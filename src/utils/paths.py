from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Iterable, Iterator


# --- hard exclude / project helpers (keep previous API) ---

#: 盘根下必须整体排除的目录名（小写）。这些目录**每个盘都可能有**，
#: 不能只写 C 盘的那几个 —— 工具现在能扫 D:/E:，
#: 而 ``D:\Recovery``、``E:\System Volume Information`` 和 C 盘的一样不能碰。
_HARD_ROOT_NAMES = {
    "boot",
    "recovery",
    "system volume information",
}

#: 路径中任意一段叫这些名字就整体排除（与盘符无关）。
_HARD_ANY_PART_NAMES = {
    "system32",
    "syswow64",
    "winsxs",
}

_HARD_EXACT = {
    Path(r"C:\Windows\System32"),
    Path(r"C:\Windows\SysWOW64"),
    Path(r"C:\Windows\WinSxS"),
    Path(r"C:\Boot"),
    Path(r"C:\Recovery"),
}

_PROJECT_MARKERS = {
    ".git",
    "package.json",
    ".sln",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "CMakeLists.txt",
}

_USER_PROTECT_NAMES = {
    "Documents",
    "Desktop",
    "Pictures",
    "Videos",
    "Music",
}

_SYSTEM_REPORT_FILES = {"hiberfil.sys", "pagefile.sys", "swapfile.sys"}

#: 遍历时限的宽容倍数。超时判定在「一个文件都还没数到」时会放宽到这个倍数 ——
#: 否则 ``C:\Windows\WinSxS`` 这种「根目录十几万条目、文件都在下一层」的目录，
#: 光列举根目录就要 3-5 秒，时限会在拿到任何数据前触发，返回一个
#: 看起来像「空目录」的 0。宁可多花几秒，也不要给一个误导性的数字。
_WALK_GRACE_FACTOR = 3.0


def normalize_path(path: str | Path) -> Path:
    try:
        return Path(path).expanduser().resolve()
    except OSError:
        return Path(path).expanduser().absolute()


def canonical_path_key(path: str | Path) -> str:
    """Return a case-insensitive key used for de-duplicating clean targets.

    Reparse points are resolved to their target first. This is required for
    correctness, not cosmetics: ``Application Data`` and ``AppData\\Roaming``
    are two names for one tree, and an unresolved key would let the
    parent/child collapse in ``effective_clean_targets`` treat them as
    separate targets — double-counting the space and deleting the same tree
    twice through two different paths.
    """
    raw = Path(os.path.expandvars(str(path))).expanduser()
    if is_reparse_point(raw):
        try:
            raw = Path(os.path.realpath(raw))
        except (OSError, ValueError):
            pass
    try:
        absolute = raw.absolute()
    except OSError:
        absolute = raw
    value = os.path.normpath(str(absolute))
    if os.name == "nt":
        value = _windows_long_path(value)
    return os.path.normcase(value)


def _windows_long_path(value: str) -> str:
    """Expand Windows 8.3 aliases without changing symlink policy."""
    try:
        import ctypes
        from ctypes import wintypes

        get_long = ctypes.windll.kernel32.GetLongPathNameW
        get_long.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        get_long.restype = wintypes.DWORD
        size = 32768
        buffer = ctypes.create_unicode_buffer(size)
        length = get_long(value, buffer, size)
        if length and length < size:
            return buffer.value
    except (AttributeError, OSError):
        pass
    return value


def is_reparse_point(path: str | Path) -> bool:
    """是否为重解析点（junction / symlink / 其它 reparse tag）。

    Windows 上 ``Path.is_symlink()`` 对目录 junction 一律返回 False ——
    实测家目录里的 ``Application Data`` / ``Local Settings`` / ``Cookies``
    ``st_reparse_tag`` 都是 ``0xA0000003``（IO_REPARSE_TAG_MOUNT_POINT），
    而 ``S_ISLNK`` 为假。后果是 ``shutil.rmtree`` 会顺着 junction 把**目标目录
    的真实内容**删掉：删 ``Application Data`` 等于清空 ``AppData\\Roaming``。

    因此凡是「这个路径能不能删」的判断，都必须走这里，而不是 ``is_symlink()``。
    """
    p = Path(path)
    try:
        if p.is_symlink():
            return True
    except (OSError, ValueError):
        pass
    isjunction = getattr(os.path, "isjunction", None)  # Python 3.12+
    if isjunction is not None:
        try:
            if isjunction(p):
                return True
        except (OSError, ValueError):
            pass
    try:
        return bool(getattr(os.lstat(p), "st_reparse_tag", 0))
    except (OSError, ValueError):
        return False


def mark_scan_partial(cancel_flag: dict | None, category: str | None = None) -> None:
    """Record that the current scanner returned a time-bounded partial result."""
    if cancel_flag is None:
        return
    meta = cancel_flag.setdefault("_scan_meta", {})
    categories = meta.setdefault("partial_categories", set())
    name = category or cancel_flag.get("_scan_current")
    if name:
        categories.add(str(name))


def is_hard_excluded(path: str | Path) -> bool:
    """是否落在硬排除范围（系统目录等）。

    这里刻意不做符号链接解析。``normalize_path`` 走的 ``Path.resolve()``
    每一层目录都要问一次文件系统，而本函数在 ``dir_size`` / ``safe_iter_files``
    里对**每个子目录**都会被调用 —— 实测遍历 3897 个目录耗时 1.9s，
    纯遍历只需 0.3s，是整轮扫描最大的单点开销，直接导致大目录的大小
    被超时截断（``~/.trae-cn/extensions`` 真实 1.69 GB，2 秒上限只量到 73 MB）。

    判定只依赖路径前缀，词法归一就足够。符号链接指向系统目录的情况
    由 ``is_deletion_protected`` 统一拦截，不靠这里。
    """
    raw = Path(os.path.expandvars(str(path))).expanduser()
    if raw.is_absolute():
        value = os.path.normpath(str(raw))
    else:
        value = os.path.normpath(os.path.join(os.getcwd(), str(raw)))
    p = Path(value)
    parts_lower = [part.lower() for part in p.parts]
    parts_set = set(parts_lower)
    if parts_set & _HARD_ANY_PART_NAMES:
        return True
    # ``parts[0]`` 是盘符（``"C:\\"``），``parts[1]`` 才是盘根下的第一层目录。
    # 这样判定与盘符无关：``D:\\Recovery`` 与 ``C:\\Recovery`` 一样被排除。
    if len(parts_lower) >= 2 and parts_lower[1] in _HARD_ROOT_NAMES:
        return True
    for exact in _HARD_EXACT:
        try:
            p.relative_to(exact)
            return True
        except ValueError:
            pass
        if p == exact:
            return True
    return False


def is_user_protected_library(path: str | Path) -> bool:
    p = normalize_path(path)
    home = Path.home()
    for name in list(_USER_PROTECT_NAMES) + ["文档", "桌面", "图片", "视频", "音乐"]:
        lib = home / name
        try:
            if lib.exists():
                p.relative_to(normalize_path(lib))
                return True
        except (ValueError, OSError):
            continue
    return False


def looks_like_project_dir(path: str | Path) -> bool:
    p = normalize_path(path)
    if p.is_file():
        p = p.parent
    home = normalize_path(Path.home())
    appdata = normalize_path(home / "AppData")
    cur = p
    for _ in range(6):
        # A marker in the user profile or AppData root must not protect every
        # cache/temp child below it. Project markers are meaningful below those roots.
        if cur in {home, appdata}:
            break
        try:
            if not cur.exists() or not cur.is_dir():
                break
            names = {x.name for x in cur.iterdir()}
        except OSError:
            break
        if names & _PROJECT_MARKERS:
            return True
        if cur.parent == cur:
            break
        cur = cur.parent
    return False


def is_deletion_protected(path: str | Path) -> bool:
    """Return whether a path must never be deleted by the cleaner."""
    raw = Path(path).expanduser()
    # junction / symlink：删它打到的是目标目录，必须整体拒绝
    if is_reparse_point(raw):
        return True
    p = normalize_path(raw)
    if is_hard_excluded(p):
        return True

    if p.name.lower() in _SYSTEM_REPORT_FILES and p.parent == Path(p.anchor):
        return True

    home = normalize_path(Path.home())
    font_roots = [
        home / "AppData" / "Local" / "Microsoft" / "Windows" / "Fonts",
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
    ]
    for fonts in font_roots:
        try:
            p.relative_to(fonts)
            return True
        except ValueError:
            continue

    return looks_like_project_dir(p)


