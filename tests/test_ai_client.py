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
            mock_settings.OPENAI_BASE_URL = ""
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
            mock_settings.OPENAI_BASE_URL = ""
            mock_settings.OPENAI_TIMEOUT = 30

            assert ai_client.is_available() is False

    def test_get_openai_client_passes_base_url(self):
        """測試有設定 base_url 時會傳入 OpenAI client"""
        from core import ai_client
        ai_client.reset_client()

        fake_client = MagicMock()

        with patch.object(ai_client, 'settings') as mock_settings:
            mock_settings.OPENAI_API_KEY = "sk-test"
            mock_settings.OPENAI_BASE_URL = "https://sub2api.flowatelier.com/v1"
            mock_settings.OPENAI_TIMEOUT = 30

            with patch("openai.OpenAI", return_value=fake_client) as mock_openai:
                client = ai_client.get_openai_client()

        assert client is fake_client
        mock_openai.assert_called_once_with(
            api_key="sk-test",
            base_url="https://sub2api.flowatelier.com/v1",
            timeout=30.0,
            max_retries=3,
        )

    def test_get_openai_client_normalizes_base_url_without_v1(self):
        """測試 base_url 可用裸網域設定，client factory 會補 /v1"""
        from core import ai_client
        ai_client.reset_client()

        fake_client = MagicMock()

        with patch.object(ai_client, 'settings') as mock_settings:
            mock_settings.OPENAI_API_KEY = "sk-test"
            mock_settings.OPENAI_BASE_URL = "https://sub2api.flowatelier.com"
            mock_settings.OPENAI_TIMEOUT = 30

            with patch("openai.OpenAI", return_value=fake_client) as mock_openai:
                client = ai_client.get_openai_client()

        assert client is fake_client
        mock_openai.assert_called_once_with(
            api_key="sk-test",
            base_url="https://sub2api.flowatelier.com/v1",
            timeout=30.0,
            max_retries=3,
        )

    def test_get_openai_client_omits_base_url_when_unset(self):
        """測試未設定 base_url 時沿用 SDK 預設 OpenAI endpoint"""
        from core import ai_client
        ai_client.reset_client()

        fake_client = MagicMock()

        with patch.object(ai_client, 'settings') as mock_settings:
            mock_settings.OPENAI_API_KEY = "sk-test"
            mock_settings.OPENAI_BASE_URL = ""
            mock_settings.OPENAI_TIMEOUT = 30

            with patch("openai.OpenAI", return_value=fake_client) as mock_openai:
                client = ai_client.get_openai_client()

        assert client is fake_client
        mock_openai.assert_called_once_with(
            api_key="sk-test",
            timeout=30.0,
            max_retries=3,
        )
