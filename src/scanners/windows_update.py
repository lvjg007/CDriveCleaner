from __future__ import annotations

from pathlib import Path

from src.models.items import CleanItem, Recommendation
from src.scanners.base import ProgressCb, Scanner
from src.utils.paths import dir_size, is_hard_excluded


class WindowsUpdateScanner(Scanner):
    name = "Windows 更新缓存"

    def scan(
        self,
        cancel_flag: dict | None = None,
        progress: ProgressCb | None = None,
    ) -> list[CleanItem]:
        if progress:
            progress(self.name, 0.0)
        target = Path(r"C:\Windows\SoftwareDistribution\Download")
        items: list[CleanItem] = []
        if target.exists() and not is_hard_excluded(target):
            size = dir_size(target, cancel_flag, max_seconds=8.0)
            if size > 0:
                items.append(
                    CleanItem.make(
                        id="wu:download",
                        category=self.name,
                        path=str(target),
                        size_bytes=size,
                        recommendation=Recommendation.RECOMMEND,
                        reason="更新下载缓存，删除后如需更新会重新下载",
                        needs_admin=True,
                    )
                )
        if progress:
            progress(self.name, 1.0)
        return items