def should_skip_scan(path: str | Path) -> bool:
    return is_hard_excluded(path)


def dir_size(
    path: str | Path,
    cancel_flag: dict | None = None,
    *,
    max_seconds: float = 8.0,
) -> int:
    """快速估算目录大小。超时返回已统计部分，避免整盘卡死。"""
    return dir_size_ex(path, cancel_flag, max_seconds=max_seconds)[0]


def dir_size_ex(
    path: str | Path,
    cancel_flag: dict | None = None,
    *,
    max_seconds: float = 8.0,
) -> tuple[int, bool]:
    """同 ``dir_size``，但额外返回「是否因超时被截断」。

    被截断时返回的是**下界**，不是真实大小。目录里小文件多的话，几秒钟
    可能只走完一小部分 —— 实测 ``~/.trae-cn/extensions`` 真实 1.69 GB，
    给 2 秒上限只量到 56 MB。调用方必须据此在界面上标注，
    否则用户会按差了 30 倍的量级去判断该不该删。

    **超时不会在数到任何文件之前触发**（见 ``_WALK_GRACE_FACTOR``）：
    否则一个「根目录条目极多、文件都在下一层」的目录会返回 0，
    而 0 看起来像「这个目录是空的」—— 比不报更糟。
    """
    total = 0
    root = Path(path)
    if not root.exists():
        return 0, False
    if root.is_file():
        try:
            return root.stat().st_size, False
        except OSError:
            return 0, False
    start = time.monotonic()
    deadline = start + max_seconds
    hard_deadline = start + max_seconds * _WALK_GRACE_FACTOR
    truncated = False
    counted_files = 0
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, onerror=lambda _e: None):
        if cancel_flag and cancel_flag.get("cancel"):
            break
        now = time.monotonic()
        # 还没数到任何文件时只受「硬时限」约束，保证不会给出误导性的 0
        if (counted_files > 0 and now > deadline) or now > hard_deadline:
            mark_scan_partial(cancel_flag)
            truncated = True
            break
        keep = []
        for d in dirnames:
            child = Path(dirpath) / d
            # junction/symlink 不进入：内容算在目标目录头上，进去就重复计量
            if is_reparse_point(child):
                continue
            if not is_hard_excluded(child):
                keep.append(d)
        dirnames[:] = keep
        for name in filenames:
            if cancel_flag and cancel_flag.get("cancel"):
                break
            if time.monotonic() > hard_deadline:
                mark_scan_partial(cancel_flag)
                truncated = True
                break
            fp = Path(dirpath) / name
            try:
                total += fp.stat().st_size
                counted_files += 1
            except OSError:
                continue
    return total, truncated


