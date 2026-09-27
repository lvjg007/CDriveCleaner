from __future__ import annotations

import os
from pathlib import Path

from src.models.items import CleanItem, Recommendation
from src.scanners.base import ProgressCb, Scanner, SCOPE_DRIVE
from src.utils import drives
from src.utils.paths import canonical_path_key, dir_size, existing_paths


class TempFilesScanner(Scanner):
    name = "系统临时文件"
    #: 见 base.SCOPE_* 说明
    drive_scope = SCOPE_DRIVE

    def _candidates(self, drive: str) -> list[str]:
        """按目标盘收集候选临时目录。

        临时目录分三类，各自归属不同的盘：
          * ``<系统盘>\\Windows\\Temp`` —— 只在装了 Windows 的那个盘上存在；
          * ``%TEMP%`` / ``%LOCALAPPDATA%\\Temp`` —— 跟着用户目录走，
            用户目录被搬到 D 盘时它们就在 D 盘；
          * ``<盘>\\Temp``、``<盘>\\temp`` —— 盘根上的临时目录，
            任何盘都可能有（手动解压、下载、脚本留下的常见落点）。

        **顺序有意义**：``existing_paths`` 去重时保留第一次出现的写法，
        所以家目录推导出来的长名放在 ``%TEMP%`` 前面 —— 真机上
        ``%TEMP%`` 常是 8.3 短名（``C:\\Users\\LVJING~1\\...``），
        去重后留下短名会让用户看不懂这个路径。
        """
        candidates: list[str] = []
        if drives.has_windows(drive):
            root = drives.system_root(drive)
            if root is not None:
                candidates.append(str(root / "Temp"))
        if drives.normalize_letter(drive) == drives.profile_drive():
            candidates.append(str(Path.home() / "AppData" / "Local" / "Temp"))
            candidates.append(os.environ.get("TEMP", ""))
            candidates.append(os.environ.get("TMP", ""))
        else:
            # TEMP 被重定向到别的盘时（``E:\\MyTemp`` 之类），那个盘也该扫到。
            # 按盘过滤而不是无条件加进来，避免扫 D 盘时把 C 盘的临时目录算进去。
            for var in ("TEMP", "TMP"):
                value = os.environ.get(var, "").strip()
                if value and drives.on_drive(value, drive):
                    candidates.append(value)
        candidates.append(f"{drive}\\Temp")
        candidates.append(f"{drive}\\temp")
        return candidates

    def scan(
        self,
        cancel_flag: dict | None = None,
        progress: ProgressCb | None = None,
    ) -> list[CleanItem]:
        if progress:
            progress(self.name, 0.0)
        drive = drives.target_drive()
        items: list[CleanItem] = []
        # existing_paths 已经按文件系统标识去重，这里不再维护第二套 seen 集合
        paths = existing_paths(self._candidates(drive))
        for i, p in enumerate(paths):
            if cancel_flag and cancel_flag.get("cancel"):
                break
            key = canonical_path_key(p)
            size = dir_size(p, cancel_flag, max_seconds=6.0)
            if size <= 0:
                continue
            needs_admin = "windows\\temp" in key
            items.append(
                CleanItem.make(
                    id=f"temp:{key}",
                    category=self.name,
                    path=str(p),
                    size_bytes=size,
                    recommendation=Recommendation.RECOMMEND,
                    reason=(
                        "系统临时文件，删除后不影响系统正常运行"
                        + ("（该目录需管理员权限）" if needs_admin else "")
                    ),
                    detail=f"临时文件 · {drive}",
                    needs_admin=needs_admin,
                )
            )
            if progress:
                progress(self.name, (i + 1) / max(len(paths), 1))
        if progress:
            progress(self.name, 1.0)
        return items
