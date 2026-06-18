from __future__ import annotations

import logging
import sys
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent / "log"
LOG_FILE = LOG_DIR / "app.log"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def get_logger(name: str = "cinesis") -> logging.Logger:
    """Return a logger that writes to log/app.log and the uvicorn console.

    Console output reuses uvicorn's own handlers (when running under uvicorn)
    so app logs appear in the same terminal as the server logs. Configured
    once per name; repeated calls reuse the same handlers.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(LOG_FORMAT)

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    uvicorn_logger = logging.getLogger("uvicorn.error")
    if uvicorn_logger.handlers:
        for handler in uvicorn_logger.handlers:
            logger.addHandler(handler)
    else:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger
