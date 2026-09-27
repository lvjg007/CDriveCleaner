from pathlib import Path

from src.cleaner.executor import CleanExecutor
from src.models.items import CleanItem, Recommendation
from src.app.orchestrator import Orchestrator


def test_executor_deletes_file(tmp_path: Path):
    f = tmp_path / "junk.txt"
    f.write_text("hello", encoding="utf-8")
    item = CleanItem.make(
        id="t",
        category="测试",
        path=str(f),
        size_bytes=5,
        recommendation=Recommendation.RECOMMEND,
        reason="test",
    )
    result = CleanExecutor().execute([item])
    assert result.success_count == 1
    assert "t" in result.removed_ids
    assert not f.exists()


def test_executor_missing_path_still_removed():
    item = CleanItem.make(
        id="gone",
        category="测试",
        path=r"C:\this_path_should_not_exist_CDriveCleaner_xyz\a.txt",
        size_bytes=1,
        recommendation=Recommendation.RECOMMEND,
        reason="test",
    )
    result = CleanExecutor().execute([item])
    assert result.success_count == 1
    assert "gone" in result.removed_ids
    assert result.freed_bytes == 0


def test_executor_skips_hard_excluded():
    item = CleanItem.make(
        id="sys",
        category="测试",
        path=r"C:\Windows\System32",
        size_bytes=1,
        recommendation=Recommendation.RECOMMEND,
        reason="should skip",
    )
    result = CleanExecutor().execute([item])
    assert result.fail_count == 1
    assert Path(r"C:\Windows\System32").exists()


def test_executor_skips_explicitly_protected_item(tmp_path: Path):
    f = tmp_path / "report.bin"
    f.write_bytes(b"keep")
    item = CleanItem.make(
        id="protected",
        category="占空间报告(勿盲删)",
        path=str(f),
        size_bytes=4,
        recommendation=Recommendation.NOT_RECOMMENDED,
        reason="report only",
        deletable=False,
        protection_reason="报告项只能展示，不能直接删除",
        selected=False,
    )
    result = CleanExecutor().execute([item])
    assert result.fail_count == 1
    assert result.errors and "报告项只能展示" in result.errors[0]
    assert f.exists()


def test_executor_skips_system_report_file():
    item = CleanItem.make(
        id="hiberfil",
        category="占空间报告(勿盲删)",
        path=r"C:\hiberfil.sys",
        size_bytes=1,
        recommendation=Recommendation.RECOMMEND,
        reason="report only",
    )
    result = CleanExecutor().execute([item])
    assert result.fail_count == 1
    assert result.removed_ids == []


def test_executor_reports_missing_admin_even_in_dry_run(monkeypatch, tmp_path: Path):
    f = tmp_path / "admin-cache.bin"
    f.write_bytes(b"admin")
    monkeypatch.setattr("src.cleaner.executor.is_admin", lambda: False)
    item = CleanItem.make(
        id="admin",
        category="系统缓存",
        path=str(f),
        size_bytes=5,
        recommendation=Recommendation.RECOMMEND,
        reason="admin",
        needs_admin=True,
    )
    result = CleanExecutor().execute([item], dry_run=True)
    assert result.success_count == 0
    assert result.fail_count == 1
    assert result.partial_count == 0
    assert result.freed_bytes == 0
    assert "需要管理员权限" in result.errors[0]
    assert f.exists()


def test_executor_records_cancelled_and_remaining_items(tmp_path: Path):
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("1", encoding="utf-8")
    second.write_text("2", encoding="utf-8")
    items = [
        CleanItem.make(id="first", category="测试", path=str(first), size_bytes=1, recommendation=Recommendation.RECOMMEND, reason="t"),
        CleanItem.make(id="second", category="测试", path=str(second), size_bytes=1, recommendation=Recommendation.RECOMMEND, reason="t"),
    ]
    result = CleanExecutor().execute(items, cancel_flag={"cancel": True})
    assert result.cancelled is True
    assert result.remaining_count == 2
    assert result.success_count == 0
    assert first.exists() and second.exists()


