"""`space_hogs` 的动态探测测试：页面文件位置 + 卷影副本占用。

两个真实踩过的坑，各自锁一组回归：

1. **页面文件写死 ``C:\\pagefile.sys`` 会漏报。**
   页面文件经常被挪到别的盘，写死之后报告里干脆没有这一项，
   看起来像 bug，实际只是找错了地方（本机页面文件在 D 盘，11 GB）。

2. **权限不足时 ``Measure-Object`` 会返回 0，看起来像「本机没有还原点」。**
   实测 ``(Get-CimInstance Win32_ShadowCopy | Measure-Object).Count``
   在普通权限下返回 ``0``，因为 CIM 的错误是非终止性的、被吞掉了。
   真实情况是 HRESULT 0x80041014 初始化失败 —— 完全没查到。
   所以「测不到」必须是 ``None`` 而不是 ``0``，并且要如实显示成
   「需管理员」，不能伪装成一个测出来的 0。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.models.items import Recommendation, effective_clean_targets
from src.scanners import space_hogs
from src.scanners.space_hogs import SpaceHogsScanner
from src.utils import drives


class _FakeCompleted:
    def __init__(self, returncode: int, stdout: bytes) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = b""


# ----------------------------------------------------- 页面文件位置探测

def test_configured_pagefiles_falls_back_when_registry_unreadable(monkeypatch):
    """读不到注册表时退回目标盘的固定猜测 —— 注意是**目标盘**，不是写死的 C 盘。"""
    def boom(*_args, **_kwargs):
        raise OSError("拒绝访问")

    monkeypatch.setattr(space_hogs.winreg, "OpenKey", boom)
    with drives.use_drive("D:"):
        assert space_hogs._configured_pagefiles() == [Path(r"D:\pagefile.sys")]


def test_configured_pagefiles_parses_explicit_drive_and_ignores_sizes(monkeypatch):
    """``D:\\pagefile.sys 4096 8192`` 的后面两段是初始/最大 MB，不是路径。"""
    monkeypatch.setattr(
        space_hogs.winreg,
        "QueryValueEx",
        lambda *_a, **_k: ([r"D:\pagefile.sys 4096 8192"], 7),
    )
    assert space_hogs._configured_pagefiles() == [Path(r"D:\pagefile.sys")]


def test_configured_pagefiles_probes_every_fixed_drive_when_system_managed(monkeypatch):
    """``?:\\pagefile.sys`` 表示系统托管，注册表不记录它落在哪个盘。

    本机实测就是这个形态，而文件在 D 盘 —— 必须逐盘探测，不能猜 C 盘。
    """
    monkeypatch.setattr(
        space_hogs.winreg, "QueryValueEx", lambda *_a, **_k: ([r"?:\pagefile.sys"], 7)
    )
    monkeypatch.setattr(space_hogs, "fixed_drive_letters", lambda: ["C:", "D:"])
    assert space_hogs._configured_pagefiles() == [
        Path(r"C:\pagefile.sys"),
        Path(r"D:\pagefile.sys"),
    ]


def test_pagefile_item_on_target_drive_reports_real_size():
    with drives.use_drive("C:"):
        item = SpaceHogsScanner()._pagefile_item(Path(r"C:\pagefile.sys"), 8 * 1024 ** 3)
    assert item.size_bytes == 8 * 1024 ** 3
    assert item.deletable is False
    assert item.cross_drive is False
    assert item.recommendation == Recommendation.NOT_RECOMMENDED
    assert "虚拟内存" in item.reason


def test_pagefile_item_off_target_drive_reports_zero_and_says_why():
    """页面文件在别的盘时报 0 字节，但理由里必须带上真实大小。

    报 0 是为了不让「已扫描总量」虚高；写清真实大小是为了不让用户以为漏了。
    """
    with drives.use_drive("C:"):
        item = SpaceHogsScanner()._pagefile_item(Path(r"D:\pagefile.sys"), 11 * 1024 ** 3)
    assert item.size_bytes == 0
    assert "D:" in item.reason
    assert "11.00 GB" in item.reason
    assert "不占用 C: 空间" in item.reason
    assert item.deletable is False


def test_pagefile_item_is_never_cleanable():
    for path in (Path(r"C:\pagefile.sys"), Path(r"D:\pagefile.sys")):
        item = SpaceHogsScanner()._pagefile_item(path, 1024)
        assert effective_clean_targets([item]) == [item]
        assert item.protection_reason


def test_pagefile_item_switches_branch_with_the_target_drive():
    """同一个路径，目标盘不同 → 走的分支不同。这条锁的是「不要写死 C 盘」。"""
    path = Path(r"D:\pagefile.sys")
    with drives.use_drive("D:"):
        on_target = SpaceHogsScanner()._pagefile_item(path, 11 * 1024 ** 3)
    with drives.use_drive("C:"):
        off_target = SpaceHogsScanner()._pagefile_item(path, 11 * 1024 ** 3)
    assert on_target.size_bytes == 11 * 1024 ** 3
    assert on_target.cross_drive is False
    assert off_target.size_bytes == 0
    assert off_target.cross_drive is True


def test_pagefile_items_returns_empty_when_nothing_found(monkeypatch):
    monkeypatch.setattr(space_hogs, "_configured_pagefiles", lambda: [])
    assert SpaceHogsScanner()._pagefile_items() == []


# ----------------------------------------------------- 卷影副本：测不到就说测不到

def test_shadow_size_is_none_not_zero_without_admin(monkeypatch):
    """核心回归：非提权下必须是 None。

    如果这里退化成 0，界面上就会显示「卷影副本 0 B」，
    等于告诉用户「本机没有还原点」—— 那是假结论。
    """
    monkeypatch.setattr(space_hogs, "is_admin", lambda: False)
    size, note = space_hogs._query_shadow_storage_size()
    assert size is None
    assert note
    assert "管理员" in note


def test_shadow_size_does_not_spawn_vssadmin_without_admin(monkeypatch):
    """非提权时连子进程都不该起：注定失败，白等 200ms。"""
    monkeypatch.setattr(space_hogs, "is_admin", lambda: False)

    def boom(*_a, **_k):
        raise AssertionError("非提权下不该调用 vssadmin")

    monkeypatch.setattr(space_hogs.subprocess, "run", boom)
    assert space_hogs._query_shadow_storage_size()[0] is None


def test_shadow_size_parses_chinese_vssadmin_output(monkeypatch):
    """真实输出是**按卷分段**的：先给「卷: (C:) …」，再给该卷的已用空间。

    解析必须跟着卷标记走，否则会把别的盘的数字算到目标盘头上。
    """
    monkeypatch.setattr(space_hogs, "is_admin", lambda: True)
    payload = (
        "卷影副本存储关联\n"
        "   卷: (C:) \\\\?\\Volume{11111111-1111-1111-1111-111111111111}\\\n"
        "   卷影副本存储卷: (C:) \\\\?\\Volume{11111111-1111-1111-1111-111111111111}\\\n"
        "   已用卷影副本存储空间: 3.02 GB (3,245,000,000 字节)\n"
        "   分配的卷影副本存储空间: 4.00 GB (4,294,967,296 字节)\n"
        "   最大卷影副本存储空间: 22.9 GB (24,600,000,000 字节)\n"
    ).encode("gbk")
    monkeypatch.setattr(
        space_hogs.subprocess, "run", lambda *_a, **_k: _FakeCompleted(0, payload)
    )
    with drives.use_drive("C:"):
        size, note = space_hogs._query_shadow_storage_size()
    assert size == 3_245_000_000
    assert note == ""


def test_shadow_size_parses_english_vssadmin_output(monkeypatch):
    monkeypatch.setattr(space_hogs, "is_admin", lambda: True)
    payload = (
        "Shadow Copy Storage association\n"
        "   For volume: (C:) \\\\?\\Volume{11111111-1111-1111-1111-111111111111}\\\n"
        "   Used Shadow Copy Storage space: 1.50 GB (1610612736 bytes)\n"
        "   Allocated Shadow Copy Storage space: 2.00 GB (2147483648 bytes)\n"
    ).encode("gbk")
    monkeypatch.setattr(
        space_hogs.subprocess, "run", lambda *_a, **_k: _FakeCompleted(0, payload)
    )
    with drives.use_drive("C:"):
        assert space_hogs._query_shadow_storage_size()[0] == 1_610_612_736


def test_shadow_size_does_not_leak_across_volumes(monkeypatch):
    """核心回归：查 C 盘不能把 D 盘的数字带出来。

    用户选了 C 盘却看到 D 盘的还原点占用，比不显示更糟 ——
    他会据此判断「C 盘还有这么多能清」，而那个数字根本不属于 C 盘。
    """
    monkeypatch.setattr(space_hogs, "is_admin", lambda: True)
    payload = (
        "卷影副本存储关联\n"
        "   卷: (C:) \\\\?\\Volume{aaaa}\\\n"
        "   已用卷影副本存储空间: 1.00 GB (1,000,000,000 字节)\n"
        "   卷: (D:) \\\\?\\Volume{bbbb}\\\n"
        "   已用卷影副本存储空间: 2.00 GB (2,000,000,000 字节)\n"
    ).encode("gbk")
    monkeypatch.setattr(
        space_hogs.subprocess, "run", lambda *_a, **_k: _FakeCompleted(0, payload)
    )
    with drives.use_drive("C:"):
        assert space_hogs._query_shadow_storage_size()[0] == 1_000_000_000
    with drives.use_drive("D:"):
        assert space_hogs._query_shadow_storage_size()[0] == 2_000_000_000


def test_shadow_size_sums_within_one_volume(monkeypatch):
    """同一个卷可能有多段（多个存储关联），同卷内的要相加。"""
    monkeypatch.setattr(space_hogs, "is_admin", lambda: True)
    payload = (
        "卷影副本存储关联\n"
        "   卷: (C:) \\\\?\\Volume{aaaa}\\\n"
        "   已用卷影副本存储空间: 1.00 GB (1,000,000,000 字节)\n"
        "   卷: (C:) \\\\?\\Volume{aaaa}\\\n"
        "   已用卷影副本存储空间: 2.00 GB (2,000,000,000 字节)\n"
    ).encode("gbk")
    monkeypatch.setattr(
        space_hogs.subprocess, "run", lambda *_a, **_k: _FakeCompleted(0, payload)
    )
    with drives.use_drive("C:"):
        assert space_hogs._query_shadow_storage_size()[0] == 3_000_000_000


def test_shadow_size_is_zero_when_target_drive_has_none(monkeypatch):
    """查询成功但目标盘没有卷影副本 → 0（这是「测到了，确实是 0」）。"""
    monkeypatch.setattr(space_hogs, "is_admin", lambda: True)
    payload = (
        "卷影副本存储关联\n"
        "   卷: (C:) \\\\?\\Volume{aaaa}\\\n"
        "   已用卷影副本存储空间: 1.00 GB (1,000,000,000 字节)\n"
    ).encode("gbk")
    monkeypatch.setattr(
        space_hogs.subprocess, "run", lambda *_a, **_k: _FakeCompleted(0, payload)
    )
    with drives.use_drive("E:"):
        size, note = space_hogs._query_shadow_storage_size()
    assert size == 0
    assert note == ""


def test_shadow_size_is_none_when_volume_cannot_be_identified(monkeypatch):
    """认不出卷归属时返回 None，不做「求和兜底」。

    兜底出来的数字看着合理，但属于哪个盘是错的。
    """
    monkeypatch.setattr(space_hogs, "is_admin", lambda: True)
    payload = "   已用卷影副本存储空间: 1.00 GB (1,000,000,000 字节)\n".encode("gbk")
    monkeypatch.setattr(
        space_hogs.subprocess, "run", lambda *_a, **_k: _FakeCompleted(0, payload)
    )
    size, note = space_hogs._query_shadow_storage_size()
    assert size is None
    assert "卷归属" in note


def test_shadow_size_is_none_when_vssadmin_denies(monkeypatch):
    """真机形态：退出码 2 + 「你没有正确的权限」。"""
    monkeypatch.setattr(space_hogs, "is_admin", lambda: True)
    payload = "错误:  你没有正确的权限，无法运行这个命令。".encode("gbk")
    monkeypatch.setattr(
        space_hogs.subprocess, "run", lambda *_a, **_k: _FakeCompleted(2, payload)
    )
    size, note = space_hogs._query_shadow_storage_size()
    assert size is None
    assert "管理员" in note


def test_shadow_size_is_none_when_vssadmin_missing(monkeypatch):
    monkeypatch.setattr(space_hogs, "is_admin", lambda: True)

    def boom(*_a, **_k):
        raise FileNotFoundError("vssadmin")

    monkeypatch.setattr(space_hogs.subprocess, "run", boom)
    assert space_hogs._query_shadow_storage_size()[0] is None


def test_shadow_size_is_none_when_vssadmin_times_out(monkeypatch):
    monkeypatch.setattr(space_hogs, "is_admin", lambda: True)

    def boom(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="vssadmin", timeout=20)

    monkeypatch.setattr(space_hogs.subprocess, "run", boom)
    assert space_hogs._query_shadow_storage_size()[0] is None


# ----------------------------------------------------- 卷影副本条目本身

def test_shadow_item_appears_even_when_unmeasurable(monkeypatch):
    """测不到也必须出现。

    它消失的话，用户永远不会知道 C 盘上还有「还原点」这么个吃空间的东西 ——
    这正是它长期成为盲区的原因。
    """
    monkeypatch.setattr(space_hogs, "is_admin", lambda: False)
    item = SpaceHogsScanner()._shadow_item()
    assert item.size_bytes == 0
    assert item.deletable is False
    assert item.needs_admin is True
    assert "vssadmin" in item.reason
    assert "系统保护" in item.reason
    assert item.protection_reason


def test_shadow_item_is_report_only_and_not_cleanable(monkeypatch):
    monkeypatch.setattr(space_hogs, "is_admin", lambda: True)
    payload = (
        "   卷: (C:) \\\\?\\Volume{aaaa}\\\n"
        "   已用卷影副本存储空间: 5.00 GB (5,368,709,120 字节)\n"
    ).encode("gbk")
    monkeypatch.setattr(
        space_hogs.subprocess, "run", lambda *_a, **_k: _FakeCompleted(0, payload)
    )
    with drives.use_drive("C:"):
        item = SpaceHogsScanner()._shadow_item()
    assert item.size_bytes == 5_368_709_120
    assert item.deletable is False
    assert effective_clean_targets([item]) == [item]


def test_shadow_item_path_follows_the_target_drive(monkeypatch):
    """路径要指向目标盘上真正拒绝访问的位置，而不是编一个好看的名字。"""
    monkeypatch.setattr(space_hogs, "is_admin", lambda: False)
    with drives.use_drive("C:"):
        assert SpaceHogsScanner()._shadow_item().path == r"C:\System Volume Information"
    with drives.use_drive("D:"):
        assert SpaceHogsScanner()._shadow_item().path == r"D:\System Volume Information"


def test_shadow_item_id_is_unique_per_drive(monkeypatch):
    """id 必须带盘符，否则同一次会话里切盘会撞 id、结果互相覆盖。"""
    monkeypatch.setattr(space_hogs, "is_admin", lambda: False)
    ids = set()
    for drive in ("C:", "D:", "E:"):
        with drives.use_drive(drive):
            ids.add(SpaceHogsScanner()._shadow_item().id)
    assert len(ids) == 3


def test_real_machine_shadow_item_matches_actual_reachability():
    """真机回归：本机非提权，卷影副本必然测不到 —— 条目仍要在，且标注需管理员。"""
    item = SpaceHogsScanner()._shadow_item()
    if space_hogs.is_admin():
        pytest.skip("当前是管理员会话，走的是可测量分支")
    assert item.size_bytes == 0
    assert item.needs_admin is True
    assert "需" in item.reason or "管理员" in item.reason
