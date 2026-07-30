from __future__ import annotations

from pathlib import Path

from src.models.items import CleanItem, Recommendation
from src.scanners.base import ProgressCb, Scanner
from src.utils.paths import dir_size, is_hard_excluded


class RecycleBinScanner(Scanner):
    name = "回收站"

    def scan(
        self,
        cancel_flag: dict | None = None,
        progress: ProgressCb | None = None,
    ) -> list[CleanItem]:
        if progress:
            progress(self.name, 0.0)
        items: list[CleanItem] = []
        # 常见回收站位置
        roots = [Path(r"C:\$Recycle.Bin")]
        # 也可扫各用户 SID 子目录汇总
        total = 0
        target_path = str(roots[0])
        for root in roots:
            if cancel_flag and cancel_flag.get("cancel"):
                break
            if not root.exists() or is_hard_excluded(root):
                continue
            total += dir_size(root, cancel_flag, max_seconds=6.0)
        if total > 0:
            items.append(
                CleanItem.make(
                    id="recycle:c",
                    category=self.name,
                    path=target_path,
                    size_bytes=total,
                    recommendation=Recommendation.RECOMMEND,
                    reason="回收站内容，清空后不可从回收站恢复",
                    needs_admin=True,
                )
            )
        if progress:
            progress(self.name, 1.0)
        return items
