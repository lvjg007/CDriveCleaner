from __future__ import annotations

import os
from pathlib import Path


def send_to_recycle_bin(path: str | Path) -> None:
    """将文件/目录移入回收站（Windows Shell）。失败则抛异常。"""
    p = str(Path(path).resolve())
    if os.name != "nt":
        raise OSError("回收站删除仅支持 Windows")

    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", wintypes.WORD),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", wintypes.LPVOID),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    FO_DELETE = 3
    FOF_ALLOWUNDO = 0x40
    FOF_NOCONFIRMATION = 0x10
    FOF_NOERRORUI = 0x400
    FOF_SILENT = 0x0004

    # 双 NUL 结尾
    from_buf = p + "\0\0"
    op = SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_DELETE
    op.pFrom = from_buf
    op.pTo = None
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT
    op.fAnyOperationsAborted = False
    op.hNameMappings = None
    op.lpszProgressTitle = None

    ret = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if ret != 0:
        raise OSError(f"移入回收站失败 code={ret} path={p}")
    if op.fAnyOperationsAborted:
        raise OSError(f"移入回收站被中止 path={p}")


def empty_recycle_bin(root: str | Path | None = None) -> None:
    """Empty recycle-bin contents through the Windows Shell.

    ``root`` 是盘根（``"D:\\\\"``）。传 ``None`` 表示清空**所有**盘 ——
    这正是原来的行为，但在多盘模式下是个陷阱：报告里 D 盘那一项写着
    「清空 D: 回收站」，实际把 C:/D:/E: 全清了，用户没法预期。
    所以调用方必须显式传目标盘，``None`` 只作为兜底保留。

    **只有返回 0 才算成功。** 刻意不对「该盘没有回收站」做特判放行：
    那样会让真正的失败（权限不足、文件被占用）被静默报成成功，
    用户以为清干净了其实没有。失败码到底长什么样没有实测过 ——
    要测就得真的清空一次用户的回收站，那是不可逆的，不能拿来做实验。
    宁可让「本来就没东西可清」偶尔报一次失败，也不能让真失败被吞掉。
    """
    if os.name != "nt":
        raise OSError("清空回收站仅支持 Windows")
    import ctypes

    SHERB_NOCONFIRMATION = 0x00000001
    SHERB_NOPROGRESSUI = 0x00000002
    SHERB_NOSOUND = 0x00000004
    drive_root = str(root) if root else None
    ret = ctypes.windll.shell32.SHEmptyRecycleBinW(
        None,
        drive_root,
        SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND,
    )
    if ret != 0:
        raise OSError(f"清空回收站失败 code={ret} drive={drive_root}")
