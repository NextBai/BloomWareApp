import os
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# 統一配置管理
from core.config import settings

# JWT 配置
SECRET_KEY = settings.JWT_SECRET_KEY or secrets.token_urlsafe(32)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES

# 密碼哈希配置
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 安全方案
security = HTTPBearer(auto_error=False)

class JWTAuth:
    def __init__(self):
        self.secret_key = SECRET_KEY
        self.algorithm = ALGORITHM
        self.access_token_expire_minutes = ACCESS_TOKEN_EXPIRE_MINUTES

    def create_access_token(self, data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
        """創建訪問令牌"""
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=self.access_token_expire_minutes)

        to_encode.update({"exp": expire, "iat": datetime.utcnow()})
        encoded_jwt = jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
        return encoded_jwt

    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """驗證JWT令牌"""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            
            # 檢查 token 是否過期
            exp = payload.get("exp")
            if exp:
                from datetime import datetime
                import time
                current_time = time.time()
                if current_time > exp:
                    import logging
                    logger = logging.getLogger("core.auth.jwt")
                    logger.warning(f"❌ Token 已過期: exp={exp}, current={current_time}, 差距={current_time - exp}秒")
                    return None
                    
            return payload
        except JWTError as e:
            import logging
            logger = logging.getLogger("core.auth.jwt")
            logger.warning(f"❌ JWT 驗證失敗: {e}")
            return None

    def get_current_user(self, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Optional[Dict[str, Any]]:
        """獲取當前用戶（從JWT令牌）"""
        if not credentials:
            return None

        payload = self.verify_token(credentials.credentials)
        if not payload:
            return None

        return payload

    def hash_password(self, password: str) -> str:
        """哈希密碼"""
        return pwd_context.hash(password)

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """驗證密碼"""
        return pwd_context.verify(plain_password, hashed_password)

# JWT認證實例
jwt_auth = JWTAuth()

def get_current_user_optional(request: Request) -> Optional[Dict[str, Any]]:
    """可選的用戶認證（不會拋出異常）"""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None

    token = auth_header.split(" ")[1]
    return jwt_auth.verify_token(token)

def require_auth(user: Optional[Dict[str, Any]] = Depends(get_current_user_optional)):
    """需要認證的依賴項"""
    if not user:
        raise HTTPException(status_code=401, detail="認證失敗")
    return user