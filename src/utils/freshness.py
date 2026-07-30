from __future__ import annotations

import time
from pathlib import Path


def is_fresh(path: str | Path, *, hours: float = 24.0) -> bool:
    """最近修改的文件视为新鲜（用 mtime；Windows 上 ctime 是创建时间不宜单独作删除保护依据）。"""
    p = Path(path)
    try:
        st = p.stat()
    except OSError:
        return False
    return (time.time() - st.st_mtime) < hours * 3600.0
