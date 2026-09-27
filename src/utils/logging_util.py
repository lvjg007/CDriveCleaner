from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path


def logs_dir() -> Path:
    candidates: list[Path] = []
    for value in (
        os.environ.get("LOCALAPPDATA"),
        os.environ.get("TEMP"),
        os.environ.get("TMP"),
        tempfile.gettempdir(),
    ):
        if not value:
            continue
        candidate = Path(value) / "CDriveCleaner" / "logs"
        if candidate not in candidates:
            candidates.append(candidate)

    last_error: OSError | None = None
    for directory in candidates:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            return directory
        except OSError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise OSError("无法确定 CDriveCleaner 日志目录")


def setup_clean_logger() -> tuple[logging.Logger, Path]:
    log_path = logs_dir() / f"clean_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logger = logging.getLogger(f"CDriveCleaner.{log_path.stem}")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)
    return logger, log_path
