from pathlib import Path

from src.utils.paths import is_hard_excluded, looks_like_project_dir


def test_system32_excluded():
    assert is_hard_excluded(r"C:\Windows\System32") is True
    assert is_hard_excluded(r"C:\Windows\System32\drivers") is True


def test_winsxs_excluded():
    assert is_hard_excluded(r"C:\Windows\WinSxS") is True


def test_temp_not_excluded():
    assert is_hard_excluded(r"C:\Windows\Temp") is False


def test_project_marker(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert looks_like_project_dir(nested) is True