def measure_protected_dir(
    path: str | Path,
    cancel_flag: dict | None = None,
    *,
    max_seconds: float = 6.0,
) -> tuple[int, bool]:
    """测量被硬排除规则挡住的目录（WinSxS、事件日志等）。返回 (字节, 是否截断)。

    **仅供报告使用。** 它绕过的是「遍历时跳过」这一层，与「能不能删」无关：
    删除安全由 ``CleanItem.deletable`` 和 ``is_deletion_protected`` 两道独立闸门
    把守，本函数不参与其中任何一道 —— WinSxS 这类目录即便被标成可删，
    ``is_deletion_protected`` 仍会拦下。

    截断时返回的是**下界**。WinSxS 有十几万文件，实测两种遍历方式都要两分钟以上，
    交互式扫描里只能给一个有界下界，调用方必须在理由里说明。

    与 ``dir_size_ex`` 一样，超时不会在数到任何文件之前触发 —— 见
    ``_WALK_GRACE_FACTOR``。这一点对 WinSxS 尤其关键：它的根目录有十几万条目，
    只列举根目录就要好几秒，早期版本会因此返回 0，而调用方把 0 当成
    「目录是空的」直接丢弃条目 —— 那个刚修好的盲区会原样回来。

    另需注意 WinSxS 内含大量与 System32 共享的硬链接，按文件大小累计会**高估**
    实际占用，权威数字只能由
    ``Dism /Online /Cleanup-Image /AnalyzeComponentStore``（需管理员）给出。
    """
    total = 0
    root = Path(path)
    if not root.exists():
        return 0, False
    start = time.monotonic()
    deadline = start + max_seconds
    hard_deadline = start + max_seconds * _WALK_GRACE_FACTOR
    truncated = False
    counted_files = 0
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, onerror=lambda _e: None):
        if cancel_flag and cancel_flag.get("cancel"):
            break
        now = time.monotonic()
        # 还没数到任何文件时只受硬时限约束，保证不会给出误导性的 0
        if (counted_files > 0 and now > deadline) or now > hard_deadline:
            mark_scan_partial(cancel_flag)
            truncated = True
            break
        # 只挡重解析点；这里刻意不过滤 is_hard_excluded，否则量不到目标本身
        dirnames[:] = [d for d in dirnames if not is_reparse_point(Path(dirpath) / d)]
        for name in filenames:
            if time.monotonic() > hard_deadline:
                mark_scan_partial(cancel_flag)
                truncated = True
                break
            try:
                total += os.stat(os.path.join(dirpath, name)).st_size
                counted_files += 1
            except OSError:
                continue
    return total, truncated


def safe_iter_files(
    root: str | Path,
    *,
    cancel_flag: dict | None = None,
    max_seconds: float = 8.0,
    skip_names: frozenset[str] | None = None,
) -> Iterator[Path]:
    """安全遍历目录下的文件。

    ``skip_names`` 是**额外**的目录名跳过表（小写比较），用于整盘遍历时
    避开 ``Windows`` / ``Program Files`` / ``$Recycle.Bin`` 这类目录 ——
    它们不在硬排除范围内，但内容不属于「用户文件」。
    硬排除规则仍然照常生效，两者是叠加关系。
    """
    root_p = Path(root)
    if not root_p.exists():
        return
    if is_hard_excluded(root_p):
        return
    start = time.monotonic()
    for dirpath, dirnames, filenames in os.walk(root_p, topdown=True, onerror=lambda _e: None):
        if cancel_flag and cancel_flag.get("cancel"):
            break
        if time.monotonic() - start > max_seconds:
            mark_scan_partial(cancel_flag)
            break
        keep = []
        for d in dirnames:
            if skip_names and d.lower() in skip_names:
                continue
            child = Path(dirpath) / d
            # junction/symlink 不进入：内容算在目标目录头上，进去就重复计量
            if is_reparse_point(child):
                continue
            if not is_hard_excluded(child):
                keep.append(d)
        dirnames[:] = keep
        for name in filenames:
            if cancel_flag and cancel_flag.get("cancel"):
                break
            if time.monotonic() - start > max_seconds:
                mark_scan_partial(cancel_flag)
                break
            yield Path(dirpath) / name


def existing_paths(candidates: Iterable[str | Path]) -> list[Path]:
    """把候选路径变成「真实存在、且互不重复」的路径列表。

    重复是这里必须处理掉的：候选来自环境变量与家目录的混合，
    真机上 ``%TEMP%`` 与 ``<家目录>\\AppData\\Local\\Temp`` 就是同一个
    目录的两种写法（前者是 8.3 短名）。留着重复项等于让调用方
    重复计量同一个目录 —— 「临时文件 2 GB」会出现两次，
    清理后释放的空间也对不上。

    去重键用 ``canonical_path_key``（与删除目标去重共用同一套语义），
    但**保留候选里第一次出现的写法**用于展示 —— 顺序因此有意义。
    """
    out: list[Path] = []
    seen: set[str] = set()
    for c in candidates:
        if c is None or not str(c).strip():
            continue
        p = Path(os.path.expandvars(str(c))).expanduser()
        if not p.exists() or is_hard_excluded(p):
            continue
        key = canonical_path_key(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out
