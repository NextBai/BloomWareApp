"""
測試 core/logging.py 日誌配置
"""

import pytest
import logging


class TestLogging:
    """測試日誌模組"""

    def test_get_logger(self):
        """測試取得 logger"""
        from core.logging import get_logger

        logger = get_logger("test_module")
        assert logger is not None
        assert logger.name == "test_module"

    def test_get_log_level(self):
        """測試取得日誌等級"""
        from core.logging import get_log_level

        level = get_log_level()
        assert isinstance(level, int)
        assert level in [
            logging.DEBUG,
            logging.INFO,
            logging.WARNING,
            logging.ERROR,
            logging.CRITICAL
        ]

    def test_get_level_name(self):
        """測試取得日誌等級名稱"""
        from core.logging import get_level_name

        name = get_level_name()
        assert isinstance(name, str)
        assert name in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

    def test_setup_logging(self):
        """測試設置日誌"""
        from core.logging import setup_logging

        logger = setup_logging("test_setup")
        assert logger is not None
        assert len(logger.handlers) > 0
