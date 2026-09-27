from __future__ import annotations

from src.models.items import CleanItem, Recommendation
from src.scanners.base import ProgressCb, Scanner, SCOPE_SYSTEM
from src.utils import drives
from src.utils.paths import dir_size, is_hard_excluded


class WindowsUpdateScanner(Scanner):
    name = "Windows 更新缓存"
    #: 见 base.SCOPE_* 说明。SoftwareDistribution 只存在于 Windows 安装盘，
    #: 数据盘上跑它只会得到一个不存在的路径。
    drive_scope = SCOPE_SYSTEM

    def scan(
        self,
        cancel_flag: dict | None = None,
        progress: ProgressCb | None = None,
    ) -> list[CleanItem]:
        if progress:
            progress(self.name, 0.0)
        drive = drives.target_drive()
        items: list[CleanItem] = []
        root = drives.system_root(drive)
        if root is None:
            if progress:
                progress(self.name, 1.0)
            return items
        target = root / "SoftwareDistribution" / "Download"
        if target.exists() and not is_hard_excluded(target):
            size = dir_size(target, cancel_flag, max_seconds=8.0)
            if size > 0:
                items.append(
                    CleanItem.make(
                        id=f"wu:download:{drive}",
                        category=self.name,
                        path=str(target),
                        size_bytes=size,
                        recommendation=Recommendation.RECOMMEND,
                        reason="更新下载缓存，删除后如需更新会重新下载",
                        detail=f"更新缓存 · {drive}",
                        needs_admin=True,
                    )
                )
        if progress:
            progress(self.name, 1.0)
        return items
