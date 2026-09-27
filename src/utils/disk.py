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


# GetDriveTypeW 的返回值：3 表示本地固定盘（DRIVE_FIXED）。
# 刻意只取固定盘：可移动盘/网络盘上不会有页面文件，探测它们只会拖慢扫描。
_DRIVE_FIXED = 3


def fixed_drive_letters() -> list[str]:
    """返回本机所有固定盘的盘符，形如 ``["C:", "D:"]``。

    用于「注册表只说 ?:\\pagefile.sys（系统托管），得自己找实际落在哪个盘」
    这类场景 —— 系统托管的页面文件位置注册表并不记录，只能逐盘探测。
    失败时退回 ``["C:"]``，保证调用方永远拿得到可用的盘符列表。
    """
    try:
        kernel32 = ctypes.windll.kernel32
        mask = kernel32.GetLogicalDrives()
        letters: list[str] = []
        for i in range(26):
            if not mask & (1 << i):
                continue
            letter = f"{chr(ord('A') + i)}:"
            try:
                if kernel32.GetDriveTypeW(f"{letter}\\") == _DRIVE_FIXED:
                    letters.append(letter)
            except OSError:
                continue
        return letters or ["C:"]
    except Exception:
        return ["C:"]
