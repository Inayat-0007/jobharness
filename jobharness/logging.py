from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FORMAT = "%(asctime)s %(levelname)-8s [%(threadName)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False
_file_logging = True


def setup_logging(level: int = logging.INFO, log_dir: str = "logs") -> None:
    """Configure the root logger once: console at INFO, rotating file at ``level``.

    If the log directory cannot be created (e.g. read-only CWD), the file
    handler is skipped and logging continues console-only (no temp-dir
    fallback), so a logging setup failure never aborts the run.
    ``_configured`` is set even when file logging was skipped, so later calls
    return early instead of re-attempting the failed file setup.
    """
    global _configured, _file_logging
    if _configured:
        return
    _configured = True
    log_path = Path(log_dir)
    try:
        log_path.mkdir(parents=True, exist_ok=True)
    except OSError:
        _file_logging = False
    else:
        _file_logging = True

    fmt = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    root = logging.getLogger()
    root.setLevel(level)

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    root.addHandler(console)

    if _file_logging:
        fh = RotatingFileHandler(
            log_path / "jobharness.log",
            maxBytes=5_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        fh.setLevel(level)
        fh.setFormatter(fmt)
        root.addHandler(fh)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"jobharness.{name}")
