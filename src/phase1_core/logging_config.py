"""
logging_config.py — 统一日志配置
墨家投资室 · logs_archiver 依赖
创建时间：2026-05-17

提供 setup_logger / setup_root_logger 供各模块使用。
"""

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path(r"C:\Users\17699\mo_zhi_sharereports\logs")


def setup_root_logger(log_file: str = "automation.log", level: int = logging.INFO) -> logging.Logger:
    """
    配置根日志记录器。
    
    Args:
        log_file: 日志文件名（相对 LOG_DIR）
        level: 日志级别
    
    Returns:
        根 logger
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / log_file

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S %z",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 清除已有的 handlers，避免重复
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)

    # 文件 handler
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # 控制台 handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    root_logger.info(f"Root logger initialized → {log_path}")
    return root_logger


def setup_logger(name: str, log_file: str, level: int = logging.INFO) -> logging.Logger:
    """
    配置一个具名日志记录器，写入指定的日志文件。
    同时也会输出到控制台。

    Args:
        name: logger 名称
        log_file: 日志文件名（相对 LOG_DIR）
        level: 日志级别

    Returns:
        配置好的 logger 实例
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / log_file

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # 只添加 handler（如果还没有）
    if not logger.handlers:
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S %z",
        )

        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger
