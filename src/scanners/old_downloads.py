from __future__ import annotations

import time
from pathlib import Path

from src.models.items import CleanItem, Recommendation
from src.scanners.base import ProgressCb, Scanner, SCOPE_PROFILE
from src.utils.paths import is_hard_excluded, looks_like_project_dir, safe_iter_files

_DAYS = 90
_MIN_SIZE = 10 * 1024 * 1024  # 10MB，避免海量小文件


class OldDownloadsScanner(Scanner):
    name = "下载目录长期未访问"
    #: 见 base.SCOPE_* 说明
    drive_scope = SCOPE_PROFILE

    def _roots(self) -> list[Path]:
        home = Path.home()
        return [home / "Downloads", home / "下载"]

    def scan(
        self,
        cancel_flag: dict | None = None,
        progress: ProgressCb | None = None,
    ) -> list[CleanItem]:
        if progress:
            progress(self.name, 0.0)
        items: list[CleanItem] = []
        cutoff = time.time() - _DAYS * 24 * 3600
        roots = [r for r in self._roots() if r.exists()]
        for i, root in enumerate(roots):
            if cancel_flag and cancel_flag.get("cancel"):
                break
            if is_hard_excluded(root):
                continue
            for f in safe_iter_files(root, cancel_flag=cancel_flag):
                if cancel_flag and cancel_flag.get("cancel"):
                    break
                if looks_like_project_dir(f):
                    continue
                try:
                    st = f.stat()
                except OSError:
                    continue
                if st.st_size < _MIN_SIZE:
                    continue
                atime = getattr(st, "st_atime", st.st_mtime)
                mtime = st.st_mtime
                last = max(atime, mtime)
                if last > cutoff:
                    continue
                items.append(
                    CleanItem.make(
                        id=f"olddl:{f}",
                        category=self.name,
                        path=str(f),
                        size_bytes=st.st_size,
                        recommendation=Recommendation.NOT_RECOMMENDED,
                        reason=f"下载目录内超过 {_DAYS} 天未访问/未修改，请确认后勾选",
                    )
                )
            if progress:
                progress(self.name, (i + 1) / max(len(roots), 1))
        items.sort(key=lambda x: x.size_bytes, reverse=True)
        items = items[:200]
        if progress:
            progress(self.name, 1.0)
        return items
