from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path


def project_root() -> Path:
    # src/utils/logging_util.py -> 项目根
    return Path(__file__).resolve().parents[2]


def logs_dir() -> Path:
    d = project_root() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def setup_clean_logger() -> tuple[logging.Logger, Path]:
    log_path = logs_dir() / f"clean_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logger = logging.getLogger(f"CDriveCleaner.{log_path.stem}")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)
    return logger, log_path
