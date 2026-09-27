import time
from pathlib import Path

from src.cleaner.executor import CleanExecutor
from src.models.items import CleanItem, Recommendation
from src.utils.freshness import is_fresh


def test_is_fresh_new_file(tmp_path: Path):
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    assert is_fresh(f, hours=24) is True


def test_is_fresh_old_file(tmp_path: Path):
    f = tmp_path / "old.txt"
    f.write_text("x", encoding="utf-8")
    old = time.time() - 48 * 3600
    import os

    os.utime(f, (old, old))
    assert is_fresh(f, hours=24) is False


def test_dry_run_does_not_delete(tmp_path: Path):
    f = tmp_path / "junk.txt"
    f.write_text("hello", encoding="utf-8")
    item = CleanItem.make(
        id="dry",
        category="测试",
        path=str(f),
        size_bytes=5,
        recommendation=Recommendation.RECOMMEND,
        reason="t",
    )
    result = CleanExecutor().execute([item], dry_run=True)
    assert result.success_count == 1
    assert f.exists()
    assert result.removed_ids == []
    assert result.freed_bytes == 0
    assert result.estimated_bytes == 5


def test_space_hogs_scanner_runs():
    from src.scanners.space_hogs import SpaceHogsScanner

    items = SpaceHogsScanner().scan()
    assert isinstance(items, list)
