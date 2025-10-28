"""
認證模組 - JWT 令牌管理 + Google OAuth 認證

結構：
- jwt.py: JWT 令牌生成、驗證、FastAPI 依賴注入
- google_oauth.py: Google OAuth 2.0 認證流程管理
"""

from .jwt import JWTAuth, get_current_user_optional, require_auth
from .google_oauth import GoogleOAuthManager

# 全局實例
jwt_auth = JWTAuth()
google_oauth = GoogleOAuthManager()

__all__ = [
    # JWT 認證
    "JWTAuth",
    "jwt_auth",
    "get_current_user_optional",
    "require_auth",

    # Google OAuth
    "GoogleOAuthManager",
    "google_oauth",
]
