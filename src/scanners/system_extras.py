from __future__ import annotations

from pathlib import Path

from src.models.items import CleanItem, Recommendation
from src.scanners.base import ProgressCb, Scanner, SCOPE_DRIVE
from src.utils import drives
from src.utils.paths import dir_size, is_hard_excluded


class SystemExtrasScanner(Scanner):
    """补充常见占空间点：传递优化、错误报告、崩溃转储、旧系统等。"""

    name = "系统与其它缓存"
    #: 见 base.SCOPE_* 说明。
    #: 刻意用 SCOPE_DRIVE 而不是 SCOPE_SYSTEM：这个扫描器同时覆盖
    #: 系统盘（Windows/ProgramData）与用户盘（%LOCALAPPDATA%）两类目标。
    #: 标成 SCOPE_SYSTEM 会让「Windows 在 C、用户目录在 D」这种机器上
    #: 的崩溃转储/WebCache 永远扫不到。
    drive_scope = SCOPE_DRIVE
    _REPORT_ONLY_LABELS = {
        "FontCache",
        "Windows.old",
        "WebCache",
        "Windows 日志",
        "Prefetch",
        "Windows Defender Scans History",
    }
    _OPTIONAL_LABELS = {
        "Windows 错误报告",
        "崩溃转储",
        "Windows Defender 日志",
        "LiveKernelReports",
        "内存转储 Minidump",
    }

    def _targets(self, drive: str) -> list[tuple[str, Path, Recommendation, str, bool]]:
        """按目标盘拼出候选路径。

        这里的条目分属两个不同的盘，必须分开算：
          * ``<盘>\\Windows`` / ``<盘>\\ProgramData`` / ``<盘>\\$WinREAgent``
            —— 跟着 Windows 安装走，只有装了系统的盘才有；
          * ``%LOCALAPPDATA%`` 下的崩溃转储、D3DSCache、INetCache、WebCache、FontCache
            —— 跟着用户目录走，用户目录搬到 D 盘时它们就在 D 盘。

        写死 ``C:\\`` 的话，Windows 装在 D 盘（或用户目录在 D 盘）就会整块漏掉。
        不属于目标盘的条目会在 ``scan`` 里被过滤掉，不会串盘。
        """
        home = Path.home()
        local = home / "AppData" / "Local"
        win = Path(f"{drive}\\Windows")
        programdata = Path(f"{drive}\\ProgramData")
        return [            (
                "传递优化缓存",
                win / "SoftwareDistribution" / "DeliveryOptimization",
                Recommendation.RECOMMEND,
                "Windows 传递优化下载缓存，删后可再下载",
                True,
            ),
            (
                "传递优化 Cache",
                win
                / "ServiceProfiles"
                / "NetworkService"
                / "AppData"
                / "Local"
                / "Microsoft"
                / "Windows"
                / "DeliveryOptimization"
                / "Cache",
                Recommendation.RECOMMEND,
                "传递优化缓存目录",
                True,
            ),
            (
                "Windows 错误报告",
                programdata / "Microsoft" / "Windows" / "WER",
                Recommendation.RECOMMEND,
                "错误报告队列，一般可清",
                True,
            ),
            (
                "崩溃转储",
                local / "CrashDumps",
                Recommendation.RECOMMEND,
                "程序崩溃 dump，排查完可删",
                False,
            ),
            (
                "DirectX 着色器缓存",
                local / "D3DSCache",
                Recommendation.RECOMMEND,
                "游戏/图形着色器缓存，删后会重建",
                False,
            ),
            (
                "网络缓存 INetCache",
                local / "Microsoft" / "Windows" / "INetCache",
                Recommendation.RECOMMEND,
                "旧版网络/IE 缓存",
                False,
            ),
            (
                "WebCache",
                local / "Microsoft" / "Windows" / "WebCache",
                Recommendation.OPTIONAL,
                "WebCache 数据库，关闭浏览器后再清更稳",
                False,
            ),
            (
                "Windows 日志",
                win / "Logs",
                Recommendation.OPTIONAL,
                "系统日志目录，可清部分占用",
                True,
            ),
            (
                "Prefetch",
                win / "Prefetch",
                Recommendation.OPTIONAL,
                "预读取文件，删除后开机/启动略慢，随后重建",
                True,
            ),
            (
                "FontCache",
                local / "Microsoft" / "Windows" / "Fonts",
                Recommendation.OPTIONAL,
                "字体相关本地数据（谨慎）",
                False,
            ),
            (
                "Windows.old",
                Path(f"{drive}\\Windows.old"),
                Recommendation.OPTIONAL,
                "升级前旧系统，确认不回退后可删，通常很大",
                True,
            ),
            (
                "WinRE 更新残留",
                Path(f"{drive}\\$WinREAgent"),
                Recommendation.OPTIONAL,
                "Windows 恢复环境更新时的中间产物，通常 10 天后由系统自动清理；"
                "实测本机 1.95 GB。确认当前没有正在进行的系统更新后再删，"
                "删后下次更新会重建",
                True,
            ),
            (
                "Windows Defender 日志",
                programdata / "Microsoft" / "Windows Defender" / "Support",
                Recommendation.RECOMMEND,
                "Defender 支持日志，一般可清",
                True,
            ),
            (
                "Windows Defender Scans History",
                programdata / "Microsoft" / "Windows Defender" / "Scans" / "History",
                Recommendation.OPTIONAL,
                "扫描历史，可选清理",
                True,
            ),
            (
                "LiveKernelReports",
                win / "LiveKernelReports",
                Recommendation.RECOMMEND,
                "内核实时转储报告",
                True,
            ),
            (
                "内存转储 Minidump",
                win / "Minidump",
                Recommendation.RECOMMEND,
                "蓝屏小转储，排查完可删",
                True,
            ),
        ]

    def _on_target_drive(self, drive: str) -> list[tuple[str, Path, Recommendation, str, bool]]:
        """从 ``_targets`` 里挑出真正属于目标盘的那些。

        ``_targets`` 刻意把两种归属的路径混在一起返回（见其文档），
        过滤单独抽成一个方法，是为了让「哪些会被留下」这件事
        只有一处定义 —— 测试可以直接验证它，而不必在测试里
        把判定条件再抄一遍（抄一遍就等于没测）。
        """
        return [
            t for t in self._targets(drive)
            if drives.normalize_letter(t[1].drive) == drive
        ]

    def scan(
        self,
        cancel_flag: dict | None = None,
        progress: ProgressCb | None = None,
    ) -> list[CleanItem]:
        if progress:
            progress(self.name, 0.0)
        drive = drives.target_drive()
        items: list[CleanItem] = []
        # 只处理目标盘上的条目：用户盘/系统盘可能不是同一个盘，
        # 让 C 盘的目标在扫 D 盘时出现，用户会以为选错了盘。
        targets = self._on_target_drive(drive)
        for i, (label, path, reco, reason, admin) in enumerate(targets):
            if cancel_flag and cancel_flag.get("cancel"):
                break
            if not path.exists() or is_hard_excluded(path):
                if progress:
                    progress(self.name, (i + 1) / max(len(targets), 1))
                continue
            size = dir_size(path, cancel_flag, max_seconds=6.0)
            if size <= 0:
                if progress:
                    progress(self.name, (i + 1) / max(len(targets), 1))
                continue
            report_only = label in self._REPORT_ONLY_LABELS
            if report_only:
                reco = Recommendation.NOT_RECOMMENDED
                reason = f"{reason}；范围可能包含系统/用户数据，仅报告不直接删除"
            elif label in self._OPTIONAL_LABELS:
                reco = Recommendation.OPTIONAL
                reason = f"{reason}；可能包含故障排查证据，确认后再清理"
            items.append(
                CleanItem.make(
                    id=f"extra:{drive}:{label}",
                    category=self.name,
                    path=str(path),
                    size_bytes=size,
                    recommendation=reco,
                    reason=f"{label}：{reason}",
                    detail=f"{label} · {drive}",
                    needs_admin=admin,
                    deletable=not report_only,
                    protection_reason="系统/用户数据目录，必须通过专用工具处理" if report_only else "",
                )
            )
            if progress:
                progress(f"{self.name}: {label}", (i + 1) / max(len(targets), 1))
        if progress:
            progress(self.name, 1.0)
        return items
