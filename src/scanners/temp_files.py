from __future__ import annotations

import os
from pathlib import Path

from src.models.items import CleanItem, Recommendation
from src.scanners.base import ProgressCb, Scanner
from src.utils.paths import dir_size, existing_paths, is_hard_excluded


class TempFilesScanner(Scanner):
    name = "系统临时文件"

    def scan(
        self,
        cancel_flag: dict | None = None,
        progress: ProgressCb | None = None,
    ) -> list[CleanItem]:
        if progress:
            progress(self.name, 0.0)
        candidates = [
            os.environ.get("TEMP", ""),
            os.environ.get("TMP", ""),
            r"C:\Windows\Temp",
            str(Path.home() / "AppData" / "Local" / "Temp"),
        ]
        # 去重
        seen: set[str] = set()
        items: list[CleanItem] = []
        paths = existing_paths(candidates)
        for i, p in enumerate(paths):
            if cancel_flag and cancel_flag.get("cancel"):
                break
            key = str(p).lower()
            if key in seen or is_hard_excluded(p):
                continue
            seen.add(key)
            size = dir_size(p, cancel_flag, max_seconds=6.0)
            if size <= 0:
                continue
            items.append(
                CleanItem.make(
                    id=f"temp:{key}",
                    category=self.name,
                    path=str(p),
                    size_bytes=size,
                    recommendation=Recommendation.RECOMMEND,
                    reason="临时文件，删除后不影响系统正常运行",
                    needs_admin="windows\\temp" in key,
                )
            )
            if progress:
                progress(self.name, (i + 1) / max(len(paths), 1))
        if progress:
            progress(self.name, 1.0)
        return items
