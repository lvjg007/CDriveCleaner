from pathlib import Path

from src.scanners.duplicates import DuplicateFilesScanner, _quick_hash
from src.scanners.empty_folders import EmptyFolderScanner
from src.scanners.extension_stats import ExtensionStatsScanner


def test_empty_folder_scanner(tmp_path: Path, monkeypatch):
    empty = tmp_path / "empty_dir"
    empty.mkdir()
    (tmp_path / "with_file").mkdir()
    (tmp_path / "with_file" / "a.txt").write_text("x", encoding="utf-8")

    scanner = EmptyFolderScanner()
    monkeypatch.setattr(scanner, "_roots", lambda: [tmp_path])
    items = scanner.scan()
    paths = {i.path for i in items}
    assert str(empty) in paths
    assert not any(str(tmp_path / "with_file") == p for p in paths)


def test_quick_hash_stable(tmp_path: Path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"hello" * 1000)
    assert _quick_hash(f) == _quick_hash(f)


def test_duplicates_finds_copies(tmp_path: Path, monkeypatch):
    d = tmp_path / "Downloads"
    d.mkdir()
    data = b"x" * (2 * 1024 * 1024)
    a = d / "a.dat"
    b = d / "b.dat"
    a.write_bytes(data)
    b.write_bytes(data)
    scanner = DuplicateFilesScanner()
    monkeypatch.setattr(scanner, "_roots", lambda: [d])
    items = scanner.scan()
    assert len(items) >= 1
    assert all(i.recommendation.value == "optional" for i in items)


def test_extension_stats(tmp_path: Path, monkeypatch):
    d = tmp_path / "Downloads"
    d.mkdir()
    (d / "a.tmp").write_bytes(b"1" * 1000)
    (d / "b.tmp").write_bytes(b"2" * 2000)
    (d / "c.mp4").write_bytes(b"3" * 5000)
    scanner = ExtensionStatsScanner()
    monkeypatch.setattr(scanner, "_roots", lambda: [d])
    items = scanner.scan()
    assert any(".tmp" in i.detail for i in items)
    assert any(".mp4" in i.detail for i in items)
