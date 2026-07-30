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
    items = [a, b, c]
    assert Orchestrator.items_for_safe_clean(items) == [a]
    assert Orchestrator.items_for_deep_clean(items) == [a, b]
    assert Orchestrator.needs_second_confirm([b]) is True
    assert Orchestrator.needs_second_confirm([a]) is False
