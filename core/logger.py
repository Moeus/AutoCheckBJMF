import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler

from .constants import LOG_PATH
from .timezone import BEIJING_TZ


class BeijingFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        timestamp = datetime.fromtimestamp(record.created, BEIJING_TZ)
        return timestamp.strftime(datefmt) if datefmt else timestamp.isoformat(sep=" ", timespec="milliseconds")


def setup_logger(debug: bool) -> logging.Logger:
    """
    初始化日志记录器。
    """
    logger = logging.getLogger("AutoCheckBJMF")
    logger.setLevel(logging.INFO if debug else logging.WARNING)
    logger.propagate = False

    log_file = str(LOG_PATH.resolve())
    has_handler = any(
        isinstance(handler, logging.FileHandler) and handler.baseFilename == log_file
        for handler in logger.handlers
    )
    if not has_handler:
        handler = RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(BeijingFormatter("%(asctime)s - %(levelname)s - %(message)s"))
        logger.addHandler(handler)
    if debug:
        logger.info("调试模式已启用")

    return logger
