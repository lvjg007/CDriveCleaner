from __future__ import annotations

import os
import time
from pathlib import Path

from src.models.items import CleanItem, Recommendation
from src.scanners.base import ProgressCb, Scanner, SCOPE_DRIVE
from src.utils import drives
from src.utils.paths import is_hard_excluded, is_user_protected_library, looks_like_project_dir, mark_scan_partial

DEFAULT_THRESHOLD = 100 * 1024 * 1024
MAX_SECONDS = 25  # 覆盖下载/桌面/文档等，超时也返回已发现项
MAX_ITEMS = 300

#: 盘根遍历时用共享跳过表（含 Windows / ProgramData / 工程目录等）。
#: 大小写不敏感比较，见 ``drives.ROOT_SKIP_DIR_NAMES``。
_SKIP_DIR_NAMES = drives.ROOT_SKIP_DIR_NAMES


class LargeFilesScanner(Scanner):
    name = "大文件扫描"
    #: 见 base.SCOPE_* 说明
    drive_scope = SCOPE_DRIVE

    def __init__(self, threshold: int = DEFAULT_THRESHOLD) -> None:
        self.threshold = threshold

    def _roots(self) -> list[Path]:
        """按目标盘挑根目录。

        用户盘：只看下载/桌面/文档这些用户真正在意的地方，不整盘遍历。
        其它盘：数据盘没有「垃圾目录」约定，只能带跳过表从盘根走一遍。
        """
        home = Path.home()
        # 公共下载目录跟着用户目录所在的盘走，不能写死 C:。
        # 写死的话，用户目录被搬到 D 盘时这里会指向 C 盘 ——
        # ``roots_for_search_scanner`` 会把它过滤掉（跨盘候选一律丢），
        # 于是公共下载目录就被静默漏掉了。按 home 推导才是对的。
        public_downloads = home.parent / "Public" / "Downloads"
        home_roots = [
            home / "Downloads",
            home / "下载",
            home / "Desktop",
            home / "桌面",
            home / "Videos",
            home / "视频",
            home / "Documents",
            home / "文档",
            public_downloads,
        ]
        candidates = drives.roots_for_search_scanner(drives.target_drive(), home_roots)
        roots: list[Path] = []
        for p in candidates:
            if not p.exists() or not p.is_dir() or is_hard_excluded(p):
                continue
            roots.append(p)
        # 去重交给 roots_for_search_scanner（它按规范化路径去重），
        # 这里不再维护第二套 seen 集合 —— 两套去重规则迟早会分叉。
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
                mark_scan_partial(cancel_flag, self.name)
                if progress:
                    progress(f"{self.name}（时限到，已返回部分结果）", 1.0)
                break
            if progress:
                progress(f"{self.name}: {base.name}", i / max(len(roots), 1))

            for dirpath, dirnames, filenames in os.walk(base, topdown=True, onerror=lambda _e: None):
                if cancel_flag and cancel_flag.get("cancel"):
                    break
                if time.monotonic() - start > MAX_SECONDS:
                    mark_scan_partial(cancel_flag, self.name)
                    break
                visited += 1
                keep = []
                for d in dirnames:
                    # 跳过表是小写，Windows 目录名大小写不固定，必须统一小写比较
                    if d.lower() in _SKIP_DIR_NAMES:
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
