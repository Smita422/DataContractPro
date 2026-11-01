"""Structured logging configuration for SchemaGuard."""

import logging
import os
import sys
from typing import Optional


def setup_logger(
    name: str = "schemaguard",
    level: Optional[str] = None,
    log_format: Optional[str] = None,
) -> logging.Logger:
    """Configure and return a structured logger instance."""
    log_level_name = level or os.getenv("SCHEMAGUARD_LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    # Avoid duplicate handlers if logger was already configured
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(log_level)

        default_format = (
            "[%(asctime)s] [%(levelname)s] [%(name)s] "
            "[%(filename)s:%(lineno)d]: %(message)s"
        )
        formatter = logging.Formatter(
            log_format or default_format, datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


logger = setup_logger()
