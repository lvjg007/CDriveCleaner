"""`src.utils.disk` 的小工具测试。"""
from __future__ import annotations

import re

from src.utils import disk


def test_fixed_drive_letters_includes_c_and_is_well_formed():
    """真机回归：C 盘必须在内，且每个盘符都是 ``X:`` 形状。

    `_configured_pagefiles` 靠它探测系统托管的页面文件落在哪个盘，
    返回空列表会让页面文件那一项整个消失。
    """
    letters = disk.fixed_drive_letters()
    assert "C:" in letters
    for letter in letters:
        assert re.fullmatch(r"[A-Z]:", letter), letter


def test_fixed_drive_letters_never_returns_empty(monkeypatch):
    """ctypes 调用炸了也必须给出可用的盘符，否则调用方要额外判空。"""
    monkeypatch.setattr(disk.ctypes, "windll", None)
    assert disk.fixed_drive_letters() == ["C:"]


def test_is_admin_returns_bool():
    assert isinstance(disk.is_admin(), bool)