def test_executor_reports_partial_directory_failure(monkeypatch, tmp_path: Path):
    root = tmp_path / "cache"
    root.mkdir()
    good = root / "good.tmp"
    bad = root / "bad.tmp"
    good.write_text("good", encoding="utf-8")
    bad.write_text("bad", encoding="utf-8")
    original_unlink = Path.unlink

    def unlink_with_failure(self, missing_ok=False):
        if self == bad:
            raise PermissionError("locked")
        return original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink_with_failure)
    item = CleanItem.make(
        id="dir",
        category="测试",
        path=str(root),
        size_bytes=7,
        recommendation=Recommendation.RECOMMEND,
        reason="test",
    )
    result = CleanExecutor().execute([item])
    assert result.success_count == 0
    assert result.fail_count == 1
    assert result.partial_count == 1
    assert result.freed_bytes == len("good")
    assert result.removed_ids == []
    assert not good.exists()
    assert bad.exists()


def test_executor_temp_directory_preserves_bytes_on_late_failure(monkeypatch, tmp_path: Path):
    root = tmp_path / "temp"
    root.mkdir()
    first = root / "first.tmp"
    second = root / "second.tmp"
    first.write_bytes(b"1234")
    second.write_bytes(b"567890")
    original_unlink = Path.unlink

    def unlink_with_failure(self, missing_ok=False):
        if self == second:
            raise PermissionError("locked")
        return original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr("src.cleaner.executor.is_fresh", lambda _path: False)
    monkeypatch.setattr(Path, "unlink", unlink_with_failure)
    item = CleanItem.make(
        id="temp-late-failure",
        category="系统临时文件",
        path=str(root),
        size_bytes=10,
        recommendation=Recommendation.RECOMMEND,
        reason="test",
    )
    result = CleanExecutor().execute([item])
    assert result.partial_count == 1
    assert result.fail_count == 1
    assert result.freed_bytes == 4
    assert result.removed_ids == []
    assert not first.exists()
    assert second.exists()


def test_executor_does_not_double_count_nested_directories(tmp_path: Path):
    parent = tmp_path / "parent"
    child = parent / "child"
    child.mkdir(parents=True)
    payload = child / "payload.bin"
    payload.write_bytes(b"1234")
    items = [
        CleanItem.make(
            id="child",
            category="测试",
            path=str(child),
            size_bytes=4,
            recommendation=Recommendation.RECOMMEND,
            reason="child",
        ),
        CleanItem.make(
            id="parent",
            category="测试",
            path=str(parent),
            size_bytes=4,
            recommendation=Recommendation.RECOMMEND,
            reason="parent",
        ),
    ]
    result = CleanExecutor().execute(items)
    assert result.success_count == 1
    assert result.freed_bytes == 4
    assert result.removed_ids == ["parent"]
    assert parent.exists()
    assert not payload.exists()


def test_safe_and_deep_filters():
    a = CleanItem.make(
        id="a",
        category="a",
        path="a",
        size_bytes=1,
        recommendation=Recommendation.RECOMMEND,
        reason="r",
    )
    b = CleanItem.make(
        id="b",
        category="b",
        path="b",
        size_bytes=1,
        recommendation=Recommendation.OPTIONAL,
        reason="r",
    )
    c = CleanItem.make(
        id="c",
        category="c",
        path="c",
        size_bytes=1,
        recommendation=Recommendation.NOT_RECOMMENDED,
        reason="r",
    )
    report = CleanItem.make(
        id="report",
        category="报告",
        path="report",
        size_bytes=1,
        recommendation=Recommendation.OPTIONAL,
        reason="r",
        deletable=False,
        selected=True,
    )
    items = [a, b, c, report]
    assert Orchestrator.items_for_safe_clean(items) == [a]
    assert Orchestrator.items_for_deep_clean(items) == [a, b]
    assert Orchestrator.selected_items(items) == [a]
    assert Orchestrator.needs_second_confirm([b]) is True
    assert Orchestrator.needs_second_confirm([a]) is False
