from pathlib import Path

from src.cleaner.executor import CleanExecutor
from src.models.items import CleanItem, Recommendation
from src.ui.treemap_window import category_totals
from src.ui.treemap import squarify
from src.utils import drives
from src.utils.recycle import send_to_recycle_bin


def test_squarify_covers_area():
    rects = squarify([("a", 70), ("b", 30)], 0, 0, 100, 100)
    assert len(rects) == 2
    area = sum(r.w * r.h for r in rects)
    assert 9900 < area < 10100


def test_recycle_file(tmp_path: Path):
    f = tmp_path / "to_recycle.txt"
    f.write_text("bye", encoding="utf-8")
    send_to_recycle_bin(f)
    assert not f.exists()


def test_executor_recycle_mode(tmp_path: Path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"12345")
    item = CleanItem.make(
        id="r1",
        category="测试",
        path=str(f),
        size_bytes=5,
        recommendation=Recommendation.RECOMMEND,
        reason="t",
    )
    result = CleanExecutor().execute([item], use_recycle_bin=True)
    assert result.success_count == 1
    assert not f.exists()
    assert "r1" in result.removed_ids


def test_executor_recycle_bin_category_empties_bin(monkeypatch):
    """清空回收站要**只清条目所在的那个盘**。

    多盘模式下报告里会同时有 C:/D:/E: 三个回收站条目。
    如果每次都调「清空所有盘」，用户点 D 盘那一项会连带清掉 C 盘的 ——
    点的是 D 盘，不该动 C 盘的东西。
    """
    calls = []
    monkeypatch.setattr(
        "src.cleaner.executor.empty_recycle_bin",
        lambda root=None: calls.append(root),
    )
    item = CleanItem.make(
        id="recycle",
        category="回收站",
        path=r"C:\$Recycle.Bin",
        size_bytes=123,
        recommendation=Recommendation.RECOMMEND,
        reason="recycle",
    )
    result = CleanExecutor().execute([item], use_recycle_bin=True)
    assert calls == ["C:\\"]
    assert result.success_count == 1
    assert result.freed_bytes == 123
    assert result.removed_ids == ["recycle"]


def test_executor_recycle_bin_empties_only_its_own_drive(monkeypatch):
    """D 盘条目必须传 ``D:\\``，不能传 ``C:\\`` 或 ``None``。"""
    calls = []
    monkeypatch.setattr(
        "src.cleaner.executor.empty_recycle_bin",
        lambda root=None: calls.append(root),
    )
    item = CleanItem.make(
        id="recycle:d",
        category="回收站",
        path=r"D:\$Recycle.Bin",
        size_bytes=1,
        recommendation=Recommendation.RECOMMEND,
        reason="recycle",
    )
    with drives.use_drive("D:"):
        CleanExecutor().execute([item], use_recycle_bin=True)
    assert calls == ["D:\\"]


def test_fast_scan_skips_slow():
    from src.app.orchestrator import Orchestrator, _SLOW_SCANNER_NAMES
    from src.scanners.registry import all_scanners

    all_names = {s.name for s in all_scanners()}
    assert _SLOW_SCANNER_NAMES & all_names
    # smoke: fast scan constructs
    orch = Orchestrator()
    assert orch.executor is not None


def test_treemap_totals_exclude_reports_and_nested_duplicates(tmp_path: Path):
    parent = tmp_path / "parent"
    child = parent / "child"
    child.mkdir(parents=True)
    report = CleanItem.make(
        id="report",
        category="报告",
        path=str(tmp_path / "report.bin"),
        size_bytes=999,
        recommendation=Recommendation.NOT_RECOMMENDED,
        reason="report",
        deletable=False,
    )
    parent_item = CleanItem.make(
        id="parent",
        category="缓存",
        path=str(parent),
        size_bytes=100,
        recommendation=Recommendation.RECOMMEND,
        reason="parent",
    )
    child_item = CleanItem.make(
        id="child",
        category="缓存",
        path=str(child),
        size_bytes=40,
        recommendation=Recommendation.RECOMMEND,
        reason="child",
    )
    assert category_totals([report, parent_item, child_item]) == {"缓存": 100}
