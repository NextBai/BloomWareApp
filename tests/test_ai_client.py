"""
測試 core/ai_client.py OpenAI 客戶端管理
"""

import pytest
from unittest.mock import patch, MagicMock


class TestAIClient:
    """測試 AI 客戶端模組"""

    def test_get_openai_client_no_api_key(self):
        """測試無 API Key 時返回 None"""
        from core import ai_client
        ai_client.reset_client()

        with patch.object(ai_client, 'settings') as mock_settings:
            mock_settings.OPENAI_API_KEY = ""
            mock_settings.OPENAI_TIMEOUT = 30

            client = ai_client.get_openai_client()
            # 無 API Key 應返回 None
            assert client is None

    def test_reset_client(self):
        """測試重置客戶端"""
        from core import ai_client

        ai_client.reset_client()
        assert ai_client._initialized is False
        assert ai_client._openai_client is None

    def test_is_available_false(self):
        """測試服務不可用"""
        from core import ai_client
        ai_client.reset_client()

        with patch.object(ai_client, 'settings') as mock_settings:
            mock_settings.OPENAI_API_KEY = ""
            mock_settings.OPENAI_TIMEOUT = 30

            assert ai_client.is_available() is False
