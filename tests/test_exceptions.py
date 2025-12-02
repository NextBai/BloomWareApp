"""
測試 core/exceptions.py 異常處理
"""

import pytest
from core.exceptions import (
    BloomWareException,
    AuthenticationError,
    TokenExpiredError,
    InvalidTokenError,
    ResourceNotFoundError,
    ChatNotFoundError,
    UserNotFoundError,
    ValidationError,
    create_error_response,
)


class TestExceptions:
    """測試異常類別"""

    def test_bloomware_exception(self):
        """測試基礎異常"""
        exc = BloomWareException("測試錯誤", code="TEST_ERROR", status_code=400)
        assert exc.message == "測試錯誤"
        assert exc.code == "TEST_ERROR"
        assert exc.status_code == 400

    def test_exception_to_dict(self):
        """測試異常轉字典"""
        exc = BloomWareException("測試", code="TEST")
        result = exc.to_dict()

        assert result["success"] is False
        assert result["error"]["code"] == "TEST"
        assert result["error"]["message"] == "測試"

    def test_authentication_error(self):
        """測試認證錯誤"""
        exc = AuthenticationError()
        assert exc.status_code == 401
        assert exc.code == "AUTHENTICATION_ERROR"

    def test_token_expired_error(self):
        """測試 Token 過期錯誤"""
        exc = TokenExpiredError()
        assert exc.status_code == 401
        assert "過期" in exc.message

    def test_invalid_token_error(self):
        """測試無效 Token 錯誤"""
        exc = InvalidTokenError()
        assert exc.status_code == 401

    def test_resource_not_found_error(self):
        """測試資源不存在錯誤"""
        exc = ResourceNotFoundError("用戶", "user123")
        assert exc.status_code == 404
        assert "用戶" in exc.message

    def test_chat_not_found_error(self):
        """測試對話不存在錯誤"""
        exc = ChatNotFoundError("chat123")
        assert exc.status_code == 404
        assert exc.details["resource_id"] == "chat123"

    def test_user_not_found_error(self):
        """測試用戶不存在錯誤"""
        exc = UserNotFoundError("user123")
        assert exc.status_code == 404

    def test_validation_error(self):
        """測試驗證錯誤"""
        exc = ValidationError("email", "格式不正確")
        assert exc.status_code == 400
        assert "email" in exc.message

    def test_create_error_response(self):
        """測試建立錯誤回應"""
        response = create_error_response(
            code="TEST",
            message="測試訊息",
            status_code=400
        )
        assert response.status_code == 400
