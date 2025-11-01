"""
TDX 基礎工具類
提供 OAuth 認證、API 呼叫、快取等共用功能
"""

import os
import json
import logging
import aiohttp
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

from .base_tool import ExecutionError
from core.database.cache import db_cache

logger = logging.getLogger("mcp.tools.tdx")

TDX_BASE_URL = "https://tdx.transportdata.tw/api/basic/v2"
TDX_CLIENT_ID = os.getenv("TDX_CLIENT_ID", "")
TDX_CLIENT_SECRET = os.getenv("TDX_CLIENT_SECRET", "")


class TDXBaseAPI:
    """TDX API 基礎類別"""
    
    _token_cache: Dict[str, Any] = {}
    
    @classmethod
    async def get_access_token(cls) -> str:
        """獲取 TDX Access Token（快取 1 小時）"""
        # 檢查快取
        if cls._token_cache.get("token") and cls._token_cache.get("expires_at"):
            if datetime.now() < cls._token_cache["expires_at"]:
                return cls._token_cache["token"]
        
        if not TDX_CLIENT_ID or not TDX_CLIENT_SECRET:
            raise ExecutionError("未設定 TDX_CLIENT_ID 或 TDX_CLIENT_SECRET 環境變數")
        
        # 請求新 token
        auth_url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
        data = {
            "grant_type": "client_credentials",
            "client_id": TDX_CLIENT_ID,
            "client_secret": TDX_CLIENT_SECRET
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(auth_url, data=data, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        raise ExecutionError(f"TDX 認證失敗: HTTP {resp.status} - {error_text}")
                    
                    token_data = await resp.json()
                    access_token = token_data.get("access_token")
                    expires_in = token_data.get("expires_in", 3600)
                    
                    if not access_token:
                        raise ExecutionError("TDX 認證回應缺少 access_token")
                    
                    # 快取（提前 60 秒過期）
                    cls._token_cache = {
                        "token": access_token,
                        "expires_at": datetime.now() + timedelta(seconds=expires_in - 60)
                    }
                    
                    logger.info("✅ TDX Access Token 取得成功")
                    return access_token
        
        except aiohttp.ClientError as e:
            raise ExecutionError(f"TDX 認證網路錯誤: {e}")
    
    @classmethod
    async def call_api(cls, endpoint: str, params: Optional[Dict[str, Any]] = None, 
                      cache_ttl: int = 60) -> Any:
        """呼叫 TDX API 並處理快取"""
        access_token = await cls.get_access_token()
        
        url = f"{TDX_BASE_URL}/{endpoint}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json"
        }
        
        # 生成快取鍵
        cache_key = f"tdx:{endpoint}:{json.dumps(params or {}, sort_keys=True)}"
        
        # 檢查快取
        if cache_ttl > 0:
            cached = await db_cache.get_tdx_cached(cache_key)
            if cached:
                logger.debug(f"📦 TDX 快取命中: {endpoint}")
                return cached
        
        # 呼叫 API
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    if resp.status == 304:
                        logger.info("TDX 資料未變更 (304)")
                        return cached if cached else []
                    
                    if resp.status != 200:
                        error_text = await resp.text()
                        raise ExecutionError(f"TDX API 錯誤 {endpoint}: HTTP {resp.status} - {error_text[:200]}")
                    
                    data = await resp.json()
                    
                    # 快取結果
                    if cache_ttl > 0:
                        await db_cache.set_tdx_cache(cache_key, data, ttl=cache_ttl)
                    
                    logger.info(f"✅ TDX API 成功: {endpoint}")
                    return data
        
        except asyncio.TimeoutError:
            raise ExecutionError(f"TDX API 逾時: {endpoint}")
        except aiohttp.ClientError as e:
            raise ExecutionError(f"TDX API 網路錯誤: {e}")
    
    @staticmethod
    def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """計算兩點間距離（公尺）"""
        from math import radians, cos, sin, asin, sqrt
        
        R = 6371000  # 地球半徑（公尺）
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * asin(sqrt(a))
        
        return R * c
    
    @staticmethod
    def format_datetime(dt_str: str) -> str:
        """格式化 TDX 時間字串"""
        if not dt_str:
            return "未知"
        try:
            # TDX 格式: 2024-11-01T14:30:00+08:00
            dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
            return dt.strftime("%H:%M")
        except:
            return dt_str
