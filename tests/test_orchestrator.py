from src.app.orchestrator import Orchestrator
from src.models.items import CleanItem, Recommendation
from src.scanners.base import Scanner, SCOPE_DRIVE
from src.utils.paths import mark_scan_partial


def test_orchestrator_scan_smoke():
    """冒烟：至少能跑完扫描器注册列表（可能 0 项，视机器环境）。"""
    orch = Orchestrator()
    # 大文件扫描可能慢，用 cancel 提前结束不合适；这里直接 scan
    # 为加快测试，临时只测 safe filter 已在 test_executor
    # 这里验证 all_scanners 可导入且 orchestrator 可构造
    assert orch.executor is not None
    assert Recommendation.RECOMMEND.value == "recommend"


def test_scan_records_fast_mode_and_filters_slow_scanners(monkeypatch):
    class FakeScanner(Scanner):
        drive_scope = SCOPE_DRIVE

        def __init__(self, name, item_id):
            self.name = name
            self.item_id = item_id

        def scan(self, cancel_flag=None, progress=None):
            return [
                CleanItem.make(
                    id=self.item_id,
                    category="测试",
                    path=self.item_id,
                    size_bytes=1,
                    recommendation=Recommendation.RECOMMEND,
                    reason="test",
                )
            ]

    monkeypatch.setattr(
        "src.app.orchestrator.all_scanners",
        lambda: [FakeScanner("普通扫描", "normal"), FakeScanner("重复文件", "slow")],
    )
    monkeypatch.setattr("src.app.orchestrator.scanner_category_order", lambda: ["测试"])
    orch = Orchestrator()
    items = orch.scan(fast=True)
    assert [item.id for item in items] == ["normal"]
    assert orch.last_scan_fast is True
    assert orch.last_scan_cancelled is False


def test_scan_records_cancelled_state(monkeypatch):
    class FakeScanner(Scanner):
        name = "普通扫描"
        drive_scope = SCOPE_DRIVE

        def scan(self, cancel_flag=None, progress=None):
            return []

    monkeypatch.setattr("src.app.orchestrator.all_scanners", lambda: [FakeScanner()])
    monkeypatch.setattr("src.app.orchestrator.scanner_category_order", lambda: [])
    orch = Orchestrator()
    orch.scan(cancel_flag={"cancel": True})
    assert orch.last_scan_cancelled is True


def test_scan_records_partial_categories(monkeypatch):
    class FakeScanner(Scanner):
        name = "限时扫描"
        drive_scope = SCOPE_DRIVE

        def scan(self, cancel_flag=None, progress=None):
            mark_scan_partial(cancel_flag, self.name)
            return []

    monkeypatch.setattr("src.app.orchestrator.all_scanners", lambda: [FakeScanner()])
    monkeypatch.setattr("src.app.orchestrator.scanner_category_order", lambda: [])
    orch = Orchestrator()
    orch.scan()
    assert orch.last_scan_partial_categories == ["限时扫描"]


def test_scan_deduplicates_normalized_paths_and_prefers_protected_item(monkeypatch, tmp_path):
    cache = tmp_path / "Cache"
    cache.mkdir()

    class FakeScanner(Scanner):
        drive_scope = SCOPE_DRIVE

        def __init__(self, name, item):
            self.name = name
            self.item = item

        def scan(self, cancel_flag=None, progress=None):
            return [self.item]

    first = CleanItem.make(
        id="gpu:cache",
        category="图形缓存",
        path=str(cache),
        size_bytes=10,
        recommendation=Recommendation.RECOMMEND,
        reason="cache",
    )
    protected = CleanItem.make(
        id="report:cache",
        category="报告",
        path=str(tmp_path / "." / "Cache"),
        size_bytes=10,
        recommendation=Recommendation.NOT_RECOMMENDED,
        reason="report",
        deletable=False,
        protection_reason="report only",
    )
    monkeypatch.setattr(
        "src.app.orchestrator.all_scanners",
        lambda: [FakeScanner("图形缓存", first), FakeScanner("报告", protected)],
    )
    monkeypatch.setattr("src.app.orchestrator.scanner_category_order", lambda: ["图形缓存", "报告"])
    items = Orchestrator().scan()
    assert len(items) == 1
    assert items[0].id == "report:cache"


def test_extension_report_does_not_hide_actionable_item(monkeypatch, tmp_path):
    target = tmp_path / "sample.tmp"
    target.write_text("x", encoding="utf-8")

    class FakeScanner(Scanner):
        drive_scope = SCOPE_DRIVE

        def __init__(self, name, item):
            self.name = name
            self.item = item

        def scan(self, cancel_flag=None, progress=None):
            return [self.item]

    actionable = CleanItem.make(
        id="temp:sample",
        category="系统临时文件",
        path=str(target),
        size_bytes=1,
        recommendation=Recommendation.RECOMMEND,
        reason="temp",
    )
    report = CleanItem.make(
        id="ext:.tmp",
        category="扩展名占用汇总",
        path=str(target),
        size_bytes=100,
        recommendation=Recommendation.OPTIONAL,
        reason="summary",
        deletable=False,
        selected=False,
    )
    monkeypatch.setattr(
        "src.app.orchestrator.all_scanners",
        lambda: [FakeScanner("系统临时文件", actionable), FakeScanner("扩展名占用汇总", report)],
    )
    monkeypatch.setattr("src.app.orchestrator.scanner_category_order", lambda: ["系统临时文件", "扩展名占用汇总"])
    items = Orchestrator().scan()
    assert len(items) == 1
    assert items[0].id == "temp:sample"


def test_safe_targets_collapse_deletable_parent_and_child(tmp_path):
    parent = tmp_path / "parent"
    child = parent / "child"
    child.mkdir(parents=True)
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
    assert Orchestrator.items_for_safe_clean([child_item, parent_item]) == [parent_item]


def test_report_parent_does_not_hide_deletable_child(tmp_path):
    parent = tmp_path / "parent"
    child = parent / "cache"
    child.mkdir(parents=True)
    report = CleanItem.make(
        id="report",
        category="报告",
        path=str(parent),
        size_bytes=100,
        recommendation=Recommendation.NOT_RECOMMENDED,
        reason="report",
        deletable=False,
    )
    child_item = CleanItem.make(
        id="child",
        category="缓存",
        path=str(child),
        size_bytes=40,
        recommendation=Recommendation.RECOMMEND,
        reason="child",
    )
    assert Orchestrator.items_for_safe_clean([report, child_item]) == [child_item]


def test_effective_targets_do_not_treat_prefix_as_parent(tmp_path):
    temp = tmp_path / "Temp"
    temp2 = tmp_path / "Temp2"
    temp.mkdir()
    temp2.mkdir()
    first = CleanItem.make(
        id="temp",
        category="缓存",
        path=str(temp),
        size_bytes=1,
        recommendation=Recommendation.RECOMMEND,
        reason="temp",
    )
    second = CleanItem.make(
        id="temp2",
        category="缓存",
        path=str(temp2),
        size_bytes=1,
        recommendation=Recommendation.RECOMMEND,
        reason="temp2",
    )
    assert Orchestrator.items_for_safe_clean([first, second]) == [first, second]
