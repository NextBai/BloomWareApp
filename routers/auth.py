"""
認證相關 API 路由
包含 Google OAuth、JWT 認證等
"""

import logging
from datetime import datetime
from typing import Dict, Optional
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, EmailStr

from core.config import settings
from core.auth import jwt_auth, get_current_user_optional, require_auth
from core.auth.google_oauth import GoogleOAuth
from core.database import create_or_login_google_user

logger = logging.getLogger("routers.auth")

router = APIRouter(prefix="/auth", tags=["認證"])

# Google OAuth 實例
google_oauth = GoogleOAuth()


class GoogleAuthRequest(BaseModel):
    """Google 認證請求"""
    credential: str


class TokenResponse(BaseModel):
    """Token 響應"""
    success: bool
    token: Optional[str] = None
    user: Optional[dict] = None
    error: Optional[str] = None


@router.get("/google/login")
async def google_login():
    """
    Google OAuth 登入入口
    重定向到 Google 授權頁面
    """
    auth_url = google_oauth.get_authorization_url()
    return RedirectResponse(url=auth_url)


@router.get("/google/callback")
async def google_callback(code: str = None, error: str = None):
    """
    Google OAuth 回調處理
    """
    if error:
        logger.error(f"Google OAuth 錯誤: {error}")
        return RedirectResponse(url=f"/login?error={error}")

    if not code:
        logger.error("Google OAuth 回調缺少 code 參數")
        return RedirectResponse(url="/login?error=missing_code")

    try:
        # 交換 code 獲取 token
        token_info = await google_oauth.exchange_code(code)
        if not token_info:
            return RedirectResponse(url="/login?error=token_exchange_failed")

        # 獲取用戶信息
        user_info = await google_oauth.get_user_info(token_info.get("access_token"))
        if not user_info:
            return RedirectResponse(url="/login?error=user_info_failed")

        # 創建或登入用戶
        result = await create_or_login_google_user(user_info)
        if not result.get("success"):
            error_msg = result.get("error", "unknown_error")
            return RedirectResponse(url=f"/login?error={error_msg}")

        # 生成 JWT token
        user = result.get("user", {})
        jwt_token = jwt_auth.create_access_token({
            "sub": user.get("id"),
            "email": user.get("email"),
            "name": user.get("name"),
        })

        # 重定向到前端，帶上 token
        return RedirectResponse(url=f"/static/frontend/index.html?token={jwt_token}")

    except Exception as e:
        logger.exception(f"Google OAuth 回調處理失敗: {e}")
        return RedirectResponse(url=f"/login?error=callback_failed")


@router.post("/google/verify", response_model=TokenResponse)
async def google_verify(request: GoogleAuthRequest):
    """
    驗證 Google ID Token（前端 One Tap 登入）
    """
    try:
        # 驗證 Google credential
        user_info = await google_oauth.verify_id_token(request.credential)
        if not user_info:
            return TokenResponse(success=False, error="invalid_credential")

        # 創建或登入用戶
        result = await create_or_login_google_user(user_info)
        if not result.get("success"):
            return TokenResponse(success=False, error=result.get("error"))

        # 生成 JWT token
        user = result.get("user", {})
        jwt_token = jwt_auth.create_access_token({
            "sub": user.get("id"),
            "email": user.get("email"),
            "name": user.get("name"),
        })

        return TokenResponse(
            success=True,
            token=jwt_token,
            user=user,
        )

    except Exception as e:
        logger.exception(f"Google 驗證失敗: {e}")
        return TokenResponse(success=False, error=str(e))


@router.get("/me")
async def get_current_user(user: dict = Depends(require_auth)):
    """
    獲取當前登入用戶信息
    """
    return {
        "success": True,
        "user": {
            "id": user.get("sub"),
            "email": user.get("email"),
            "name": user.get("name"),
        }
    }


@router.post("/refresh")
async def refresh_token(user: dict = Depends(require_auth)):
    """
    刷新 JWT Token
    """
    new_token = jwt_auth.create_access_token({
        "sub": user.get("sub"),
        "email": user.get("email"),
        "name": user.get("name"),
    })

    return {
        "success": True,
        "token": new_token,
    }
