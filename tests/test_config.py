"""
測試 core/config.py 配置模組
"""

import pytest
from core.config import Settings


class TestSettings:
    """測試 Settings 類別"""

    def test_cors_origins_default(self):
        """測試 CORS 預設值"""
        origins = Settings.get_cors_origins()
        assert isinstance(origins, list)

    def test_constants_defined(self):
        """測試常數已定義"""
        assert hasattr(Settings, 'WEBSOCKET_SESSION_TIMEOUT')
        assert hasattr(Settings, 'CLEANUP_INTERVAL')
        assert hasattr(Settings, 'MEMORY_IMPORTANCE_THRESHOLD')
        assert hasattr(Settings, 'INTENT_CACHE_TTL')
        assert hasattr(Settings, 'CHAT_HISTORY_LIMIT')
        assert hasattr(Settings, 'CARE_MODE_HISTORY_LIMIT')

    def test_security_constants(self):
        """測試安全性常數"""
        assert hasattr(Settings, 'FAILED_LOGIN_THRESHOLD')
        assert hasattr(Settings, 'LOGIN_BLOCK_DURATION')
        assert hasattr(Settings, 'JWT_SECRET_MIN_LENGTH')
        assert Settings.JWT_SECRET_MIN_LENGTH >= 32

    def test_default_values(self):
        """測試預設值合理性"""
        assert Settings.WEBSOCKET_SESSION_TIMEOUT > 0
        assert Settings.CLEANUP_INTERVAL > 0
        assert 0 <= Settings.MEMORY_IMPORTANCE_THRESHOLD <= 1
        assert Settings.INTENT_CACHE_TTL > 0
