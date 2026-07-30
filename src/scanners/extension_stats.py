from __future__ import annotations

import os
import time
from collections import defaultdict
from pathlib import Path

from src.models.items import CleanItem, Recommendation, format_size
from src.scanners.base import ProgressCb, Scanner
from src.utils.paths import is_hard_excluded

_MAX_SECONDS = 20
_TOP_N = 20


class ExtensionStatsScanner(Scanner):
    """借鉴 WinDirStat 扩展名视图：汇总常见用户目录下各扩展名占用（报告项）。"""

    name = "扩展名占用汇总"

    def _roots(self) -> list[Path]:
        home = Path.home()
        return [
            home / "Downloads",
            home / "下载",
            home / "Desktop",
            home / "桌面",
            home / "Videos",
            home / "视频",
            home / "Documents",
            home / "文档",
            home / "AppData" / "Local" / "Temp",
        ]

    def scan(
        self,
        cancel_flag: dict | None = None,
        progress: ProgressCb | None = None,
    ) -> list[CleanItem]:
        if progress:
            progress(self.name, 0.0)
        totals: dict[str, int] = defaultdict(int)
        counts: dict[str, int] = defaultdict(int)
        largest: dict[str, tuple[int, Path]] = {}
        roots = [r for r in self._roots() if r.exists()]
        start = time.monotonic()

        for ri, root in enumerate(roots):
            if cancel_flag and cancel_flag.get("cancel"):
                break
            if is_hard_excluded(root):
                continue
            if progress:
                progress(f"{self.name}: {root.name}", ri / max(len(roots), 1))
            for dirpath, dirnames, filenames in os.walk(root, topdown=True, onerror=lambda _e: None):
                if cancel_flag and cancel_flag.get("cancel"):
                    break
                if time.monotonic() - start > _MAX_SECONDS:
                    break
                dirnames[:] = [
                    d for d in dirnames
                    if d not in {".git", "node_modules", ".venv", "venv"}
                    and not is_hard_excluded(Path(dirpath) / d)
                ]
                for name in filenames:
                    fp = Path(dirpath) / name
                    try:
                        size = fp.stat().st_size
                    except OSError:
                        continue
                    ext = fp.suffix.lower() or "(无扩展名)"
                    totals[ext] += size
                    counts[ext] += 1
                    prev = largest.get(ext)
                    if prev is None or size > prev[0]:
                        largest[ext] = (size, fp)

        ranked = sorted(totals.items(), key=lambda x: -x[1])[:_TOP_N]
        items: list[CleanItem] = []
        for ext, total in ranked:
            if total <= 0:
                continue
            big = largest.get(ext)
            sample = str(big[1]) if big else ext
            # 常见垃圾扩展：可选；其它仅报告
            junk_ext = ext in {".tmp", ".temp", ".log", ".bak", ".old", ".crdownload", ".partial", ".dmp"}
            reco = Recommendation.OPTIONAL if junk_ext else Recommendation.NOT_RECOMMENDED
            reason = (
                f"扩展名 {ext} 共 {counts[ext]} 个文件，合计 {format_size(total)}"
                + ("；该类型常为残留，可勾选最大样例所在目录相关文件清理" if junk_ext else "；报告项，路径指向该类型最大文件便于定位")
            )
            items.append(
                CleanItem.make(
                    id=f"ext:{ext}",
                    category=self.name,
                    path=sample,
                    size_bytes=total,
                    recommendation=reco,
                    reason=reason,
                    detail=f"扩展名 {ext} · {counts[ext]} 个 · 合计 {format_size(total)}",
                    selected=False,
                )
            )
        if progress:
            progress(self.name, 1.0)
        return items
