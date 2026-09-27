"""盘符基础设施：枚举、分类、容量，以及「当前目标盘」状态。

这个模块存在的理由：工具原本只认 C 盘，把盘符写死在几十个地方。
要支持扫其它盘，必须先有一个地方能回答四个问题：

1. 本机有哪些固定盘？（``list_drives``）
2. 哪个盘装了 Windows？（``system_drive`` / ``has_windows``）
3. 哪个盘放着用户目录？（``profile_drive``）
4. 这次扫描的是哪个盘？（``target_drive`` / ``set_target_drive``）

第 2、3 问是关键。用户配置类扫描器（AI 工具数据、家目录残留、浏览器缓存…）
读的是 ``Path.home()``，它们**只存在于用户目录所在的那个盘**。
在 D 盘上重跑它们只会把 C 盘的结果再报一遍 —— 所以必须能判定
「这个扫描器在这个盘上有没有意义」，见 ``Scanner.applies_to``。

``target_drive`` 刻意做成模块级状态而不是逐层传参：扫描器有 22 个，
逐个改签名噪音太大，而且这是单线程桌面程序，同一时刻只有一轮扫描。
需要隔离时用 ``use_drive`` 上下文管理器。
"""
from __future__ import annotations

import ctypes
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from src.utils.disk import DriveUsage, fixed_drive_letters
from src.utils.paths import canonical_path_key


def _normalize(letter: str | Path) -> str:
    """把各种写法归一成 ``"C:"``。非法输入返回空串。"""
    text = str(letter).strip().upper().rstrip("\\/")
    if not text:
        return ""
    if len(text) == 1 and text.isalpha():
        text += ":"
    if len(text) == 2 and text[0].isalpha() and text[1] == ":":
        return text
    return ""


#: 公开别名。别的模块需要归一化盘符时用这个，别去碰 ``_normalize``。
normalize_letter = _normalize


def _system_drive() -> str:
    """Windows 安装所在盘，取自 ``%SystemRoot%``（形如 ``C:\\Windows``）。"""
    root = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or ""
    letter = _normalize(Path(root).drive) if root else ""
    return letter or "C:"


def _profile_drive() -> str:
    """用户目录所在盘。用户目录可以整个搬到 D 盘，不能假定是 C。"""
    try:
        return _normalize(Path.home().drive) or "C:"
    except (OSError, RuntimeError):
        return "C:"


def system_drive() -> str:
    return _system_drive()


def profile_drive() -> str:
    return _profile_drive()


def drive_root(letter: str | Path) -> Path:
    """``"C:"`` → ``Path("C:\\\\")``。

    非法盘符抛 ``ValueError``，**不退回 C 盘**。这一点是刻意的：
    静默退回意味着「界面显示 D 盘、实际扫 C 盘」，
    对一个会删文件的工具来说这是最不能有的行为 ——
    宁可当场报错，也不要删错盘。
    """
    normalized = _normalize(letter)
    if not normalized:
        raise ValueError(f"非法盘符: {letter!r}")
    return Path(f"{normalized}\\")


def system_root(letter: str | Path) -> Path | None:
    """该盘上的 ``\\Windows`` 目录；没有 Windows 安装时返回 ``None``。

    注意系统盘不一定装了 Windows 在 ``\\Windows`` —— 有人会把安装目录改名。
    这里只认 ``\\Windows`` 存在与否，够用且不会误判。
    """
    normalized = _normalize(letter)
    if not normalized:
        return None
    candidate = Path(f"{normalized}\\Windows")
    try:
        return candidate if candidate.is_dir() else None
    except OSError:
        return None


def has_windows(letter: str | Path) -> bool:
    return system_root(letter) is not None


def _volume_label_and_fs(letter: str) -> tuple[str, str]:
    """读卷标与文件系统。取不到就返回空串，不抛异常。"""
    try:
        from ctypes import wintypes

        get_volume = ctypes.windll.kernel32.GetVolumeInformationW
        get_volume.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPWSTR,
            wintypes.DWORD,
        ]
        get_volume.restype = wintypes.BOOL
        name_buf = ctypes.create_unicode_buffer(261)
        fs_buf = ctypes.create_unicode_buffer(261)
        ok = get_volume(
            f"{letter}\\", name_buf, 261, None, None, None, fs_buf, 261
        )
        if ok:
            return name_buf.value.strip(), fs_buf.value.strip()
    except Exception:
        pass
    return "", ""


