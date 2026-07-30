from __future__ import annotations

import os
import time
from pathlib import Path

from src.models.items import CleanItem, Recommendation
from src.scanners.base import ProgressCb, Scanner
from src.utils.paths import is_hard_excluded, looks_like_project_dir

_MAX_SECONDS = 20
_MAX_ITEMS = 200
_SKIP = {
    "Windows", "System32", "SysWOW64", "WinSxS", "Program Files",
    "Program Files (x86)", "$Recycle.Bin", "System Volume Information",
    "node_modules", ".git", "Packages", "WindowsApps",
}


class EmptyFolderScanner(Scanner):
    """借鉴 Scour/NeatDisk：查找空目录。"""

    name = "空目录"

    def _roots(self) -> list[Path]:
        home = Path.home()
        return [
            home / "Downloads",
            home / "下载",
            home / "Desktop",
            home / "桌面",
            home / "Documents",
            home / "文档",
            home / "AppData" / "Local" / "Temp",
            Path(os.environ.get("TEMP", "")),
            Path(r"C:\Temp"),
        ]

    def scan(
        self,
        cancel_flag: dict | None = None,
        progress: ProgressCb | None = None,
    ) -> list[CleanItem]:
        if progress:
            progress(self.name, 0.0)
        items: list[CleanItem] = []
        roots = [r for r in self._roots() if r and r.exists()]
        start = time.monotonic()
        for ri, root in enumerate(roots):
            if cancel_flag and cancel_flag.get("cancel"):
                break
            if is_hard_excluded(root):
                continue
            if progress:
                progress(f"{self.name}: {root.name}", ri / max(len(roots), 1))
            # 自底向上找空目录
            for dirpath, dirnames, filenames in os.walk(root, topdown=False, onerror=lambda _e: None):
                if cancel_flag and cancel_flag.get("cancel"):
                    break
                if time.monotonic() - start > _MAX_SECONDS:
                    break
                p = Path(dirpath)
                if p == root or is_hard_excluded(p):
                    continue
                if any(part in _SKIP for part in p.parts):
                    continue
                if looks_like_project_dir(p):
                    continue
                try:
                    # 空：无文件且无子目录（walk bottom-up 时子目录可能已空）
                    if any(p.iterdir()):
                        # 再确认：仅含空子目录也不算严格空；只收真正空
                        continue
                except OSError:
                    continue
                items.append(
                    CleanItem.make(
                        id=f"empty:{p}",
                        category=self.name,
                        path=str(p),
                        size_bytes=0,
                        recommendation=Recommendation.OPTIONAL,
                        reason="空目录，删除不影响文件内容",
                        detail=f"空目录 · {p.name}",
                    )
                )
                if len(items) >= _MAX_ITEMS:
                    break
            if len(items) >= _MAX_ITEMS or time.monotonic() - start > _MAX_SECONDS:
                break
        if progress:
            progress(self.name, 1.0)
        return items
