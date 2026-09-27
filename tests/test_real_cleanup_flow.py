import os
import time
from pathlib import Path

from src.app.orchestrator import Orchestrator
from src.scanners.temp_files import TempFilesScanner


def test_temp_scan_to_safe_clean_removes_real_old_file(monkeypatch, tmp_path: Path):
    temp_root = tmp_path / "user-temp"
    temp_root.mkdir()
    old_file = temp_root / "old.tmp"
    old_file.write_bytes(b"garbage-data")
    now = time.time()
    os.utime(old_file, (now - 48 * 3600, now - 48 * 3600))

    scanner = TempFilesScanner()
    monkeypatch.setattr("src.scanners.temp_files.existing_paths", lambda _candidates: [temp_root])
    items = scanner.scan()
    assert len(items) == 1
    assert items[0].size_bytes == old_file.stat().st_size
    assert items[0].selected is True

    monkeypatch.setattr("src.cleaner.executor.is_deletion_protected", lambda _path: False)
    orch = Orchestrator()
    targets = orch.items_for_safe_clean(items)
    result = orch.clean(targets)

    assert result.success_count == 1
    assert result.fail_count == 0
    assert result.freed_bytes == len(b"garbage-data")
    assert result.removed_ids == [items[0].id]
    assert not old_file.exists()


def test_temp_clean_preserves_fresh_file_inside_old_directory(tmp_path: Path, monkeypatch):
    temp_root = tmp_path / "user-temp"
    nested = temp_root / "old-dir"
    nested.mkdir(parents=True)
    old_file = nested / "old.tmp"
    fresh_file = nested / "fresh.tmp"
    old_file.write_bytes(b"old")
    fresh_file.write_bytes(b"fresh")
    old = time.time() - 48 * 3600
    os.utime(old_file, (old, old))
    scanner_item = __import__("src.models.items", fromlist=["CleanItem"]).CleanItem.make(
        id="temp-nested", category="系统临时文件", path=str(temp_root), size_bytes=8,
        recommendation=__import__("src.models.items", fromlist=["Recommendation"]).Recommendation.RECOMMEND,
        reason="temp",
    )
    monkeypatch.setattr("src.cleaner.executor.is_deletion_protected", lambda _path: False)
    result = __import__("src.cleaner.executor", fromlist=["CleanExecutor"]).CleanExecutor().execute([scanner_item])
    assert result.success_count == 1
    assert old_file.exists() is False
    assert fresh_file.exists() is True
    assert result.freed_bytes == 3


def test_temp_clean_reports_noop_when_all_files_are_fresh(tmp_path: Path, monkeypatch):
    from src.models.items import CleanItem, Recommendation
    root = tmp_path / "user-temp"
    root.mkdir()
    fresh = root / "fresh.tmp"
    fresh.write_bytes(b"fresh")
    item = CleanItem.make(
        id="fresh-only", category=TempFilesScanner.name, path=str(root), size_bytes=5,
        recommendation=Recommendation.RECOMMEND, reason="temp",
    )
    monkeypatch.setattr("src.cleaner.executor.is_deletion_protected", lambda _path: False)
    result = __import__("src.cleaner.executor", fromlist=["CleanExecutor"]).CleanExecutor().execute([item])
    assert result.success_count == 0
    assert result.fail_count == 1
    assert result.removed_ids == []
    assert fresh.exists()