@dataclass(frozen=True)
class DriveInfo:
    """一个固定盘的静态信息 + 容量。"""

    letter: str
    label: str
    fs: str
    total: int
    free: int
    is_system: bool
    is_profile: bool

    @property
    def used(self) -> int:
        return max(0, self.total - self.free)

    @property
    def used_pct(self) -> float:
        if self.total <= 0:
            return 0.0
        return self.used * 100.0 / self.total

    @property
    def kind(self) -> str:
        if self.is_system:
            return "系统盘"
        if self.is_profile:
            return "用户盘"
        return "数据盘"

    @property
    def title(self) -> str:
        """下拉框里显示的文案，例如 ``C: 系统盘（Windows）``。"""
        suffix = f"（{self.label}）" if self.label else ""
        return f"{self.letter} {self.kind}{suffix}"

    def usage(self) -> DriveUsage:
        return DriveUsage(total=self.total, used=self.used, free=self.free)


def drive_usage(letter: str | Path) -> DriveUsage:
    """读取指定盘的容量。盘不存在时抛 ``OSError``（与 ``shutil.disk_usage`` 一致）。"""
    import shutil

    normalized = _normalize(letter)
    if not normalized:
        raise OSError(f"非法盘符: {letter!r}")
    usage = shutil.disk_usage(f"{normalized}\\")
    return DriveUsage(total=usage.total, used=usage.used, free=usage.free)


def list_drives() -> list[DriveInfo]:
    """枚举所有固定盘。系统盘排最前，其余按盘符顺序。

    只列固定盘：可移动盘和网络盘拔掉就走，拿来当清理目标不安全。
    """
    sys_letter = _system_drive()
    prof_letter = _profile_drive()
    drives: list[DriveInfo] = []
    for letter in fixed_drive_letters():
        try:
            usage = drive_usage(letter)
        except OSError:
            continue
        label, fs = _volume_label_and_fs(letter)
        drives.append(
            DriveInfo(
                letter=letter,
                label=label,
                fs=fs,
                total=usage.total,
                free=usage.free,
                is_system=letter == sys_letter,
                is_profile=letter == prof_letter,
            )
        )
    drives.sort(key=lambda d: (not d.is_system, d.letter))
    return drives


def get_drive_info(letter: str | Path) -> DriveInfo | None:
    normalized = _normalize(letter)
    if not normalized:
        return None
    for info in list_drives():
        if info.letter == normalized:
            return info
    return None


# --------------------------------------------------------------- 目标盘状态

_target_drive: str | None = None


def target_drive() -> str:
    """当前扫描目标盘。默认系统盘。

    显式设过就记住；否则每次都重新推断（用户目录可能在运行期间被搬走，
    虽然罕见，但重新推断的代价只是一次 ``Path.home()``）。
    """
    if _target_drive:
        return _target_drive
    return _system_drive()


def set_target_drive(letter: str | Path | None) -> str:
    """设置目标盘。传 ``None`` 表示恢复「跟随系统盘」。

    **非法盘符是空操作，不是重置。** 这一点必须分清：
    传 ``None`` 是「我不指定了，你自己推断」，传 ``"垃圾"`` 是「输入错了」。
    把后者也当成重置，会让用户切到 D 盘的选择被一次误输入悄悄改回 C 盘 ——
    界面上还显示着 D，实际扫的是 C。返回值是设置后实际生效的盘符。
    """
    global _target_drive
    if letter is None:
        _target_drive = None
        return target_drive()
    normalized = _normalize(letter)
    if not normalized:
        return target_drive()
    _target_drive = normalized
    return target_drive()


@contextmanager
def use_drive(letter: str | Path | None) -> Iterator[str]:
    """临时切换目标盘，退出时还原。测试用。

    ``with use_drive("D:"): ...``
    """
    global _target_drive
    previous = _target_drive
    try:
        yield set_target_drive(letter)
    finally:
        _target_drive = previous


