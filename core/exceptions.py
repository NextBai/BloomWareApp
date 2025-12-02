"""
統一異常處理
定義自訂異常類別和錯誤響應格式
"""

from typing import Optional, Dict, Any
from fastapi import HTTPException
from fastapi.responses import JSONResponse


class BloomWareException(Exception):
    """Bloom Ware 基礎異常類別"""

    def __init__(
        self,
        message: str,
        code: str = "UNKNOWN_ERROR",
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)

    def to_dict(self) -> Dict[str, Any]:
        """轉換為字典格式"""
        return {
            "success": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }

    def to_response(self) -> JSONResponse:
        """轉換為 JSON 響應"""
        return JSONResponse(
            status_code=self.status_code,
            content=self.to_dict(),
        )


# ==================== 認證相關異常 ====================

class AuthenticationError(BloomWareException):
    """認證錯誤"""

    def __init__(self, message: str = "認證失敗", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="AUTHENTICATION_ERROR",
            status_code=401,
            details=details,
        )


class TokenExpiredError(AuthenticationError):
    """Token 過期"""

    def __init__(self):
        super().__init__(
            message="Token 已過期，請重新登入",
            details={"reason": "token_expired"},
        )


class InvalidTokenError(AuthenticationError):
    """無效的 Token"""

    def __init__(self):
        super().__init__(
            message="無效的認證令牌",
            details={"reason": "invalid_token"},
        )


class PermissionDeniedError(BloomWareException):
    """權限不足"""

    def __init__(self, message: str = "權限不足"):
        super().__init__(
            message=message,
            code="PERMISSION_DENIED",
            status_code=403,
        )


# ==================== 資源相關異常 ====================

class ResourceNotFoundError(BloomWareException):
    """資源不存在"""

    def __init__(self, resource_type: str, resource_id: str):
        super().__init__(
            message=f"{resource_type} 不存在",
            code="RESOURCE_NOT_FOUND",
            status_code=404,
            details={
                "resource_type": resource_type,
                "resource_id": resource_id,
            },
        )


class ChatNotFoundError(ResourceNotFoundError):
    """對話不存在"""

    def __init__(self, chat_id: str):
        super().__init__("對話", chat_id)


class UserNotFoundError(ResourceNotFoundError):
    """用戶不存在"""

    def __init__(self, user_id: str):
        super().__init__("用戶", user_id)


# ==================== 驗證相關異常 ====================

class ValidationError(BloomWareException):
    """驗證錯誤"""

    def __init__(self, field: str, message: str):
        super().__init__(
            message=f"參數 '{field}' 驗證失敗: {message}",
            code="VALIDATION_ERROR",
            status_code=400,
            details={"field": field},
        )


class RateLimitExceededError(BloomWareException):
    """請求頻率超限"""

    def __init__(self, retry_after: int = 60):
        super().__init__(
            message="請求頻率超過限制，請稍後再試",
            code="RATE_LIMIT_EXCEEDED",
            status_code=429,
            details={"retry_after": retry_after},
        )


# ==================== 服務相關異常 ====================

class ServiceUnavailableError(BloomWareException):
    """服務不可用"""

    def __init__(self, service_name: str):
        super().__init__(
            message=f"{service_name} 服務暫時不可用",
            code="SERVICE_UNAVAILABLE",
            status_code=503,
            details={"service": service_name},
        )


class DatabaseError(BloomWareException):
    """數據庫錯誤"""

    def __init__(self, message: str = "數據庫操作失敗"):
        super().__init__(
            message=message,
            code="DATABASE_ERROR",
            status_code=500,
        )


class AIServiceError(BloomWareException):
    """AI 服務錯誤"""

    def __init__(self, message: str = "AI 服務暫時不可用"):
        super().__init__(
            message=message,
            code="AI_SERVICE_ERROR",
            status_code=503,
        )


class ExternalAPIError(BloomWareException):
    """外部 API 錯誤"""

    def __init__(self, api_name: str, message: str):
        super().__init__(
            message=f"{api_name} API 錯誤: {message}",
            code="EXTERNAL_API_ERROR",
            status_code=502,
            details={"api": api_name},
        )


# ==================== 語音相關異常 ====================

class VoiceAuthError(BloomWareException):
    """語音認證錯誤"""

    def __init__(self, message: str, reason: str):
        super().__init__(
            message=message,
            code="VOICE_AUTH_ERROR",
            status_code=400,
            details={"reason": reason},
        )


class SpeakerLabelTakenError(VoiceAuthError):
    """語音標籤已被使用"""

    def __init__(self):
        super().__init__(
            message="此語音標籤已被其他用戶綁定",
            reason="speaker_label_taken",
        )


# ==================== 異常處理器 ====================

def create_error_response(
    code: str,
    message: str,
    status_code: int = 500,
    details: Optional[Dict[str, Any]] = None,
) -> JSONResponse:
    """創建標準錯誤響應"""
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
            }
        }
    )


def handle_exception(exc: Exception) -> JSONResponse:
    """
    統一異常處理
    
    將各種異常轉換為標準 JSON 響應
    """
    if isinstance(exc, BloomWareException):
        return exc.to_response()
    
    if isinstance(exc, HTTPException):
        return create_error_response(
            code="HTTP_ERROR",
            message=exc.detail,
            status_code=exc.status_code,
        )
    
    # 未知異常
    import logging
    logger = logging.getLogger("core.exceptions")
    logger.exception(f"未處理的異常: {exc}")
    
    return create_error_response(
        code="INTERNAL_ERROR",
        message="內部伺服器錯誤",
        status_code=500,
    )
