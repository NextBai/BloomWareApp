"""
統一日誌配置
集中管理所有模組的日誌設定

使用方式：
    from core.logging import get_logger
    logger = get_logger(__name__)
"""

import os
import logging
from typing import Optional

# 全域日誌等級（只讀取一次）
_LOG_LEVEL_NAME = os.getenv("BLOOMWARE_LOG_LEVEL", "WARNING").upper()
_LOG_LEVEL = getattr(logging, _LOG_LEVEL_NAME, logging.WARNING)

# 日誌格式
_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def get_log_level() -> int:
    """獲取日誌等級"""
    return _LOG_LEVEL


def setup_logging(
    name: Optional[str] = None,
    level: Optional[int] = None,
) -> logging.Logger:
    """
    設置日誌配置
    
    Args:
        name: 日誌名稱（None 表示 root logger）
        level: 日誌等級（None 表示使用環境變數）
    
    Returns:
        配置好的 Logger 實例
    """
    if level is None:
        level = _LOG_LEVEL

    # 配置格式
    formatter = logging.Formatter(_LOG_FORMAT)

    # 獲取或創建 logger
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # 避免重複添加 handler
    if not logger.handlers:
        # 控制台 handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # 防止日誌重複輸出
    logger.propagate = False

    return logger


def get_logger(name: str) -> logging.Logger:
    """
    獲取已配置的 Logger（推薦使用）
    
    Args:
        name: 日誌名稱，建議使用 __name__
    
    Returns:
        Logger 實例
    
    Example:
        from core.logging import get_logger
        logger = get_logger(__name__)
        logger.info("Hello")
    """
    return setup_logging(name)


def get_level_name() -> str:
    """獲取當前日誌等級名稱"""
    return _LOG_LEVEL_NAME


# 預設配置 root logger
_root_configured = False

def configure_root_logger():
    """配置 root logger（只執行一次）"""
    global _root_configured
    if not _root_configured:
        level = get_log_level()
        logging.basicConfig(
            level=level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler()]
        )
        _root_configured = True


# 自動配置
configure_root_logger()
