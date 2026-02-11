"""
Logging configuration for the trading bot.
"""
import logging
import os
from datetime import datetime

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)


def setup_logger(name: str = "iron_condor_bot", level: str = "INFO") -> logging.Logger:
    """Create and configure logger with file and console handlers."""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))

    if logger.handlers:
        return logger

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console_fmt = logging.Formatter("%(asctime)s │ %(levelname)-7s │ %(message)s", datefmt="%H:%M:%S")
    console.setFormatter(console_fmt)
    logger.addHandler(console)

    # File handler (daily rotation)
    log_file = os.path.join(LOG_DIR, f"bot_{datetime.now().strftime('%Y%m%d')}.log")
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter(
        "%(asctime)s │ %(levelname)-7s │ %(name)s │ %(funcName)s:%(lineno)d │ %(message)s"
    )
    file_handler.setFormatter(file_fmt)
    logger.addHandler(file_handler)

    # Trade-specific log
    trade_file = os.path.join(LOG_DIR, "trades.log")
    trade_handler = logging.FileHandler(trade_file)
    trade_handler.setLevel(logging.INFO)
    trade_handler.setFormatter(file_fmt)
    trade_logger = logging.getLogger(f"{name}.trades")
    trade_logger.addHandler(trade_handler)

    return logger


log = setup_logger()
trade_log = logging.getLogger("iron_condor_bot.trades")
