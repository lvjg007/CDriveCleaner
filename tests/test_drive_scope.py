"""多盘扫描的「范围判定」回归。

工具从「只扫 C 盘」扩到「选盘扫」之后，最容易出的错不是崩溃，而是
**静默产出错误结果**：在 D 盘上重跑一个读 ``Path.home()`` 的扫描器，
它会把 C 盘的家目录垃圾原样再报一遍 —— 用户以为 D 盘有 20 GB 可清，
实际那些文件在 C 盘。这类错误没有异常、没有日志，只有一份看起来
完全合理的报告，比崩溃危险得多。

所以这里测的不是「代码能跑」，而是三件事：

1. 每个扫描器声明的盘范围是否合法、是否与它的实现相符；
2. 扫描器在「不适用的盘」上是否被正确跳过、且给了理由；
3. 任何扫描器挑出来的根目录是否都落在目标盘上（跨盘泄漏的底线）。

第 3 条是兜底：即使某个扫描器的 ``drive_scope`` 写错了，
根目录也不该跨到别的盘上去。
"""
from pathlib import Path

import pytest

from src.app.orchestrator import Orchestrator
from src.models.items import CleanItem, Recommendation
from src.scanners.base import SCOPE_DRIVE, SCOPE_PROFILE, SCOPE_SYSTEM, Scanner
from src.scanners.duplicates import DuplicateFilesScanner
from src.scanners.empty_folders import EmptyFolderScanner
from src.scanners.installer_residue import InstallerResidueScanner
from src.scanners.large_files import LargeFilesScanner
from src.scanners.recycle_bin import RecycleBinScanner
from src.scanners.registry import all_scanners
from src.scanners.system_extras import SystemExtrasScanner
from src.scanners.temp_files import TempFilesScanner
from src.utils import drives

_VALID_SCOPES = {SCOPE_DRIVE, SCOPE_SYSTEM, SCOPE_PROFILE}


def _real_drives() -> list[str]:
    return [d.letter for d in drives.list_drives()]


def _other_drive() -> str | None:
    """一个「不是用户目录所在盘」的真实盘，没有就返回 None。"""
    for letter in _real_drives():
        if drives.normalize_letter(letter) != drives.profile_drive():
            return drives.normalize_letter(letter)
    return None


# ------------------------------------------------------------ 声明是否合法

def test_every_scanner_declares_a_known_scope():
    """没声明或声明错，都会被当成「任意盘」处理 —— 静默产出假重复。

    默认值是 ``SCOPE_DRIVE``，也就是「不声明 = 任何盘都扫」。
    所以新增读 ``Path.home()`` 的扫描器时忘了声明，不会报错，
    只会在 D 盘上把 C 盘的结果再报一遍。
    """
    for scanner in all_scanners():
        assert scanner.drive_scope in _VALID_SCOPES, (
            f"{scanner.name} 的 drive_scope={scanner.drive_scope!r} 不是合法取值"
        )


def test_scope_label_is_human_readable():
    for scanner in all_scanners():
        label = scanner.scope_label
        assert label, scanner.name
        assert label != scanner.drive_scope, f"{scanner.name} 没有中文标签"


def test_every_scope_is_actually_used():
    """三个范围都得有扫描器在用，否则对应分支是死代码。

    尤其是 ``SCOPE_SYSTEM``：一旦没人用，``applies_to`` 里那条
    「数据盘上没有 Windows」的判定就没人验证，烂掉也不会被发现。
    """
    used = {s.drive_scope for s in all_scanners()}
    assert used == _VALID_SCOPES, f"未使用的范围: {_VALID_SCOPES - used}"


def test_scanner_count_matches_the_registry():
    """范围判定是按「每个扫描器」跑的，数量对不上说明有扫描器漏标了。"""
    assert len(all_scanners()) == 22


# ---------------------------------------------------- applies_to 的真实语义

def test_drive_scope_scanners_apply_to_every_real_drive():
    for scanner in all_scanners():
        if scanner.drive_scope != SCOPE_DRIVE:
            continue
        for letter in _real_drives():
            assert scanner.applies_to(letter), f"{scanner.name} 应适用于 {letter}"


def test_system_scope_scanners_follow_has_windows():
    """「只在装了 Windows 的盘上有意义」——判定标准就是有没有 ``\\Windows``。

    不写死盘符：系统盘不一定是 C，用户也可能把 Windows 装在 D。
    """
    for scanner in all_scanners():
        if scanner.drive_scope != SCOPE_SYSTEM:
            continue
        for letter in _real_drives():
            assert scanner.applies_to(letter) == drives.has_windows(letter), (
                f"{scanner.name} 在 {letter} 上的判定与 has_windows 不一致"
            )


def test_profile_scope_scanners_follow_the_profile_drive():
    for scanner in all_scanners():
        if scanner.drive_scope != SCOPE_PROFILE:
            continue
        for letter in _real_drives():
            expected = drives.normalize_letter(letter) == drives.profile_drive()
            assert scanner.applies_to(letter) == expected, (
                f"{scanner.name} 在 {letter} 上的判定与 profile_drive 不一致"
            )


def test_profile_scanners_are_skipped_off_the_profile_drive():
    """假重复的直接回归：非用户盘上，所有读 ``Path.home()`` 的扫描器都必须跳过。

    这是本文件存在的主要理由。真机上 D 盘扫描从 321 项降到 84 项，
    少掉的正是这些扫描器重复报出来的 C 盘内容。
    """
    other = _other_drive()
    if other is None:
        pytest.skip("本机只有一个固定盘，无法构造「非用户盘」")

    profile_scanners = [s for s in all_scanners() if s.drive_scope == SCOPE_PROFILE]
    assert profile_scanners, "没有任何 SCOPE_PROFILE 扫描器，这条测试失去意义"

    for scanner in profile_scanners:
        assert not scanner.applies_to(other), (
            f"{scanner.name} 在非用户盘 {other} 上仍被判为适用 —— "
            "它会把用户盘的目录再报一遍"
        )


def test_skip_reason_is_present_exactly_when_skipped():
    """理由必须成对出现：跳过了却不给理由，用户会以为是漏扫。"""
    for scanner in all_scanners():
        for letter in _real_drives() + ["Z:"]:
            applies = scanner.applies_to(letter)
            reason = scanner.skip_reason(letter)
            if applies:
                assert reason == "", f"{scanner.name} 在 {letter} 上适用却给了理由"
            else:
                assert reason, f"{scanner.name} 在 {letter} 上被跳过却没给理由"


def test_unknown_drive_is_never_treated_as_the_system_drive():
    """空盘符 / 不存在的盘不能被当成 C 盘。

    「界面显示 D，实际扫 C」对删除工具是最坏的失效方式，所以
    非法输入一律判为「不适用」，而不是退回默认盘。
    """
    for scanner in all_scanners():
        if scanner.drive_scope == SCOPE_DRIVE:
            continue
        assert not scanner.applies_to(""), f"{scanner.name} 把空盘符当成了可用盘"
        assert not scanner.applies_to("Z:"), f"{scanner.name} 把不存在的盘当成了可用盘"


# ------------------------------------------------------- 与编排层保持一致

def test_orchestrator_and_scanner_agree_on_applicability():
    """``scanners_for`` 必须与 ``applies_to`` 完全一致。

    两处各写一套判定的话，界面上显示「已跳过」的扫描器可能仍在跑，
    或者反过来 —— 用户看到的与实际执行的分叉。
    """
    orch = Orchestrator()
    for letter in _real_drives() + ["Z:"]:
        runnable, skipped = orch.scanners_for(letter)
        expected_runnable = [s for s in all_scanners() if s.applies_to(letter)]
        expected_skipped = [s for s in all_scanners() if not s.applies_to(letter)]

        assert [s.name for s in runnable] == [s.name for s in expected_runnable]
        assert [name for name, _ in skipped] == [s.name for s in expected_skipped]

        # 两部分必须恰好覆盖全部扫描器，不能重复也不能遗漏
        assert len(runnable) + len(skipped) == len(all_scanners())
        assert {s.name for s in runnable} & {name for name, _ in skipped} == set()

        # 跳过的理由要能直接显示给用户
        for name, reason in skipped:
            assert reason, f"{name} 在 {letter} 上被跳过却没给理由"


