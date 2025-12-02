"""
測試 models/schemas.py Pydantic 模型
"""

import pytest
from datetime import datetime
from pydantic import ValidationError as PydanticValidationError

from models.schemas import (
    UserCreate,
    UserLogin,
    ChatCreateRequest,
    MessageCreateRequest,
    FileAnalysisRequest,
    SpeakerLabelBindRequest,
)


class TestUserSchemas:
    """測試用戶相關模型"""

    def test_user_create_valid(self):
        """測試有效的用戶建立請求"""
        user = UserCreate(
            name="測試用戶",
            email="test@example.com",
            password="password123"
        )
        assert user.name == "測試用戶"
        assert user.email == "test@example.com"

    def test_user_create_invalid_email(self):
        """測試無效的 email"""
        with pytest.raises(PydanticValidationError):
            UserCreate(
                name="測試",
                email="invalid-email",
                password="password123"
            )

    def test_user_create_short_password(self):
        """測試過短的密碼"""
        with pytest.raises(PydanticValidationError):
            UserCreate(
                name="測試",
                email="test@example.com",
                password="12345"  # 少於 6 字元
            )

    def test_user_login_valid(self):
        """測試有效的登入請求"""
        login = UserLogin(
            email="test@example.com",
            password="password123"
        )
        assert login.email == "test@example.com"


class TestChatSchemas:
    """測試對話相關模型"""

    def test_chat_create_request(self):
        """測試建立對話請求"""
        chat = ChatCreateRequest(user_id="user123")
        assert chat.user_id == "user123"
        assert chat.title == "新對話"  # 預設值

    def test_chat_create_with_title(self):
        """測試帶標題的建立對話請求"""
        chat = ChatCreateRequest(user_id="user123", title="我的對話")
        assert chat.title == "我的對話"

    def test_message_create_request(self):
        """測試建立訊息請求"""
        msg = MessageCreateRequest(sender="user", content="你好")
        assert msg.sender == "user"
        assert msg.content == "你好"


class TestFileSchemas:
    """測試檔案相關模型"""

    def test_file_analysis_request(self):
        """測試檔案分析請求"""
        req = FileAnalysisRequest(
            filename="test.txt",
            content="SGVsbG8gV29ybGQ=",
            mime_type="text/plain"
        )
        assert req.filename == "test.txt"
        assert req.user_prompt == "請分析這個檔案的內容"  # 預設值


class TestVoiceSchemas:
    """測試語音相關模型"""

    def test_speaker_label_bind_request(self):
        """測試語音標籤綁定請求"""
        req = SpeakerLabelBindRequest(speaker_label="speaker_001")
        assert req.speaker_label == "speaker_001"