#: 从盘根开始遍历时要跳过的目录名（一律小写比较）。
#:
#: 分三类，都不能进去：
#:   * 系统目录 —— 内容不是「垃圾」，进去只会翻出大量误报，
#:     而且 ``Windows`` 一个目录就够把时限吃光；
#:   * 归属别的扫描器的目录 —— ``$Recycle.Bin`` 有回收站扫描器，
#:     ``ProgramData`` / ``AppData`` 有系统与其它缓存扫描器，
#:     从盘根再爬一遍只会重复报同一批文件；
#:   * 工程目录 —— ``.git`` / ``node_modules`` 里的文件不是用户的「大文件」。
ROOT_SKIP_DIR_NAMES = frozenset(
    {
        "windows",
        "winsxs",
        "system32",
        "syswow64",
        "program files",
        "program files (x86)",
        "programdata",
        "$recycle.bin",
        "system volume information",
        "recovery",
        "boot",
        "perflogs",
        "windowsapps",
        "appdata",
        "packages",
        "node_modules",
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "__pycache__",
    }
)


def on_drive(path: str | Path, drive: str | Path) -> bool:
    """路径是否落在指定盘上。

    无法判断盘符时按「不在」处理 —— 遍历型扫描器宁可少扫一个根，
    也不能把别的盘扫进来：多扫一个目录只是慢，错盘扫描是错报告。
    """
    letter = normalize_letter(Path(path).drive)
    return bool(letter) and letter == normalize_letter(drive)


def dedupe_paths(paths: list[Path]) -> list[Path]:
    """按文件系统标识去重，保持原顺序。

    用 ``canonical_path_key`` 而不是字符串比较：真机上 ``%TEMP%`` 就是
    8.3 短名形式（``C:\\Users\\LVJING~1\\...``），与
    ``<家目录>\\AppData\\Local\\Temp`` 指的是同一个目录，但字符串不一样。
    不去重的话同一批文件会被两个根各扫一遍、各报一次。

    复用 ``canonical_path_key`` 而不是自己写一套：它已经处理了重解析点
    与 8.3 别名，且与「删除目标去重」共用同一套语义 —— 两套「同不同一个
    路径」的判定并存，迟早会给出互相矛盾的答案。
    """
    seen: set[str] = set()
    out: list[Path] = []
    for p in paths:
        key = canonical_path_key(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def roots_for_search_scanner(drive: str | Path, home_roots: list[Path]) -> list[Path]:
    """给「大文件 / 重复文件 / 空目录」这类遍历型扫描器挑根目录。

    目标盘就是用户盘时，沿用按用户目录细分的根（下载、桌面、文档…）——
    这些才是用户真正在意的地方，也避免了整盘遍历。

    目标盘不是用户盘时，只能从盘根开始走：数据盘上没有任何已知的
    「垃圾目录」约定，能做的就是带跳过表地把整盘过一遍，
    让用户自己看见哪里占地方。

    盘根一定进跳过表判定 —— ``<盘>:\\Windows`` 这类目录
    即便在数据盘上也不该被当成候选。

    **返回的每一个根都保证落在目标盘上。** 这条不变量由本函数统一兜住，
    而不是指望 7 个调用方各自记得 —— 真机上踩过一次：``large_files``
    的候选里写死了 ``C:\\Users\\Public\\Downloads``，一旦用户目录被搬到
    D 盘，选 D 盘扫描时它照样会去遍历 C 盘的那个目录。多扫一个目录只是
    慢，把 C 盘的文件报成 D 盘的垃圾才是真问题。所以传进来的候选只要
    不在目标盘上就丢掉。

    非法盘符返回空列表，不退回 C 盘：退回意味着「调用方以为在扫 D 盘，
    实际扫了 C 盘」，这类静默错盘对删除工具是致命的。
    """
    normalized = normalize_letter(drive)
    if not normalized:
        return []
    if normalized == profile_drive():
        candidates = [p for p in home_roots if on_drive(p, normalized) and p.exists()]
    else:
        root = drive_root(normalized)
        candidates = [root] if root.exists() else []
    return dedupe_paths(candidates)
