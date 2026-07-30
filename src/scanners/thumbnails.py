from __future__ import annotations

from pathlib import Path

from src.models.items import CleanItem, Recommendation
from src.scanners.base import ProgressCb, Scanner
from src.utils.paths import dir_size, is_hard_excluded


class ThumbnailsScanner(Scanner):
    name = "缩略图缓存"

    def scan(
        self,
        cancel_flag: dict | None = None,
        progress: ProgressCb | None = None,
    ) -> list[CleanItem]:
        if progress:
            progress(self.name, 0.0)
        explorer = Path.home() / "AppData" / "Local" / "Microsoft" / "Windows" / "Explorer"
        items: list[CleanItem] = []
        if not explorer.exists() or is_hard_excluded(explorer):
            if progress:
                progress(self.name, 1.0)
            return items
        total = 0
        paths: list[str] = []
        try:
            for f in explorer.glob("thumbcache_*.db"):
                if cancel_flag and cancel_flag.get("cancel"):
                    break
                try:
                    total += f.stat().st_size
                    paths.append(str(f))
                except OSError:
                    continue
            icon = explorer / "iconcache.db"
            if icon.exists():
                total += icon.stat().st_size
                paths.append(str(icon))
        except OSError:
            pass
        if total > 0 and paths:
            # 以目录为单位清理更稳
            items.append(
                CleanItem.make(
                    id="thumb:explorer",
                    category=self.name,
                    path=str(explorer),
                    size_bytes=total,
                    recommendation=Recommendation.RECOMMEND,
                    reason="缩略图缓存，删除后资源管理器会重建",
                    needs_admin=False,
                )
            )
        if progress:
            progress(self.name, 1.0)
        return items
