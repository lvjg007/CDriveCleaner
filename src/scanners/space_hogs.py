from __future__ import annotations

import re
import subprocess
import winreg
from pathlib import Path

from src.models.items import CleanItem, Recommendation
from src.scanners.base import ProgressCb, Scanner, SCOPE_DRIVE
from src.utils import drives
from src.utils.disk import fixed_drive_letters, is_admin
from src.utils.paths import is_hard_excluded, measure_protected_dir

# 这些是系统盘上最常见、也最容易被误删的「大户」。它们全都不进入清理队列，
# 只负责把量级摆出来 + 告诉用户该用哪个官方工具。
# 其中 WinSxS 与 winevt 落在硬排除范围内，普通扫描器看不见它们 ——
# 这正是它们长期成为盲区的原因。
#
# 路径**不含盘符**，由 ``_system_report_dirs(drive)`` 按目标盘拼出来。
# 写死 ``C:\Windows\WinSxS`` 的话，Windows 装在 D 盘（或用户在 D 盘选了扫描）
# 就会得到一个永远不存在的路径。
_SYSTEM_REPORT_RELATIVE: list[tuple[str, str, str]] = [
    (
        "组件存储 WinSxS",
        r"Windows\WinSxS",
        "Windows 组件存储。目录内含大量与 System32 共享的硬链接，"
        "按文件大小累计会高估实际占用 —— 权威数字请用 "
        "Dism /Online /Cleanup-Image /AnalyzeComponentStore（需管理员）查看；"
        "清理用同命令的 /StartComponentCleanup，加 /ResetBase 后将无法卸载已安装的更新",
    ),
    (
        "MSI 安装缓存",
        r"Windows\Installer",
        "MSI/MSP 安装包缓存：删掉能省空间，但之后修复、更新、卸载相关程序都会失败。"
        "请用 Windows 自带磁盘清理或专用 MSI 清理工具处理",
    ),
    (
        "Visual Studio / VC++ 安装缓存",
        r"ProgramData\Package Cache",
        "VS、VC++ 运行库等安装程序的缓存，修复和卸载时会用到，不建议直接删",
    ),
    (
        "Windows 事件日志",
        r"Windows\System32\winevt\Logs",
        "系统事件日志：直接删文件会丢失排障证据，"
        "应在「事件查看器」中清除日志，或用 wevtutil cl 逐个清理",
    ),
]


def _system_report_dirs(drive: str) -> list[tuple[str, Path, str]]:
    """把系统大户的相对路径拼成目标盘上的绝对路径。"""
    return [(label, Path(f"{drive}\\{rel}"), reason) for label, rel, reason in _SYSTEM_REPORT_RELATIVE]


# 测量被超时截断时的标注。WinSxS 有十几万文件，实测两种遍历方式都要两分钟以上，
# 交互式扫描只能给有界下界 —— 必须说出来，不能让用户以为是准确值。
_TRUNCATED_NOTE = "；大小统计超时，实际不小于所显示的值"

_MEMORY_MGMT_KEY = (
    r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management"
)


def _configured_pagefiles() -> list[Path]:
    """从注册表读出实际配置的页面文件路径。

    这里不能写死 ``C:\\pagefile.sys``：页面文件经常被挪到别的盘，
    写死的结果是「报告里根本看不到页面文件」，看起来像 bug 其实只是找错了地方。
    实测本机页面文件就在 ``D:\\pagefile.sys``（11 GB），C 盘压根没有这个文件。

    注册表 ``PagingFiles`` 的值有两种形态：
      * ``D:\\pagefile.sys 4096 8192`` —— 显式指定了盘符，直接取第一段；
      * ``?:\\pagefile.sys`` —— 系统托管，注册表**不记录**它最终落在哪个盘，
        只能逐固定盘根目录探测 ``pagefile.sys`` 是否存在。

    读取不需要管理员权限（已实测）。读不到时退回目标盘的固定猜测。
    """
    fallback = [Path(f"{drives.target_drive()}\\pagefile.sys")]
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _MEMORY_MGMT_KEY) as key:
            raw, _ = winreg.QueryValueEx(key, "PagingFiles")
    except OSError:
        return fallback

    paths: list[Path] = []
    for entry in raw or []:
        token = str(entry).strip().split(" ")[0] if str(entry).strip() else ""
        if not token:
            continue
        if token.startswith("?"):
            # 系统托管：位置未知，逐固定盘探测
            return [Path(f"{d}\\pagefile.sys") for d in fixed_drive_letters()]
        paths.append(Path(token))
    return paths or fallback


