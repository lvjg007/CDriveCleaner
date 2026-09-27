"""系统盲区的可见性与安全边界测试。

背景：WinSxS、`System32\\winevt\\Logs` 这类目录落在 `_HARD_EXACT` /
`is_hard_excluded` 范围内，任何走 `dir_size` 的扫描器都看不见它们 ——
C 盘上最大的东西反而长期是盲区。

修法是给「只报告」场景单独开一条测量通道（`measure_protected_dir`），
它绕过的是**遍历时的跳过**，与**能不能删**无关。这个边界必须由测试锁死，
否则很容易顺手把硬排除放开。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.models.items import CleanItem, Recommendation, effective_clean_targets
from src.scanners import space_hogs
from src.scanners.space_hogs import SpaceHogsScanner
from src.scanners.system_extras import SystemExtrasScanner
from src.utils import paths
from src.utils.paths import dir_size, dir_size_ex, is_deletion_protected, is_hard_excluded, measure_protected_dir


def _item(path: Path, item_id: str) -> CleanItem:
    return CleanItem.make(
        id=item_id,
        category="测试",
        path=str(path),
        size_bytes=1024,
        recommendation=Recommendation.RECOMMEND,
        reason="测试",
    )


# ----------------------------------------------------- 盲区测量通道

def test_measure_protected_dir_counts_children_dir_size_skips(tmp_path: Path):
    """核心回归：`dir_size` 会把硬排除的子目录整个过滤掉，报告通道必须算进来。"""
    root = tmp_path / "WinSxS"
    sub = root / "System32"  # 名字落在硬排除里
    sub.mkdir(parents=True)
    (sub / "payload.bin").write_bytes(b"\0" * 4096)
    (root / "top.bin").write_bytes(b"\0" * 2048)

    assert dir_size(root, max_seconds=10) == 2048
    size, truncated = measure_protected_dir(root, max_seconds=10)
    assert size == 2048 + 4096
    assert truncated is False


def test_measure_protected_dir_reports_truncation(tmp_path: Path):
    (tmp_path / "payload.bin").write_bytes(b"123")
    size, truncated = measure_protected_dir(tmp_path, max_seconds=-1)
    assert size == 0
    assert truncated is True


class _FakeClock:
    """把 ``time.monotonic`` 换成一串可编排的时间点，让超时判定确定地复现。

    真实时钟测这条会受机器负载影响：同一份代码在空载时能数到文件、
    在满载时可能连目录列举都跑不完。超时逻辑必须用假时钟测。

    ``values`` 按调用次序逐个返回，用完之后一直返回最后一个 —— 这样
    ``_FakeClock(0.0, 2.0)`` 表达的是「起步时是 0，之后一直停在 2 秒」，
    正好用来构造「已经越过软时限、但还没到硬时限」的处境。
    """

    def __init__(self, *values: float) -> None:
        if not values:
            raise ValueError("至少要给一个时间点")
        self._values = list(values)
        self.calls = 0

    def monotonic(self) -> float:
        self.calls += 1
        return self._values[min(self.calls - 1, len(self._values) - 1)]


def _two_file_tree(tmp_path: Path) -> Path:
    """两个子目录各一个文件。

    为什么要两个目录：截断判定发生在**进入下一个目录时**，只有一个目录
    的话遍历会在时限内跑完，永远测不到「截断」这条分支。两个目录才能
    构造出「先数到一个文件，再在下一个目录处超时」的真实次序。
    """
    root = tmp_path / "root"
    for sub in ("a", "b"):
        (root / sub).mkdir(parents=True)
        (root / sub / "payload.bin").write_bytes(b"\0" * 4096)
    return root


def test_truncated_reading_is_never_a_misleading_zero(tmp_path: Path, monkeypatch):
    """被截断的读数必须是「大于 0 的下界」，不能是 0。

    背景（真机踩过）：``C:\\Windows\\WinSxS`` 的根目录有十几万条目，
    光是列举根目录就要 3-5 秒。时限若在「一个文件都没数到」时就触发，
    会返回 0 —— 而调用方把 0 当成「目录是空的」直接丢掉条目，
    于是刚修好的盲区原样回来了。

    假时钟：软时限 1.0 秒，硬时限 3.0 秒，而时钟从第 2 次调用起就停在 2.0 秒。
    于是「越过软时限」与「尚未越过硬时限」同时成立，宽限期被真正行使。
    """
    import src.utils.paths as paths

    root = _two_file_tree(tmp_path)

    clock = _FakeClock(0.0, 2.0)
    monkeypatch.setattr(paths, "time", clock)
    size, truncated = paths.dir_size_ex(root, max_seconds=1.0)

    assert truncated is True, "越过软时限且已数到文件后仍未截断"
    assert size == 4096, "截断读数落到了 0，会看起来像「空目录」"


def test_grace_period_lets_the_walk_reach_the_first_file(tmp_path: Path, monkeypatch):
    """宽限期的正向作用：软时限已过但还没数到文件时，遍历必须继续。

    这是 ``test_truncated_reading_is_never_a_misleading_zero`` 的对照：
    同一份时钟、同样越过软时限，但目录小到能在硬时限内走完，
    此时必须拿到真实大小，而不是「超时了所以是 0」。
    """
    import src.utils.paths as paths

    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "payload.bin").write_bytes(b"\0" * 4096)

    clock = _FakeClock(0.0, 2.0)
    monkeypatch.setattr(paths, "time", clock)
    size, truncated = paths.dir_size_ex(root, max_seconds=1.0)

    # 软时限 1.0 早在第 2 次调用时就已越过，能数到文件全靠宽限期
    assert clock.calls >= 3, "遍历在列举目录阶段就被软时限掐断了"
    assert size == 4096
    assert truncated is False, "遍历走完了，不该报截断"


def test_grace_period_does_not_hide_a_genuinely_empty_dir(tmp_path: Path, monkeypatch):
    """对照组：目录真的空时，宽限期过后仍应如实返回 0 且未截断。

    宽限期不能变成「永远不截断」，否则一个卡死的目录会拖死整轮扫描。
    """
    import src.utils.paths as paths

    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)

    monkeypatch.setattr(paths, "time", _FakeClock(0.0, 2.0))
    size, truncated = paths.dir_size_ex(root, max_seconds=1.0)
    assert size == 0
    assert truncated is False


def test_hard_deadline_still_applies_before_any_file(tmp_path: Path, monkeypatch):
    """宽限期不是无限：超过硬时限照样截断，否则一个卡死的目录会拖死整轮扫描。"""
    import src.utils.paths as paths

    root = _two_file_tree(tmp_path)

    # 时钟一上来就远超硬时限（max_seconds=1.0 → 硬时限 3.0）
    monkeypatch.setattr(paths, "time", _FakeClock(0.0, 99.0))
    size, truncated = paths.dir_size_ex(root, max_seconds=1.0)
    assert size == 0
    assert truncated is True


def test_measure_protected_dir_shares_the_grace_period(tmp_path: Path, monkeypatch):
    """报告通道与常规通道必须用同一套时限语义，否则两个数字没法互相印证。

    ``dir_size`` 给的是「能删多少」，``measure_protected_dir`` 给的是
    「被保护的东西占多少」。两者若在超时语义上分叉，用户会看到
    「WinSxS 显示 0」而「普通目录显示下界」这种自相矛盾的报告。
    """
    import src.utils.paths as paths

    root = _two_file_tree(tmp_path)

    monkeypatch.setattr(paths, "time", _FakeClock(0.0, 2.0))
    walked = paths.dir_size_ex(root, max_seconds=1.0)

    monkeypatch.setattr(paths, "time", _FakeClock(0.0, 2.0))
    measured = measure_protected_dir(root, max_seconds=1.0)

    assert measured == walked == (4096, True)


def test_unmeasurable_dir_item_is_kept_visible(tmp_path: Path, monkeypatch):
    """测不出来的目录必须照样出现在报告里。

    「测出来是 0」和「没测出来」是两件事：前者说明目录是空的，可以丢掉；
    后者说明这个目录在时限内量不出来 —— 丢掉它等于让盲区重新隐身。
    """
    target = tmp_path / "WinSxS"
    target.mkdir()
    monkeypatch.setattr(space_hogs, "measure_protected_dir", lambda *a, **k: (0, True))

    item = SpaceHogsScanner()._dir_item("组件存储 WinSxS", target, "系统目录")
    assert item is not None, "没测出来就被丢掉了，盲区会重新隐身"
    assert item.size_bytes == 0
    assert item.deletable is False
    assert "未能" in item.reason


def test_genuinely_empty_dir_item_is_dropped(tmp_path: Path, monkeypatch):
    """对照组：没被截断的 0 说明目录确实是空的，该丢就丢，别留噪音。"""
    target = tmp_path / "empty"
    target.mkdir()
    monkeypatch.setattr(space_hogs, "measure_protected_dir", lambda *a, **k: (0, False))
    assert SpaceHogsScanner()._dir_item("空目录", target, "理由") is None


def test_measure_protected_dir_still_skips_reparse_points(tmp_path: Path, make_junction):
    """绕过硬排除不等于绕过重解析点 —— 后者会重复计量并指向别的树。"""
    real = tmp_path / "real"
    real.mkdir()
    (real / "payload.bin").write_bytes(b"\0" * 4096)
    link = tmp_path / "link"
    if not make_junction(link, real):
        pytest.skip("当前环境无法创建 junction")

    size, _ = measure_protected_dir(tmp_path, max_seconds=10)
    assert size == 4096


def test_winsxs_is_measurable_but_never_deletable():
    """真机回归：报告看得见 WinSxS，但它必须始终被删除保护拦下。"""
    winsxs = Path(r"C:\Windows\WinSxS")
    if not winsxs.is_dir():
        pytest.skip("本机没有 WinSxS")

    assert is_hard_excluded(winsxs) is True
    assert is_deletion_protected(winsxs) is True
    size, _ = measure_protected_dir(winsxs, max_seconds=2.0)
    assert size > 0, "测量通道没生效，WinSxS 又成了盲区"


# ----------------------------------------------------- 报告项一律不可删

def test_system_report_dirs_are_declared_with_reasons():
    """系统大户的路径是**相对**的，由盘符拼出来。

    写死 ``C:\\Windows\\WinSxS`` 的话，Windows 装在 D 盘时这一项永远不存在。
    """
    labels = [label for label, _rel, _reason in space_hogs._SYSTEM_REPORT_RELATIVE]
    assert "组件存储 WinSxS" in labels
    assert "MSI 安装缓存" in labels
    assert "Windows 事件日志" in labels
    for label, rel, reason in space_hogs._SYSTEM_REPORT_RELATIVE:
        assert reason.strip(), f"{label} 没写理由"
        assert len(reason) > 20, f"{label} 的理由太短，用户看不出代价"
        assert ":" not in rel, f"{label} 的相对路径不该带盘符: {rel}"


def test_system_report_dirs_follow_the_target_drive():
    """同一条相对路径在两个盘上要拼出各自的绝对路径。"""
    c_dirs = {label: path for label, path, _r in space_hogs._system_report_dirs("C:")}
    d_dirs = {label: path for label, path, _r in space_hogs._system_report_dirs("D:")}
    assert c_dirs["组件存储 WinSxS"] == Path(r"C:\Windows\WinSxS")
    assert d_dirs["组件存储 WinSxS"] == Path(r"D:\Windows\WinSxS")
    assert set(c_dirs) == set(d_dirs)


def test_dir_report_item_is_report_only(tmp_path: Path):
    fake = tmp_path / "WinSxS"
    fake.mkdir()
    (fake / "payload.bin").write_bytes(b"\0" * 4096)

    item = SpaceHogsScanner()._dir_item("组件存储 WinSxS", fake, "系统目录")
    assert item is not None
    assert item.deletable is False
    assert item.recommendation == Recommendation.NOT_RECOMMENDED
    assert item.protection_reason
    # 报告项不能进清理队列
    assert effective_clean_targets([item]) == [item]


def test_dir_report_item_is_skipped_when_empty(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert SpaceHogsScanner()._dir_item("空目录", empty, "理由") is None


# ----------------------------------------------------- junction 不能当祖先

def test_effective_targets_do_not_collapse_into_a_junction_parent(tmp_path: Path, make_junction):
    """junction 父项不是真实祖先。

    它最终会被删除保护拦下，若子项已因「父目录已选中」被折叠掉，
    子项就会静默地什么都不做。
    """
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    if not make_junction(link, real):
        pytest.skip("当前环境无法创建 junction")
    (link / "child").mkdir()

    kept = effective_clean_targets([_item(link, "parent"), _item(link / "child", "child")])
    assert "child" in {i.id for i in kept}, "子项被折叠进了 junction 父目录"


def test_effective_targets_still_collapse_normal_parents(tmp_path: Path):
    """对照组：普通父子目录该折叠还是要折叠，别把功能改坏了。"""
    parent = tmp_path / "parent"
    child = parent / "child"
    child.mkdir(parents=True)

    kept = effective_clean_targets([_item(parent, "parent"), _item(child, "child")])
    assert {i.id for i in kept} == {"parent"}


# ----------------------------------------------------- 死条目清理

def test_dead_patch_cache_entry_is_removed():
    """`C:\\Windows\\Installer\\$PatchCache$` 在本机根本不存在，是永远返回 0 的死条目。"""
    labels = [label for label, *_ in SystemExtrasScanner()._targets("C:")]
    assert "Installer 补丁缓存" not in labels
    assert "WinRE 更新残留" in labels


def test_winre_agent_is_optional_not_report_only():
    """WinRE 残留实测近 2 GB，是可回收的；但要写清代价，让用户自己确认。"""
    targets = {label: reco for label, _p, reco, _r, _a in SystemExtrasScanner()._targets("C:")}
    assert targets["WinRE 更新残留"] == Recommendation.OPTIONAL


def test_system_extras_targets_follow_the_target_drive():
    """系统盘条目要跟着盘符走，用户盘条目（%LOCALAPPDATA%）不跟着走。"""
    c_targets = {label: path for label, path, *_ in SystemExtrasScanner()._targets("C:")}
    d_targets = {label: path for label, path, *_ in SystemExtrasScanner()._targets("D:")}
    assert c_targets["WinRE 更新残留"] == Path(r"C:\$WinREAgent")
    assert d_targets["WinRE 更新残留"] == Path(r"D:\$WinREAgent")
    assert c_targets["Windows.old"] == Path(r"C:\Windows.old")
    assert d_targets["Windows.old"] == Path(r"D:\Windows.old")
    # 崩溃转储在用户目录下，与目标盘无关 —— 两个盘拼出来必须是同一个位置，
    # 否则「在 D 盘扫描」会去找 D:\Users\... 这个不存在的路径
    assert c_targets["崩溃转储"] == d_targets["崩溃转储"]
