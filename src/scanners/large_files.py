from __future__ import annotations

import os
import time
from pathlib import Path

from src.models.items import CleanItem, Recommendation
from src.scanners.base import ProgressCb, Scanner
from src.utils.paths import is_hard_excluded, is_user_protected_library, looks_like_project_dir

DEFAULT_THRESHOLD = 100 * 1024 * 1024
MAX_SECONDS = 25  # 覆盖下载/桌面/文档等，超时也返回已发现项
MAX_ITEMS = 300

_SKIP_DIR_NAMES = {
    "Windows",
    "WinSxS",
    "System32",
    "SysWOW64",
    "Program Files",
    "Program Files (x86)",
    "$Recycle.Bin",
    "System Volume Information",
    "Recovery",
    "Boot",
    "PerfLogs",
    "node_modules",
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "__pycache__",
    "WindowsApps",
    "Packages",
    "AppData",  # AppData 改由专用扫描器处理，这里不深爬
}


class LargeFilesScanner(Scanner):
    name = "大文件扫描"

    def __init__(self, threshold: int = DEFAULT_THRESHOLD) -> None:
        self.threshold = threshold

    def _roots(self) -> list[Path]:
        home = Path.home()
        candidates = [
            home / "Downloads",
            home / "下载",
            home / "Desktop",
            home / "桌面",
            home / "Videos",
            home / "视频",
            home / "Documents",
            home / "文档",
            Path(r"C:\Users\Public\Downloads"),
            Path(r"C:\Temp"),
            Path(r"C:\temp"),
        ]
        roots: list[Path] = []
        seen: set[str] = set()
        for p in candidates:
            if not p.exists() or not p.is_dir() or is_hard_excluded(p):
                continue
            key = str(p).lower()
            if key in seen:
                continue
            seen.add(key)
            roots.append(p)
        return roots

    def scan(
        self,
        cancel_flag: dict | None = None,
        progress: ProgressCb | None = None,
    ) -> list[CleanItem]:
        if progress:
            progress(self.name, 0.0)
        items: list[CleanItem] = []
        roots = self._roots()
        start = time.monotonic()
        visited = 0

        for i, base in enumerate(roots):
            if cancel_flag and cancel_flag.get("cancel"):
                break
            if time.monotonic() - start > MAX_SECONDS:
                if progress:
                    progress(f"{self.name}（时限到，已返回部分结果）", 1.0)
                break
            if progress:
                progress(f"{self.name}: {base.name}", i / max(len(roots), 1))

            for dirpath, dirnames, filenames in os.walk(base, topdown=True, onerror=lambda _e: None):
                if cancel_flag and cancel_flag.get("cancel"):
                    break
                if time.monotonic() - start > MAX_SECONDS:
                    break
                visited += 1
                keep = []
                for d in dirnames:
                    if d in _SKIP_DIR_NAMES:
                        continue
                    child = Path(dirpath) / d
                    if is_hard_excluded(child):
                        continue
                    keep.append(d)
                dirnames[:] = keep

                if visited % 40 == 0 and progress:
                    short = dirpath if len(dirpath) < 55 else "…" + dirpath[-52:]
                    progress(f"{self.name}: {short}", min(0.95, (i + 0.5) / max(len(roots), 1)))

                for name in filenames:
                    fp = Path(dirpath) / name
                    try:
                        size = fp.stat().st_size
                    except OSError:
                        continue
                    if size < self.threshold:
                        continue
                    if looks_like_project_dir(fp):
                        continue
                    reason = f"超过 {self.threshold // (1024 * 1024)}MB 的大文件，请确认后勾选"
                    if is_user_protected_library(fp):
                        reason = "位于文档/桌面等目录，请确认后勾选"
                    items.append(
                        CleanItem.make(
                            id=f"large:{fp}",
                            category=self.name,
                            path=str(fp),
                            size_bytes=size,
                            recommendation=Recommendation.NOT_RECOMMENDED,
                            reason=reason,
                        )
                    )

        items.sort(key=lambda x: x.size_bytes, reverse=True)
        items = items[:MAX_ITEMS]
        if progress:
            progress(self.name, 1.0)
        return items