# vssadmin 在中文/英文系统下的「已用存储空间」行。括号里是权威字节数，
# 前面的 GB 数字受 locale 和四舍五入影响，不用它。
_SHADOW_USED_PATTERNS = (
    re.compile(r"已用卷影副本存储空间.*?\(\s*([\d,]+)\s*字节"),
    re.compile(r"Used\s+Shadow\s+Copy\s+Storage\s+space.*?\(\s*([\d,]+)\s*bytes", re.I),
)

# 卷标记行里的盘符，例如 ``卷: (C:) \\?\Volume{...}\``。
# 刻意不匹配「已用 / Used」行 —— 那些行的括号里是字节数，不是盘符。
_SHADOW_VOLUME_RE = re.compile(r"\(([A-Za-z]:)\)")


def _shadow_usage_by_drive(text: str) -> dict[str, int]:
    """把 ``vssadmin list shadowstorage`` 的输出按盘拆开。

    输出是**按卷分段的**，每段先给「卷: (C:) …」再给该卷的已用/分配/最大空间。
    必须先记住当前段属于哪个卷，否则会把别的盘的数字算到目标盘头上 ——
    用户选了 D 盘却看到 C 盘的还原点占用，比不显示更糟。

    识别不出卷归属的段落**直接丢弃**，不做「求和兜底」：
    兜底出来的数字看着合理，但属于哪个盘是错的。
    """
    per_drive: dict[str, int] = {}
    current: str | None = None
    for line in text.splitlines():
        is_used_line = any(p.search(line) for p in _SHADOW_USED_PATTERNS)
        if is_used_line:
            if current is None:
                continue
            for pattern in _SHADOW_USED_PATTERNS:
                for raw in pattern.findall(line):
                    try:
                        per_drive[current] = per_drive.get(current, 0) + int(raw.replace(",", ""))
                    except ValueError:
                        continue
            continue
        if "已用" in line or "Used" in line:
            continue
        marker = _SHADOW_VOLUME_RE.search(line)
        if marker:
            current = marker.group(1).upper()
    return per_drive


