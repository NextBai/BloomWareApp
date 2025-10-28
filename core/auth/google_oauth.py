"""
Google OAuth 2.0 Authorization Code Flow with PKCE
實現安全的Google登入流程，包含PKCE保護機制
"""

import os
import secrets
import hashlib
import base64
import json
import logging
from typing import Optional, Dict, Any
from urllib.parse import urlencode, urlparse, parse_qs
import httpx
from fastapi import HTTPException
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest

# 統一配置管理
from core.config import settings

logger = logging.getLogger("GoogleOAuth")


class GoogleOAuthManager:
    """Google OAuth 2.0 管理器，實現Authorization Code Flow + PKCE"""

    def __init__(self):
        self.client_id = settings.GOOGLE_CLIENT_ID
        self.client_secret = settings.GOOGLE_CLIENT_SECRET
        # 默認使用配置中的值，但可以在調用時動態覆蓋
        self.redirect_uri = settings.GOOGLE_REDIRECT_URI

        if not self.client_id or not self.client_secret:
            raise ValueError("GOOGLE_CLIENT_ID 和 GOOGLE_CLIENT_SECRET 環境變數必須設置")

        # Google OAuth 2.0 端點
        self.auth_url = "https://accounts.google.com/o/oauth2/v2/auth"
        self.token_url = "https://oauth2.googleapis.com/token"
        self.userinfo_url = "https://www.googleapis.com/oauth2/v2/userinfo"
        self.revoke_url = "https://oauth2.googleapis.com/revoke"

    def generate_pkce_pair(self) -> Dict[str, str]:
        """生成PKCE code_verifier 和 code_challenge"""
        # 生成code_verifier (43-128字符)
        code_verifier = secrets.token_urlsafe(64)

        # 生成code_challenge (SHA256 hash of code_verifier, base64url encoded)
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).decode().rstrip('=')

        return {
            "code_verifier": code_verifier,
            "code_challenge": code_challenge
        }

    def get_authorization_url(self, state: str = None, code_challenge: str = None) -> str:
        """生成授權URL"""
        if not code_challenge:
            pkce_pair = self.generate_pkce_pair()
            code_challenge = pkce_pair["code_challenge"]

        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": "openid email profile",
            "response_type": "code",
            "access_type": "offline",  # 請求refresh token
            "prompt": "consent",  # 強制顯示同意畫面
            "code_challenge": code_challenge,
            "code_challenge_method": "S256"
        }

        if state:
            params["state"] = state

        return f"{self.auth_url}?{urlencode(params)}"

    async def exchange_code_for_tokens(self, code: str, code_verifier: str) -> Dict[str, Any]:
        """交換authorization code為access token"""
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri,
            "code_verifier": code_verifier
        }

        logger.info(f"🔑 Token 交換請求: redirect_uri={self.redirect_uri}")

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.token_url,
                    data=data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"}
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                # 記錄 Google 返回的詳細錯誤
                error_detail = e.response.text
                logger.error(f"❌ Google Token 交換失敗: status={e.response.status_code}, detail={error_detail}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Token exchange failed: {error_detail}"
                )
            except httpx.HTTPError as e:
                logger.error(f"❌ HTTP 錯誤: {str(e)}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Token exchange failed: {str(e)}"
                )

    async def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """獲取用戶信息"""
        headers = {"Authorization": f"Bearer {access_token}"}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(self.userinfo_url, headers=headers)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to get user info: {str(e)}"
                )

    async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        """刷新access token"""
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.token_url,
                    data=data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"}
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Token refresh failed: {str(e)}"
                )

    async def revoke_token(self, token: str) -> bool:
        """撤銷token"""
        data = {
            "token": token,
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.revoke_url,
                    data=data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"}
                )
                return response.status_code == 200
            except httpx.HTTPError:
                return False

    def validate_state(self, received_state: str, expected_state: str) -> bool:
        """驗證state參數防止CSRF攻擊"""
        return received_state == expected_state

    def create_credentials(self, token_data: Dict[str, Any]) -> Credentials:
        """創建Google Credentials對象"""
        return Credentials(
            token=token_data.get("access_token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri=self.token_url,
            client_id=self.client_id,
            client_secret=self.client_secret,
            scopes=["openid", "email", "profile"]
        )


# 全局OAuth管理器實例
oauth_manager = GoogleOAuthManager()