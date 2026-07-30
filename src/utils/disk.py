from __future__ import annotations

import ctypes
import shutil
from dataclasses import dataclass


@dataclass
class DriveUsage:
    total: int
    used: int
    free: int

    @property
    def used_pct(self) -> float:
        if self.total <= 0:
            return 0.0
        return self.used * 100.0 / self.total


def get_c_drive_usage() -> DriveUsage:
    usage = shutil.disk_usage("C:\\")
    return DriveUsage(total=usage.total, used=usage.used, free=usage.free)


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False
