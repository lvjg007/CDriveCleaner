"""盘符基础设施测试：枚举、分类、目标盘状态。

这里的每一条都对应一个「写死 C 盘」会踩的坑。用户目录可以被搬到 D 盘，
Windows 也不一定装在 C 盘 —— 所以判定必须基于**盘的属性**，不是盘符字面量。
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from src.utils import drives


# ----------------------------------------------------- 盘符归一化

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("C", "C:"),
        ("c", "C:"),
        ("C:", "C:"),
        ("c:", "C:"),
        ("D:\\", "D:"),
        ("D:/", "D:"),
        ("  e:  ", "E:"),
    ],
)
def test_normalize_letter_accepts_common_forms(raw, expected):
    assert drives.normalize_letter(raw) == expected


@pytest.mark.parametrize("raw", ["", "  ", "CC", "1:", "C:\\Users", "AB:", None])
def test_normalize_letter_rejects_garbage(raw):
    """非法输入返回空串，不抛异常 —— 界面传来的值不该让扫描崩掉。"""
    assert drives.normalize_letter(raw) == ""


# ----------------------------------------------------- 系统盘 / 用户盘

def test_system_drive_matches_systemroot():
    """系统盘取自 ``%SystemRoot%``，不是写死的 C。"""
    import os

    expected = drives.normalize_letter(Path(os.environ["SystemRoot"]).drive)
    assert drives.system_drive() == expected


def test_profile_drive_matches_home():
    """用户盘取自 ``Path.home()``，用户目录被搬到 D 盘时必须跟着变。"""
    assert drives.profile_drive() == drives.normalize_letter(Path.home().drive)


def test_drive_root_shape():
    assert drives.drive_root("C:") == Path("C:\\")
    assert drives.drive_root("d") == Path("D:\\")


def test_system_root_only_where_windows_exists():
    assert drives.system_root(drives.system_drive()) == Path(
        f"{drives.system_drive()}\\Windows"
    )
    assert drives.has_windows(drives.system_drive()) is True


def test_system_root_of_unknown_drive_is_none():
    """不存在的盘不能返回一个看似合法的路径。"""
    assert drives.system_root("") is None
    assert drives.has_windows("") is False


# ----------------------------------------------------- 枚举

def test_list_drives_includes_system_drive():
    letters = [d.letter for d in drives.list_drives()]
    assert drives.system_drive() in letters


def test_list_drives_puts_system_drive_first():
    infos = drives.list_drives()
    assert infos, "至少要枚举到一个盘"
    assert infos[0].is_system is True
    assert sum(1 for d in infos if d.is_system) == 1


def test_list_drives_entries_are_well_formed():
    for info in drives.list_drives():
        assert len(info.letter) == 2 and info.letter.endswith(":")
        assert info.total > 0
        assert 0 <= info.free <= info.total
        assert info.kind in {"系统盘", "用户盘", "数据盘"}
        assert info.letter in info.title
        assert 0.0 <= info.used_pct <= 100.0


def test_drive_info_used_is_derived():
    info = drives.DriveInfo(
        letter="X:", label="", fs="NTFS", total=100, free=30,
        is_system=False, is_profile=False,
    )
    assert info.used == 70
    assert info.used_pct == pytest.approx(70.0)
    assert info.kind == "数据盘"


def test_drive_info_kind_prefers_system_over_profile():
    """系统盘同时也是用户盘时，标签应显示「系统盘」—— 系统盘是更强的属性。"""
    info = drives.DriveInfo(
        letter="C:", label="Windows", fs="NTFS", total=100, free=30,
        is_system=True, is_profile=True,
    )
    assert info.kind == "系统盘"


def test_drive_usage_matches_shutil():
    drive = drives.system_drive()
    usage = drives.drive_usage(drive)
    reference = shutil.disk_usage(f"{drive}\\")
    assert usage.total == reference.total


def test_drive_usage_raises_on_bad_drive():
    with pytest.raises(OSError):
        drives.drive_usage("")


def test_get_drive_info_round_trips():
    for info in drives.list_drives():
        assert drives.get_drive_info(info.letter) == info
    assert drives.get_drive_info("") is None


# ----------------------------------------------------- 目标盘状态

def test_target_drive_defaults_to_system_drive():
    with drives.use_drive(None):
        assert drives.target_drive() == drives.system_drive()


def test_set_target_drive_normalizes():
    with drives.use_drive(None):
        assert drives.set_target_drive("d") == "D:"
        assert drives.target_drive() == "D:"


def test_set_target_drive_ignores_garbage():
    """非法盘符只是被忽略，不会把目标盘弄成空值。"""
    with drives.use_drive("D:"):
        assert drives.set_target_drive("垃圾") == "D:"
        assert drives.set_target_drive("") == "D:"


def test_set_target_drive_none_restores_following_system_drive():
    with drives.use_drive("D:"):
        assert drives.target_drive() == "D:"
        drives.set_target_drive(None)
        assert drives.target_drive() == drives.system_drive()


def test_use_drive_restores_previous_state():
    drives.set_target_drive("D:")
    try:
        with drives.use_drive("E:"):
            assert drives.target_drive() == "E:"
        assert drives.target_drive() == "D:"
    finally:
        drives.set_target_drive(None)


def test_use_drive_restores_on_exception():
    drives.set_target_drive("D:")
    try:
        with pytest.raises(RuntimeError):
            with drives.use_drive("E:"):
                raise RuntimeError("boom")
        assert drives.target_drive() == "D:"
    finally:
        drives.set_target_drive(None)


# ----------------------------------------------------- 搜索型扫描器的根

def test_roots_for_profile_drive_uses_home_subdirs(tmp_path: Path):
    home_roots = [tmp_path / "Downloads", tmp_path / "Desktop"]
    for p in home_roots:
        p.mkdir()
    roots = drives.roots_for_search_scanner(drives.profile_drive(), home_roots)
    assert roots == home_roots


def test_roots_for_other_drive_uses_drive_root():
    """数据盘上没有「下载/桌面」这种约定，只能从盘根走。"""
    other = "D:" if drives.system_drive() != "D:" else "E:"
    roots = drives.roots_for_search_scanner(other, [Path("C:\\nope")])
    assert roots == [drives.drive_root(other)]


def test_roots_for_missing_drive_is_empty():
    assert drives.roots_for_search_scanner("", []) == []


def test_root_skip_names_are_lowercase():
    """跳过表是小写比较的，混进大写会让某个目录悄悄不被跳过。"""
    for name in drives.ROOT_SKIP_DIR_NAMES:
        assert name == name.lower(), name


def test_root_skip_names_cover_the_dangerous_ones():
    for name in ("windows", "system32", "winsxs", "$recycle.bin",
                 "system volume information", "program files", "programdata"):
        assert name in drives.ROOT_SKIP_DIR_NAMES, f"{name} 没被跳过"
