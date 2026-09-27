from __future__ import annotations

import hashlib
import os
import time
from collections import defaultdict
from pathlib import Path

from src.models.items import CleanItem, Recommendation
from src.scanners.base import ProgressCb, Scanner, SCOPE_DRIVE
from src.utils import drives
from src.utils.paths import is_hard_excluded, looks_like_project_dir, mark_scan_partial

_MIN_SIZE = 1 * 1024 * 1024  # 1MB 以上才查重
_MAX_SECONDS = 25
#: 整盘查重（数据盘）时的时限。25 秒对 100GB+ 的盘连目录都走不完，
#: 那样只会得到一份几乎没用的「部分结果」；给到 90 秒才有实际意义。
#: 「快速扫描」本来就会跳过本扫描器，所以这个代价不会落在日常路径上。
_MAX_SECONDS_WHOLE_DRIVE = 90
_MAX_GROUPS = 80
_HASH_READ = 1024 * 1024  # 先读 1MB 头；同头再全量


def _quick_hash(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            chunk = f.read(_HASH_READ)
            if not chunk:
                return None
            h.update(chunk)
            # 小文件直接结束；大文件再追加大小与尾部
            size = path.stat().st_size
            h.update(str(size).encode())
            if size > _HASH_READ:
                f.seek(max(0, size - 64 * 1024))
                h.update(f.read(64 * 1024))
        return h.hexdigest()
    except OSError:
        return None


class DuplicateFilesScanner(Scanner):
    """借鉴 BitBroom/Scour：按大小分组 + 内容指纹找重复文件。"""

    name = "重复文件"
    #: 见 base.SCOPE_* 说明
    drive_scope = SCOPE_DRIVE

    def _roots(self) -> list[Path]:
        """用户盘只看下载/桌面/文档等；其它盘从盘根走一遍。"""
        home = Path.home()
        home_roots = [
            home / "Downloads",
            home / "下载",
            home / "Desktop",
            home / "桌面",
            home / "Videos",
            home / "视频",
            home / "Documents",
            home / "文档",
            home / "Pictures",
            home / "图片",
        ]
        return drives.roots_for_search_scanner(drives.target_drive(), home_roots)

    def _budget(self) -> float:
        drive = drives.target_drive()
        if drives.normalize_letter(drive) == drives.profile_drive():
            return _MAX_SECONDS
        return _MAX_SECONDS_WHOLE_DRIVE

    def scan(
        self,
        cancel_flag: dict | None = None,
        progress: ProgressCb | None = None,
    ) -> list[CleanItem]:
        if progress:
            progress(self.name, 0.0)
        by_size: dict[int, list[Path]] = defaultdict(list)
        roots = [r for r in self._roots() if r.exists()]
        max_seconds = self._budget()
        start = time.monotonic()

        for ri, root in enumerate(roots):
            if cancel_flag and cancel_flag.get("cancel"):
                break
            if is_hard_excluded(root):
                continue
            if progress:
                progress(f"{self.name}: 收集 {root.name}", ri / max(len(roots) + 2, 1))
            for dirpath, dirnames, filenames in os.walk(root, topdown=True, onerror=lambda _e: None):
                if cancel_flag and cancel_flag.get("cancel"):
                    break
                if time.monotonic() - start > max_seconds * 0.6:
                    mark_scan_partial(cancel_flag, self.name)
                    break
                dirnames[:] = [
                    d for d in dirnames
                    if d.lower() not in drives.ROOT_SKIP_DIR_NAMES
                    and not is_hard_excluded(Path(dirpath) / d)
                ]
                for name in filenames:
                    fp = Path(dirpath) / name
                    if looks_like_project_dir(fp):
                        continue
                    try:
                        size = fp.stat().st_size
                    except OSError:
                        continue
                    if size < _MIN_SIZE:
                        continue
                    by_size[size].append(fp)

        # 仅处理同尺寸 >=2
        candidates = {s: ps for s, ps in by_size.items() if len(ps) >= 2}
        items: list[CleanItem] = []
        group_i = 0
        total_groups = max(len(candidates), 1)
        for gi, (size, paths) in enumerate(candidates.items()):
            if cancel_flag and cancel_flag.get("cancel"):
                break
            if time.monotonic() - start > max_seconds:
                mark_scan_partial(cancel_flag, self.name)
                break
            if progress and gi % 5 == 0:
                progress(f"{self.name}: 比对 {gi}/{len(candidates)}", 0.6 + 0.4 * gi / total_groups)
            hashes: dict[str, list[Path]] = defaultdict(list)
            for p in paths:
                digest = _quick_hash(p)
                if digest:
                    hashes[digest].append(p)
            for digest, group in hashes.items():
                if len(group) < 2:
                    continue
                # 保留体积列表中第一个，其余标可选删除
                keep = group[0]
                for dup in group[1:]:
                    items.append(
                        CleanItem.make(
                            id=f"dup:{digest[:12]}:{dup}",
                            category=self.name,
                            path=str(dup),
                            size_bytes=size,
                            recommendation=Recommendation.OPTIONAL,
                            reason=f"疑似重复（保留: {keep.name}），确认后可删副本",
                            detail=f"重复文件 · 同组保留「{keep.name}」 · {dup.name}",
                        )
                    )
                group_i += 1
                if group_i >= _MAX_GROUPS:
                    break
            if group_i >= _MAX_GROUPS:
                break

        items.sort(key=lambda x: -x.size_bytes)
        if progress:
            progress(self.name, 1.0)
        return items
