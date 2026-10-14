import logging
from datetime import datetime

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

    if debug:
        log_file = str(LOG_PATH)
        has_handler = any(
            isinstance(handler, logging.FileHandler) and handler.baseFilename == log_file
            for handler in logger.handlers
        )
        if not has_handler:
            handler = logging.FileHandler(log_file, encoding="utf-8")
            handler.setFormatter(BeijingFormatter("%(asctime)s - %(levelname)s - %(message)s"))
            logger.addHandler(handler)
        logger.info("调试模式已启用")

    return logger
