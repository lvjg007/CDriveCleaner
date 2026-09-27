"""家目录残留扫描器的分级、分组与安全边界测试。"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.models.items import Recommendation
from src.scanners import home_residue
from src.scanners.home_residue import HomeResidueScanner
from src.scanners.registry import scanner_category_order
from src.scanners.tiers import Target
from src.utils.paths import canonical_path_key, is_deletion_protected

_MB = 1024 * 1024


def _dir_with_size(root: Path, size: int) -> Path:
    """造一个目录，内含一个指定大小的文件（要超过下限才会被产出）。"""
    root.mkdir(parents=True, exist_ok=True)
    (root / "payload.bin").write_bytes(b"\0" * size)
    return root


def _scan_with(monkeypatch, targets: list[Target]) -> dict[str, object]:
    scanner = HomeResidueScanner()
    monkeypatch.setattr(scanner, "_targets", lambda: targets)
    return {item.id: item for item in scanner.scan()}


# --------------------------------------------------------------- 注册与分级

def test_home_residue_category_is_registered():
    assert "家目录残留" in scanner_category_order()


def test_safe_tier_is_recommended_and_preselected(monkeypatch, tmp_path: Path):
    cache = _dir_with_size(tmp_path / "Cache", 2 * _MB)
    by_id = _scan_with(
        monkeypatch,
        [Target("某工具缓存", cache, home_residue.SAFE, "自动重建")],
    )
    item = by_id["home:某工具缓存"]
    assert item.recommendation == Recommendation.RECOMMEND
    assert item.deletable is True
    assert item.selected is True


def test_optional_tier_is_selectable_but_not_preselected(monkeypatch, tmp_path: Path):
    dl = _dir_with_size(tmp_path / "downloaded", 3 * _MB)
    by_id = _scan_with(
        monkeypatch,
        [Target("下载缓存", dl, home_residue.OPTIONAL, "删了要重新下载")],
    )
    item = by_id["home:下载缓存"]
    assert item.recommendation == Recommendation.OPTIONAL
    assert item.deletable is True
    assert item.selected is False


def test_caution_tier_is_selectable_but_discouraged(monkeypatch, tmp_path: Path):
    """分层只表达风险，不剥夺选择权 —— 这是「由我来确认删除和保留」的产品承诺。"""
    ext = _dir_with_size(tmp_path / "extensions", 3 * _MB)
    by_id = _scan_with(
        monkeypatch,
        [Target("已装扩展", ext, home_residue.CAUTION, "删了功能会缺")],
    )
    item = by_id["home:已装扩展"]
    assert item.recommendation == Recommendation.NOT_RECOMMENDED
    assert item.deletable is True
    assert item.selected is False
    assert "不建议删除" in item.reason


def test_all_three_tiers_stay_selectable(monkeypatch, tmp_path: Path):
    by_id = _scan_with(monkeypatch, [
        Target("甲", _dir_with_size(tmp_path / "a", 2 * _MB), home_residue.SAFE, "日志"),
        Target("乙", _dir_with_size(tmp_path / "b", 2 * _MB), home_residue.OPTIONAL, "下载物"),
        Target("丙", _dir_with_size(tmp_path / "c", 2 * _MB), home_residue.CAUTION, "扩展"),
    ])
    assert len(by_id) == 3
    assert all(item.deletable for item in by_id.values())
    assert [i.id for i in by_id.values() if i.selected] == ["home:甲"]


# --------------------------------------------------------------- 目录 glob

def test_glob_matches_directories_too(monkeypatch, tmp_path: Path):
    """*-updater 是目录而非文件，glob 展开必须支持目录 —— 这是本扫描器的主力目标。

    （「AI 工具数据」的 glob 只处理文件，因为那边匹配的是 *.bak* 这类文件。）
    """
    local = tmp_path / "Local"
    upd = local / "@demo-app-updater"
    upd.mkdir(parents=True)
    (upd / "installer.exe").write_bytes(b"\0" * (3 * _MB))

    tiny = local / "tiny-updater"
    tiny.mkdir()
    (tiny / "x.bin").write_bytes(b"\0" * 1000)

    untouched = local / "not-matched"
    untouched.mkdir()
    (untouched / "y.bin").write_bytes(b"\0" * (3 * _MB))

    by_id = _scan_with(monkeypatch, [
        Target("更新器残留", local, home_residue.SAFE, "更新包残留", pattern="*-updater"),
    ])
    assert list(by_id) == ["home:更新器残留:@demo-app-updater"]


def test_glob_expansion_skips_tiny_entries(monkeypatch, tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "small.dmp").write_bytes(b"\0" * 100)
    by_id = _scan_with(monkeypatch, [
        Target("崩溃转储", root, home_residue.SAFE, "转储", pattern="*.dmp"),
    ])
    assert by_id == {}


def test_truncated_size_is_disclosed(monkeypatch, tmp_path: Path):
    """大小被超时截断时必须写进理由。

    否则用户会按差了几十倍的值做删/留判断 —— 实测 .trae-cn/extensions
    真实 1.69 GB，2 秒上限只量到 56 MB。
    """
    root = tmp_path / "many-files"
    root.mkdir()

    by_id = _scan_with(monkeypatch, [Target("大目录", root, home_residue.SAFE, "缓存")])
    assert by_id == {}  # 未打桩时目录是空的，不产出

    monkeypatch.setattr(home_residue, "dir_size_ex", lambda *a, **k: (5 * _MB, True))
    by_id = _scan_with(monkeypatch, [Target("大目录", root, home_residue.SAFE, "缓存")])
    assert home_residue._TRUNCATED_NOTE in by_id["home:大目录"].reason

    monkeypatch.setattr(home_residue, "dir_size_ex", lambda *a, **k: (5 * _MB, False))
    by_id = _scan_with(monkeypatch, [Target("大目录", root, home_residue.SAFE, "缓存")])
    assert home_residue._TRUNCATED_NOTE not in by_id["home:大目录"].reason


# --------------------------------------------------------------- 安全边界

def test_reparse_target_is_never_emitted(monkeypatch, tmp_path: Path, make_junction):
    """junction 目标必须跳过：删它会顺着链接打到目标目录上。"""
    real = tmp_path / "real"
    real.mkdir()
    (real / "payload.bin").write_bytes(b"\0" * (2 * _MB))
    link = tmp_path / "linked-cache"
    if not make_junction(link, real):
        pytest.skip("当前环境无法创建 junction")

    by_id = _scan_with(
        monkeypatch,
        [Target("伪装缓存", link, home_residue.SAFE, "不该产出")],
    )
    assert by_id == {}


def test_declared_targets_are_not_deletion_protected():
    """回归：目标若被保护规则拦下，用户勾了也会静默失败。

    只检查声明的路径，不做目录遍历，所以很快、且与机器是否装了这些软件无关。
    """
    scanner = HomeResidueScanner()
    blocked = [str(t.path) for t in scanner._targets() if is_deletion_protected(t.path)]
    assert blocked == [], f"以下目标会被保护规则误拦：{blocked}"


def test_declared_targets_avoid_credentials():
    scanner = HomeResidueScanner()
    offenders = [str(t.path) for t in scanner._targets() if scanner._is_never_touch(t.path)]
    assert offenders == [], f"目标清单里混入了凭据类路径：{offenders}"


def test_target_labels_are_unique():
    labels = [t.label for t in HomeResidueScanner()._targets()]
    assert len(labels) == len(set(labels))


def test_every_target_has_a_group():
    """没打分组的目标会退回扫描器名，在分类下拉里挤成一大坨。"""
    groups = [t.group for t in HomeResidueScanner()._targets()]
    assert "" not in groups
    assert all(g.startswith(home_residue._GROUP_PREFIX) for g in groups)


def test_no_path_overlap_with_other_scanners():
    """回归：三个扫描器不能对同一条路径各报一次 —— 用户会看到重复项、空间重复计量。"""
    from src.scanners.ai_tools import AiToolsScanner
    from src.scanners.dev_cache import DevCacheScanner

    other_keys = [canonical_path_key(t.path) for t in AiToolsScanner()._targets()]
    # DevCacheScanner 的清单是 (label, raw_path) 二元组
    other_keys += [canonical_path_key(raw) for _label, raw in DevCacheScanner()._candidates()]

    clashes = []
    for t in HomeResidueScanner()._targets():
        if t.pattern:
            # glob 目标按模式匹配，天然不与具体路径冲突
            continue
        key = canonical_path_key(t.path)
        for ok in other_keys:
            if key == ok or key.startswith(ok + os.sep) or ok.startswith(key + os.sep):
                clashes.append((str(t.path), ok))
    assert clashes == [], f"与其它扫描器路径重叠：{clashes}"


# --------------------------------------------------------------- 中断与预算

def test_cancel_stops_scan(monkeypatch, tmp_path: Path):
    cache = _dir_with_size(tmp_path / "Cache", 2 * _MB)
    scanner = HomeResidueScanner()
    monkeypatch.setattr(
        scanner, "_targets", lambda: [Target("缓存", cache, home_residue.SAFE, "x")]
    )
    assert scanner.scan(cancel_flag={"cancel": True}) == []


def test_budget_exhaustion_marks_partial(monkeypatch, tmp_path: Path):
    cache = _dir_with_size(tmp_path / "Cache", 2 * _MB)
    scanner = HomeResidueScanner()
    monkeypatch.setattr(
        scanner, "_targets", lambda: [Target("缓存", cache, home_residue.SAFE, "x")]
    )
    monkeypatch.setattr(home_residue, "_TOTAL_BUDGET_SECONDS", -1.0)
    flag: dict = {}
    assert scanner.scan(cancel_flag=flag) == []
    assert "家目录残留" in flag["_scan_meta"]["partial_categories"]
