from __future__ import annotations

import os
import time
from pathlib import Path

from src.models.items import CleanItem, Recommendation
from src.scanners.base import ProgressCb, Scanner, SCOPE_DRIVE
from src.utils import drives
from src.utils.paths import is_hard_excluded, looks_like_project_dir, mark_scan_partial

_MAX_SECONDS = 20
_MAX_ITEMS = 200
#: 盘根遍历时用共享跳过表（小写比较）。
_SKIP = drives.ROOT_SKIP_DIR_NAMES


class EmptyFolderScanner(Scanner):
    """借鉴 Scour/NeatDisk：查找空目录。"""

    name = "空目录"
    #: 见 base.SCOPE_* 说明
    drive_scope = SCOPE_DRIVE

    def _roots(self) -> list[Path]:
        """用户盘看下载/桌面/文档与临时目录；其它盘从盘根走一遍。

        刻意不再写死 ``C:\\Temp``：目标盘是数据盘时，盘根遍历本来就覆盖它；
        目标盘是用户盘时，``<用户盘>:\\Temp`` 由「系统临时文件」扫描器负责，
        在这里再来一遍属于重复报。
        """
        home = Path.home()
        home_roots = [
            home / "Downloads",
            home / "下载",
            home / "Desktop",
            home / "桌面",
            home / "Documents",
            home / "文档",
            home / "AppData" / "Local" / "Temp",
        ]
        for name in ("TEMP", "TMP"):
            value = os.environ.get(name, "").strip()
            if value:
                home_roots.append(Path(value))
        return drives.roots_for_search_scanner(drives.target_drive(), home_roots)

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
                    mark_scan_partial(cancel_flag, self.name)
                    break
                p = Path(dirpath)
                if p == root or is_hard_excluded(p):
                    continue
                # 只比对**相对根目录**的路径段。用绝对路径段会误伤：
                # 跳过表里有 ``appdata``，而 ``%LOCALAPPDATA%\Temp`` 本身就是
                # 合法的扫描根 —— 拿绝对路径比对会把整个根目录跳掉。
                try:
                    rel_parts = p.relative_to(root).parts
                except ValueError:
                    rel_parts = p.parts
                if any(part.lower() in _SKIP for part in rel_parts):
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
                if time.monotonic() - start > _MAX_SECONDS:
                    mark_scan_partial(cancel_flag, self.name)
                break
        if progress:
            progress(self.name, 1.0)
        return items
