"""测试共用夹具。

这里自己造 junction，而不是调 ``cmd /c mklink /J``：
受限/沙箱环境里 cmd.exe 可能不可用，而 junction 的语义正是本仓库
最需要验证的边界（``is_symlink()`` 对它恒为 False）。
"""
from __future__ import annotations

import ctypes
import os
import struct
from ctypes import wintypes
from pathlib import Path

import pytest


def _create_junction(link: Path, target: Path) -> bool:
    """用 FSCTL_SET_REPARSE_POINT 造一个真 junction。

    NTFS 上创建 junction 不需要管理员权限，也不需要 cmd.exe。
    成功返回 True，环境不支持时返回 False（调用方据此 skip）。
    """
    if os.name != "nt":
        return False

    GENERIC_WRITE = 0x40000000
    FILE_SHARE_ALL = 0x00000001 | 0x00000002 | 0x00000004
    OPEN_EXISTING = 3
    FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
    FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    FSCTL_SET_REPARSE_POINT = 0x000900A4
    IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    try:
        link.mkdir(exist_ok=True)
    except OSError:
        return False

    target_abs = os.path.abspath(str(target))
    substitute = ("\\??\\" + target_abs).encode("utf-16-le")
    printable = target_abs.encode("utf-16-le")

    # 布局按系统实际写出的来（用 FSCTL_GET_REPARSE_POINT 读家目录的
    # "Application Data" 反推）：两个名字各自以 2 字节 NUL 结尾，
    # 且 PrintNameOffset = SubstituteNameLength + 2，不是 + 0。
    # 写成后者会稳定拿到 ERROR_INVALID_REPARSE_DATA (4392)。
    path_buffer = substitute + b"\x00\x00" + printable + b"\x00\x00"
    # REPARSE_DATA_BUFFER 通用头 8 字节 + MountPointReparseBuffer 头 8 字节 + 路径
    buffer = struct.pack(
        "<IHHHHHH",
        IO_REPARSE_TAG_MOUNT_POINT,
        8 + len(path_buffer),
        0,
        0,
        len(substitute),
        len(substitute) + 2,
        len(printable),
    ) + path_buffer

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except (OSError, AttributeError):
        return False

    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    handle = kernel32.CreateFileW(
        str(link),
        GENERIC_WRITE,
        FILE_SHARE_ALL,
        None,
        OPEN_EXISTING,
        FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS,
        None,
    )
    if not handle or handle == INVALID_HANDLE_VALUE:
        return False

    try:
        kernel32.DeviceIoControl.restype = wintypes.BOOL
        kernel32.DeviceIoControl.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
            wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        ]
        returned = wintypes.DWORD(0)
        ok = kernel32.DeviceIoControl(
            handle,
            FSCTL_SET_REPARSE_POINT,
            buffer,
            len(buffer),
            None,
            0,
            ctypes.byref(returned),
            None,
        )
        return bool(ok)
    finally:
        kernel32.CloseHandle(handle)


@pytest.fixture
def make_junction():
    """返回一个 (link, target) -> bool 的构造器；环境不支持时由用例自行 skip。"""
    return _create_junction
