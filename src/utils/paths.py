from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Iterable, Iterator


# --- hard exclude / project helpers (keep previous API) ---

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


def normalize_path(path: str | Path) -> Path:
    try:
        return Path(path).expanduser().resolve()
    except OSError:
        return Path(path).expanduser().absolute()


def is_hard_excluded(path: str | Path) -> bool:
    p = normalize_path(path)
    parts_lower = {part.lower() for part in p.parts}
    if "system32" in parts_lower or "syswow64" in parts_lower or "winsxs" in parts_lower:
        return True
    if len(p.parts) >= 2 and p.parts[1].lower() == "boot":
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
    cur = p
    for _ in range(6):
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


def should_skip_scan(path: str | Path) -> bool:
    return is_hard_excluded(path)


def dir_size(
    path: str | Path,
    cancel_flag: dict | None = None,
    *,
    max_seconds: float = 8.0,
) -> int:
    """快速估算目录大小。超时返回已统计部分，避免整盘卡死。"""
    total = 0
    root = Path(path)
    if not root.exists():
        return 0
    if root.is_file():
        try:
            return root.stat().st_size
        except OSError:
            return 0
    start = time.monotonic()
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, onerror=lambda _e: None):
        if cancel_flag and cancel_flag.get("cancel"):
            break
        if time.monotonic() - start > max_seconds:
            break
        keep = []
        for d in dirnames:
            child = Path(dirpath) / d
            if not is_hard_excluded(child):
                keep.append(d)
        dirnames[:] = keep
        for name in filenames:
            if cancel_flag and cancel_flag.get("cancel"):
                break
            if time.monotonic() - start > max_seconds:
                break
            fp = Path(dirpath) / name
            try:
                total += fp.stat().st_size
            except OSError:
                continue
    return total


def safe_iter_files(
    root: str | Path,
    *,
    cancel_flag: dict | None = None,
    max_seconds: float = 8.0,
) -> Iterator[Path]:
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
            break
        keep = []
        for d in dirnames:
            child = Path(dirpath) / d
            if not is_hard_excluded(child):
                keep.append(d)
        dirnames[:] = keep
        for name in filenames:
            if cancel_flag and cancel_flag.get("cancel"):
                break
            if time.monotonic() - start > max_seconds:
                break
            yield Path(dirpath) / name


def existing_paths(candidates: Iterable[str | Path]) -> list[Path]:
    out: list[Path] = []
    for c in candidates:
        p = Path(os.path.expandvars(str(c))).expanduser()
        if p.exists() and not is_hard_excluded(p):
            out.append(p)
    return out