def _query_shadow_storage_size(drive: str | None = None) -> tuple[int | None, str]:
    """查询指定盘卷影副本（系统还原点）的实际占用，返回 ``(字节数, 说明)``。

    非提权下这条路是彻底堵死的，已用四条独立路径实测确认：
      * ``vssadmin list shadowstorage`` → 退出码 2，「你没有正确的权限」
      * ``Get-CimInstance Win32_ShadowStorage`` → HRESULT 0x80041014 初始化失败
      * ``root\\default:SystemRestore`` → 退出码 1
      * ``C:\\System Volume Information`` → WinError 5 拒绝访问

    所以测不到时返回 ``None``，由调用方如实标注「需管理员」，
    **绝不能拿 0 冒充**。这里有个真实的坑值得记下来：
    ``(Get-CimInstance Win32_ShadowCopy | Measure-Object).Count`` 在权限不足时
    会因为错误是非终止性的而返回 ``0`` —— 看起来像「本机没有还原点」，
    实际上只是查询失败了。任何「有没有还原点」的结论都不能基于这个 0。
    """
    target = drives.normalize_letter(drive or drives.target_drive())
    if not is_admin():
        return None, "当前未以管理员身份运行。"
    try:
        proc = subprocess.run(
            ["vssadmin", "list", "shadowstorage"],
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None, "vssadmin 无法执行。"
    text = proc.stdout.decode("gbk", errors="replace")
    if proc.returncode != 0:
        return None, "vssadmin 拒绝执行（需管理员）。"
    per_drive = _shadow_usage_by_drive(text)
    if not per_drive:
        return None, "已提权执行，但无法从 vssadmin 输出中识别卷归属。"
    size = per_drive.get(target)
    if not size:
        return 0, ""
    return size, ""


class SpaceHogsScanner(Scanner):
    """
    借鉴 BitBroom Space Hogs：只报告大户，默认不建议删除。
    休眠/页面文件/虚拟磁盘等应通过系统设置或官方工具处理。
    """

    name = "占空间报告(勿盲删)"
    #: 见 base.SCOPE_* 说明
    drive_scope = SCOPE_DRIVE

    def _file_item(self, label: str, path: Path, reason: str) -> CleanItem | None:
        if not path.exists() or is_hard_excluded(path):
            return None
        try:
            size = path.stat().st_size
        except OSError:
            return None
        if size <= 0:
            return None
        return CleanItem.make(
            id=f"hog:{label}",
            category=self.name,
            path=str(path),
            size_bytes=size,
            recommendation=Recommendation.NOT_RECOMMENDED,
            reason=reason,
            detail=f"报告项 · {label}",
            deletable=False,
            protection_reason="报告项只能展示，必须通过 Windows 系统工具处理",
        )

    def _dir_item(self, label: str, path: Path, reason: str) -> CleanItem | None:
        """报告一个目录。刻意用 measure_protected_dir 而不是 dir_size：
        这里的对象多落在硬排除范围内（WinSxS、System32\\winevt），
        用 dir_size 只会量到几十 KB，等于没量。

        注意这只是「测量时不被跳过」，与可删除性无关 —— 本方法产出的
        全部是 deletable=False，且 is_deletion_protected 是另一道独立闸门。

        ``size <= 0`` 分两种情况，不能一起丢弃：
          * 未被截断的 0 —— 目录确实是空的，丢掉；
          * 被截断的 0 —— **没测出来**，不是空。这种情况必须照样出条目，
            否则 WinSxS 这种「量不出来」的目录会从报告里消失，
            而那正是它长期成为盲区的原因。理由里会写明没测出来。
        """
        if not path.is_dir():
            return None
        size, truncated = measure_protected_dir(path, max_seconds=6.0)
        if size <= 0:
            if not truncated:
                return None
            reason = (
                f"{reason}；本次扫描未能在时限内测出大小（该目录条目极多），"
                "实际占用不为 0，请用上面提到的官方工具查看"
            )
        elif truncated:
            reason = f"{reason}{_TRUNCATED_NOTE}"
        return CleanItem.make(
            id=f"hog:dir:{label}",
            category=self.name,
            path=str(path),
            size_bytes=size,
            recommendation=Recommendation.NOT_RECOMMENDED,
            reason=reason,
            detail=f"报告项 · {label}",
            deletable=False,
            protection_reason="系统目录，必须通过官方工具处理，本工具不会删除",
        )

    def _pagefile_item(self, path: Path, size: int, *, target: str | None = None) -> CleanItem:
        """由「路径 + 大小」生成页面文件报告项。

        纯决策、不碰文件系统，因此「在目标盘上」/「在别的盘上」两个分支都能直接测。

        在别的盘上的页面文件报 0 字节并标 ``cross_drive``：它确实不占目标盘空间，
        写成真实大小会让「已扫描」总量虚高，用户会以为清了能省这么多。
        它是纯说明项（``deletable=False``），所以允许跨盘展示 ——
        ``CleanItem.make`` 会强制这个组合，可删除条目拿不到跨盘资格。
        """
        target_drive = drives.normalize_letter(target or drives.target_drive())
        on_target = path.drive.upper() == target_drive
        if on_target:
            reason = (
                "系统页面文件（虚拟内存）。不要直接删除："
                "应在「系统属性 → 高级 → 性能设置 → 高级 → 虚拟内存」中"
                "调整大小，或整体移到其它盘"
            )
            detail = f"报告项 · 页面文件 · {target_drive}"
        else:
            reason = (
                f"页面文件位于 {path.drive}（{size / 1024 ** 3:.2f} GB），"
                f"不占用 {target_drive} 空间。此项仅作说明，无需处理；"
                f"想看它的详情请把目标盘切到 {path.drive}"
            )
            detail = f"报告项 · 页面文件（在 {path.drive}，不在 {target_drive}）"
        return CleanItem.make(
            id=f"hog:pagefile:{path}",
            category=self.name,
            path=str(path),
            size_bytes=size if on_target else 0,
            recommendation=Recommendation.NOT_RECOMMENDED,
            reason=reason,
            detail=detail,
            deletable=False,
            cross_drive=not on_target,
            protection_reason="页面文件由系统独占管理，本工具不会删除",
        )

    def _pagefile_items(self) -> list[CleanItem]:
        """按注册表实际配置的位置报告页面文件。

        目标盘上的按真实大小报；目标盘一个都没有、但别的盘有时，
        就报一条 0 字节说明项 —— 否则「报告里找不到页面文件」会被当成漏扫
        （本机就是这样：页面文件在 D 盘，C 盘压根没有）。
        """
        target = drives.target_drive()
        found: list[tuple[Path, int]] = []
        for path in _configured_pagefiles():
            try:
                if not path.exists():
                    continue
                size = path.stat().st_size
            except OSError:
                continue
            if size > 0:
                found.append((path, size))

        on_target = [
            self._pagefile_item(p, s, target=target)
            for p, s in found
            if p.drive.upper() == target
        ]
        if on_target:
            return on_target
        off_target = next(((p, s) for p, s in found if p.drive.upper() != target), None)
        return [self._pagefile_item(*off_target, target=target)] if off_target else []

    def _shadow_item(self) -> CleanItem:
        """报告目标盘的卷影副本 / 系统还原点占用。

        这是系统盘上最典型的「看不见的大户」：占用几 GB 到几十 GB，
        但既不落在任何可遍历目录里（``<盘>:\\System Volume Information`` 拒绝访问），
        也不在普通扫描器视野内。测得到就报数字，测不到就如实说测不到。
        """
        target = drives.target_drive()
        svid = rf"{target}\System Volume Information"
        size, note = _query_shadow_storage_size(target)
        if size is None:
            reason = (
                f"系统还原点 / 卷影副本通常占用 {target} 数 GB 到数十 GB，"
                "但它的实际占用必须提权才能查询。"
                f"{note}"
                "请以管理员身份运行本程序，或用管理员命令行执行 "
                "vssadmin list shadowstorage 查看；"
                "在「系统属性 → 系统保护」里可调整最大使用量、删除还原点"
            )
        elif size == 0:
            reason = (
                f"{target} 上当前没有卷影副本占用（已提权查询确认）。"
                "系统保护若未开启，就不会产生还原点"
            )
        else:
            reason = (
                f"{target} 上系统还原点 / 卷影副本的实际占用。"
                "请在「系统属性 → 系统保护」中调整最大使用量或删除旧还原点；"
                f"直接删 {svid} 会破坏还原功能"
            )
        return CleanItem.make(
            id=f"hog:shadowstorage:{target}",
            category=self.name,
            path=svid,
            size_bytes=size or 0,
            recommendation=Recommendation.NOT_RECOMMENDED,
            reason=reason,
            detail=f"报告项 · 卷影副本 / 系统还原点 · {target}",
            deletable=False,
            needs_admin=True,
            protection_reason="卷影副本必须通过 vssadmin 或「系统保护」界面管理，本工具不会删除",
        )

    def _vhdx_items(self, cancel_flag: dict | None) -> list[CleanItem]:
        """WSL / Docker 的虚拟磁盘。它们只可能出现在用户目录下。

        单独拆出来是因为它有自己的根（用户目录），与目标盘无关 ——
        只有目标盘就是用户盘时调用方才会走到这里。
        """
        local = Path.home() / "AppData" / "Local"
        search_roots = [
            local / "Packages",
            local / "Docker",
            local / "wsl",
        ]
        items: list[CleanItem] = []
        for root in search_roots:
            if cancel_flag and cancel_flag.get("cancel"):
                break
            if not root.exists():
                continue
            try:
                for p in root.rglob("*.vhdx"):
                    if len(items) >= 15:
                        break
                    if is_hard_excluded(p):
                        continue
                    try:
                        size = p.stat().st_size
                    except OSError:
                        continue
                    if size < 100 * 1024 * 1024:
                        continue
                    items.append(
                        CleanItem.make(
                            id=f"hog:vhdx:{p}",
                            category=self.name,
                            path=str(p),
                            size_bytes=size,
                            recommendation=Recommendation.NOT_RECOMMENDED,
                            reason="WSL/Docker 虚拟磁盘：请用 wsl --shutdown 后 diskpart compact，勿直接删正在使用的 vhdx",
                            detail=f"报告项 · 虚拟磁盘 · {p.name}",
                            deletable=False,
                            protection_reason="虚拟磁盘必须通过 WSL/Docker 或磁盘工具处理",
                        )
                    )
            except OSError:
                continue
        return items

    def scan(
        self,
        cancel_flag: dict | None = None,
        progress: ProgressCb | None = None,
    ) -> list[CleanItem]:
        if progress:
            progress(self.name, 0.0)
        items: list[CleanItem] = []
        drive = drives.target_drive()

        # 页面文件：按注册表实际配置的位置报，不写死 C 盘
        items.extend(self._pagefile_items())
        if progress:
            progress(self.name, 0.1)

        # 休眠文件 / 交换文件：位于系统盘根目录
        for label, path, reason in (
            (
                "休眠文件 hiberfil.sys",
                Path(rf"{drive}\hiberfil.sys"),
                "休眠与快速启动的镜像文件。关闭休眠可释放（需管理员执行 "
                "powercfg /hibernate off，会同时失去快速启动）；不要直接删这个系统文件",
            ),
            (
                "交换文件 swapfile.sys",
                Path(rf"{drive}\swapfile.sys"),
                "供 UWP/商店应用使用的交换文件，由系统管理。"
                "删掉会被系统立刻重建，请勿手动处理",
            ),
        ):
            if cancel_flag and cancel_flag.get("cancel"):
                break
            it = self._file_item(label, path, reason)
            if it:
                items.append(it)
        if progress:
            progress(self.name, 0.2)

        # 卷影副本 / 系统还原点（提权才测得到，测不到也要如实出现）
        items.append(self._shadow_item())
        if progress:
            progress(self.name, 0.3)

        # 系统大户目录（含硬排除范围内的盲区）—— 只有装了 Windows 的盘才有
        report_dirs = _system_report_dirs(drive)
        for i, (label, path, reason) in enumerate(report_dirs):
            if cancel_flag and cancel_flag.get("cancel"):
                break
            it = self._dir_item(label, path, reason)
            if it:
                items.append(it)
            if progress:
                progress(f"{self.name}: {label}", (i + 1) / max(len(report_dirs), 1))

        # WSL / Docker vhdx（常见占坑）。它们在用户目录下，只有目标盘是用户盘时才有
        if drives.normalize_letter(drive) == drives.profile_drive():
            items.extend(self._vhdx_items(cancel_flag))

        if progress:
            progress(self.name, 1.0)
        return items
