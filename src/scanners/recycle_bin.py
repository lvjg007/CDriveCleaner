from __future__ import annotations

from pathlib import Path

from src.models.items import CleanItem, Recommendation
from src.scanners.base import ProgressCb, Scanner, SCOPE_DRIVE
from src.utils import drives
from src.utils.paths import dir_size, is_hard_excluded


class RecycleBinScanner(Scanner):
    name = "回收站"
    #: 见 base.SCOPE_* 说明
    drive_scope = SCOPE_DRIVE

    def scan(
        self,
        cancel_flag: dict | None = None,
        progress: ProgressCb | None = None,
    ) -> list[CleanItem]:
        """报告目标盘的回收站占用。

        回收站是**每盘一个**：``C:\\$Recycle.Bin`` 与 ``D:\\$Recycle.Bin``
        是两个互不相干的位置，各有各的大小。所以这里只报目标盘那一个，
        不做跨盘汇总 —— 汇总会让用户在 D 盘上看到 C 盘的数字，
        清空之后又对不上（到底清的是哪个盘？）。
        """
        if progress:
            progress(self.name, 0.0)
        drive = drives.target_drive()
        root = Path(f"{drive}\\$Recycle.Bin")
        items: list[CleanItem] = []
        if not root.exists() or is_hard_excluded(root):
            if progress:
                progress(self.name, 1.0)
            return items
        total = dir_size(root, cancel_flag, max_seconds=6.0)
        if total > 0:
            items.append(
                CleanItem.make(
                    id=f"recycle:{drive}",
                    category=self.name,
                    path=str(root),
                    size_bytes=total,
                    recommendation=Recommendation.OPTIONAL,
                    reason=f"清空 {drive} 回收站内容，清空后不可从回收站恢复",
                    detail=f"回收站 · {drive}",
                    needs_admin=True,
                )
            )
        if progress:
            progress(self.name, 1.0)
        return items
