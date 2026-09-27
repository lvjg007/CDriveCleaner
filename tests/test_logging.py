from pathlib import Path

from src.utils.logging_util import logs_dir, setup_clean_logger


def test_logs_dir_uses_localappdata(monkeypatch, tmp_path: Path):
    local = tmp_path / "local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("TEMP", str(tmp_path / "temp"))
    monkeypatch.delenv("TMP", raising=False)

    assert logs_dir() == local / "CDriveCleaner" / "logs"


def test_logs_dir_falls_back_to_temp_without_localappdata(monkeypatch, tmp_path: Path):
    fallback = tmp_path / "temp"
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setenv("TEMP", str(fallback))
    monkeypatch.delenv("TMP", raising=False)

    assert logs_dir() == fallback / "CDriveCleaner" / "logs"


def test_setup_clean_logger_writes_under_selected_directory(monkeypatch, tmp_path: Path):
    local = tmp_path / "local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("TEMP", str(tmp_path / "temp"))

    logger, path = setup_clean_logger()
    try:
        logger.info("test")
        assert path.parent == local / "CDriveCleaner" / "logs"
        assert path.exists()
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers.clear()
