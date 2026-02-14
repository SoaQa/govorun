import logging
import sys

from src.config import settings


def setup_logging() -> logging.Logger:
    """Настройка единого логгера для приложения."""
    logger = logging.getLogger("govorun")
    logger.setLevel(settings.log_level.upper())

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(settings.log_level.upper())
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


logger = setup_logging()