# ------------------------------------------- 根目录不得跨盘（兜底不变量）

_ROOTS_SCANNERS = [
    LargeFilesScanner,
    DuplicateFilesScanner,
    EmptyFolderScanner,
    InstallerResidueScanner,
]


@pytest.mark.parametrize("scanner_cls", _ROOTS_SCANNERS)
def test_search_scanner_roots_never_leave_the_target_drive(scanner_cls):
    """遍历型扫描器挑出来的根必须全在目标盘上。

    真机踩过：``large_files`` 的候选里写死了 ``C:\\Users\\Public\\Downloads``。
    用户目录一旦被搬到 D 盘，选 D 盘扫描时它会照样去遍历 C 盘那个目录。
    多扫一个目录只是慢，把 C 盘的文件报成 D 盘的垃圾才是真问题。

    现在这条不变量由 ``roots_for_search_scanner`` 统一兜住，
    这里逐个扫描器验证它确实生效了。
    """
    scanner = scanner_cls()
    for letter in _real_drives():
        with drives.use_drive(letter):
            roots = scanner._roots()
        for root in roots:
            assert drives.on_drive(root, letter), (
                f"{scanner.name} 在扫 {letter} 时挑出了跨盘的根: {root}"
            )


@pytest.mark.parametrize("scanner_cls", _ROOTS_SCANNERS)
def test_search_scanner_roots_are_not_empty_on_a_real_drive(scanner_cls):
    """真实盘上不该一个根都挑不出来 —— 那等于静默不扫。"""
    scanner = scanner_cls()
    for letter in _real_drives():
        with drives.use_drive(letter):
            roots = scanner._roots()
        assert roots, f"{scanner.name} 在 {letter} 上一个根都没挑出来"


@pytest.mark.parametrize("scanner_cls", _ROOTS_SCANNERS)
def test_search_scanner_roots_are_deduplicated(scanner_cls):
    """根目录不能重复。

    用 ``canonical_path_key`` 判重而不是字符串比较：真机上 ``%TEMP%`` 就是
    8.3 短名形式（``C:\\Users\\LVJING~1\\...``），与
    ``<家目录>\\AppData\\Local\\Temp`` 指的是同一个目录，但字符串不同。
    字符串比较会漏掉这种重复，同一批文件被两个根各扫一遍、各报一次。
    """
    from src.utils.paths import canonical_path_key

    scanner = scanner_cls()
    for letter in _real_drives():
        with drives.use_drive(letter):
            roots = scanner._roots()
        keys = [canonical_path_key(r) for r in roots]
        assert len(keys) == len(set(keys)), (
            f"{scanner.name} 在 {letter} 上挑出了重复的根: "
            f"{[str(r) for r in roots]}"
        )


def test_dedupe_paths_uses_filesystem_identity(tmp_path: Path):
    """``dedupe_paths`` 要按文件系统标识去重，并保留第一次出现的写法。"""
    import ctypes
    from ctypes import wintypes

    from src.utils.paths import canonical_path_key

    get_short = ctypes.windll.kernel32.GetShortPathNameW
    get_short.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    get_short.restype = wintypes.DWORD
    buffer = ctypes.create_unicode_buffer(32768)
    length = get_short(str(tmp_path), buffer, 32768)
    short = buffer.value if length and length < 32768 else str(tmp_path)

    if canonical_path_key(short) == canonical_path_key(tmp_path) and short != str(tmp_path):
        out = drives.dedupe_paths([tmp_path, Path(short)])
        assert out == [tmp_path], "别名没有合并，或没有保留第一次出现的写法"

    # 大小写不同的同一路径也必须合并
    out = drives.dedupe_paths([tmp_path, Path(str(tmp_path).upper())])
    assert len(out) == 1


def test_temp_file_candidates_have_no_duplicates():
    """候选里不能出现指向同一个目录的两个写法。

    真机上 ``%TEMP%`` 与 ``<家目录>\\AppData\\Local\\Temp`` 就是同一个
    目录的短名/长名两种写法，候选里同时留着它们等于让扫描器重复计量。
    """
    from src.utils.paths import canonical_path_key, existing_paths

    scanner = TempFilesScanner()
    for letter in _real_drives():
        with drives.use_drive(letter):
            candidates = scanner._candidates(letter)
        keys = [canonical_path_key(c) for c in existing_paths(candidates)]
        assert len(keys) == len(set(keys)), (
            f"扫 {letter} 时的临时目录候选有重复: {candidates}"
        )


def test_temp_file_candidates_prefer_the_readable_long_path():
    """去重后留下的应当是长名。

    ``%TEMP%`` 常是 8.3 短名（``C:\\Users\\LVJING~1\\...``），
    把它显示给用户等于让人去猜这是哪个目录。
    """
    scanner = TempFilesScanner()
    profile = drives.profile_drive()
    with drives.use_drive(profile):
        candidates = scanner._candidates(profile)
    expected = str(Path.home() / "AppData" / "Local" / "Temp")
    if expected not in candidates:
        pytest.skip("本机没有家目录下的 Temp 目录")
    assert candidates.index(expected) < len(candidates), "长名不在候选里"
    # 长名必须排在任何可能撞车的短名写法之前
    short_forms = [c for c in candidates if "~" in c]
    for short in short_forms:
        assert candidates.index(expected) < candidates.index(short), (
            "短名排在长名前面，去重后会留下用户看不懂的那个"
        )


def test_roots_for_unknown_drive_is_empty_not_c_drive():
    """非法盘符必须返回空，不能退回 C 盘。"""
    assert drives.roots_for_search_scanner("", [Path("C:\\Windows")]) == []
    assert drives.roots_for_search_scanner("Z:", []) == []


def test_roots_filter_out_candidates_on_another_drive():
    """核心不变量：候选里混进别的盘的路径时必须被丢掉。"""
    profile = drives.profile_drive()
    foreign = "Z:"
    assert drives.normalize_letter(foreign) != profile

    roots = drives.roots_for_search_scanner(profile, [Path(foreign + "\\Users\\Public\\Downloads")])
    assert roots == [], "别的盘的候选没有被过滤掉"


# ---------------------------------------------- 各扫描器自报的路径也在盘内

def test_temp_file_candidates_stay_on_the_target_drive():
    scanner = TempFilesScanner()
    for letter in _real_drives():
        for candidate in scanner._candidates(letter):
            assert drives.on_drive(candidate, letter), (
                f"临时文件候选 {candidate} 不在目标盘 {letter} 上"
            )


def test_system_extras_targets_stay_on_the_target_drive():
    """``_targets`` 混着两种归属的路径，过滤后必须只剩目标盘的。

    这个扫描器是唯一一个同时覆盖「系统盘的东西」和「用户盘的东西」的：
    ``<盘>\\Windows\\...`` 跟着 Windows 走，``%LOCALAPPDATA%\\...`` 跟着
    用户目录走。两个盘不是同一个盘时，后者必须被丢掉，否则在 D 盘扫描
    会列出 C 盘的崩溃转储目录，用户会以为自己选错了盘。
    """
    scanner = SystemExtrasScanner()
    for letter in _real_drives():
        kept = scanner._on_target_drive(letter)
        assert kept, f"{scanner.name} 在 {letter} 上一个目标都没留下"
        for label, path, *_ in kept:
            assert drives.on_drive(path, letter), f"{label} 跨盘了: {path}"


def test_system_extras_drops_targets_from_another_drive():
    """过滤不能是空转：用户目录不在目标盘时，确实有目标被丢掉。"""
    other = _other_drive()
    if other is None:
        pytest.skip("本机只有一个固定盘，无法构造「非用户盘」")

    scanner = SystemExtrasScanner()
    raw = scanner._targets(other)
    kept = scanner._on_target_drive(other)

    assert len(kept) < len(raw), (
        f"扫 {other} 时一个目标都没被过滤掉 —— 用户目录明明不在这个盘上"
    )
    for label, path, *_ in raw:
        if drives.on_drive(path, other):
            assert (label, path) in [(k[0], k[1]) for k in kept], (
                f"{label} 属于目标盘却被丢掉了"
            )


def test_recycle_bin_reports_only_the_target_drive(monkeypatch):
    """回收站是按卷独立的，扫 D 盘不能把 C 盘的回收站算进来。

    真机上 ``C:\\$Recycle.Bin`` 与 ``D:\\$Recycle.Bin`` 是两个互不相干的
    位置。早期实现把两者汇总成一个数字，用户在 D 盘上会看到 C 盘的占用，
    清空之后又对不上 —— 到底清的是哪个盘？

    这里把 ``dir_size`` 换掉，只验证「遍历的是哪个目录」和
    「产出的条目属于哪个盘」，不真的去读用户的回收站。
    """
    import src.scanners.recycle_bin as mod

    scanner = RecycleBinScanner()
    assert scanner.drive_scope == SCOPE_DRIVE

    for letter in _real_drives():
        walked: list[Path] = []

        def fake_dir_size(root, cancel_flag=None, *, max_seconds=6.0, _seen=walked):
            _seen.append(Path(root))
            return 4096

        monkeypatch.setattr(mod, "dir_size", fake_dir_size)
        with drives.use_drive(letter):
            items = scanner.scan()

        for root in walked:
            assert drives.on_drive(root, letter), f"扫 {letter} 时遍历了 {root}"
            assert root.name == "$Recycle.Bin", f"遍历的不是回收站: {root}"
        for item in items:
            assert item.drive == letter, f"{item.path} 不在目标盘 {letter} 上"
            assert item.id == f"recycle:{letter}", "id 没带盘符，多盘扫描会撞 id"
            assert letter in item.detail, "详情里没写清是哪个盘的回收站"


# ------------------------------------------------- 跨盘条目的删除闸门

def test_cross_drive_items_can_never_be_deletable():
    """跨盘 + 可删 = 「在 D 盘勾选、实际删掉 C 盘文件」。

    ``CleanItem.make`` 直接把这两个属性锁死：跨盘只对报告项开放。
    """
    item = CleanItem.make(
        id="x",
        category="c",
        path=r"D:\pagefile.sys",
        size_bytes=0,
        recommendation=Recommendation.NOT_RECOMMENDED,
        reason="页面文件不在本盘",
        deletable=True,
        cross_drive=True,
    )
    assert item.cross_drive is False, "可删除条目竟然带上了跨盘标记"

    report_only = CleanItem.make(
        id="y",
        category="c",
        path=r"D:\pagefile.sys",
        size_bytes=0,
        recommendation=Recommendation.NOT_RECOMMENDED,
        reason="页面文件不在本盘",
        deletable=False,
        cross_drive=True,
    )
    assert report_only.cross_drive is True, "报告项应当保留跨盘标记用于解释"


def test_item_drive_property_reads_the_path():
    item = CleanItem.make(
        id="x",
        category="c",
        path=r"D:\some\file.bin",
        size_bytes=1,
        recommendation=Recommendation.RECOMMEND,
        reason="r",
    )
    assert item.drive == "D:"


def test_base_scanner_defaults_to_drive_scope():
    """基类默认值必须是「任意盘」，否则新增扫描器会莫名其妙整类消失。"""
    assert Scanner.drive_scope == SCOPE_DRIVE
