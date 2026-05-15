"""
TDX 基礎工具類
提供 OAuth 認證、API 呼叫、快取等共用功能

TDX API 文件: https://tdx.transportdata.tw/api-service/swagger

API 版本說明：
- v2: 公車(Bus)、自行車(Bike)、停車場(Parking)、高鐵(THSR)、捷運(Metro)
- v3: 台鐵(TRA)

正確端點範例：
- 公車: /v2/Bus/EstimatedTimeOfArrival/City/{City}/{RouteName}
- 公車站: /v2/Bus/Stop/City/{City}
- 自行車站: /v2/Bike/Station/City/{City}
- 自行車即時: /v2/Bike/Availability/City/{City}
- 停車場: /v2/Parking/OffStreet/CarPark/City/{City}
- 高鐵時刻: /v2/Rail/THSR/DailyTimetable/TrainDates/{TrainDate}
- 高鐵車站: /v2/Rail/THSR/Station
- 捷運車站: /v2/Rail/Metro/Station/{Operator}
- 捷運即時: /v2/Rail/Metro/LiveBoard/{Operator}
- 台鐵時刻: /v3/Rail/TRA/DailyTrainTimetable/Today
- 台鐵車站: /v3/Rail/TRA/Station

OData 查詢參數：
- $select: 選擇欄位
- $filter: 過濾條件
- $orderby: 排序
- $top: 取前 N 筆
- $skip: 跳過 N 筆
- $spatialFilter: 空間過濾 nearby(lat, lon, distance_m)
- $format: 回傳格式 (JSON)
"""

import os
import json
import logging
import aiohttp
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

from ..base_tool import ExecutionError
from core.database.cache import db_cache

logger = logging.getLogger("mcp.tools.tdx")

TDX_BASE_URLS = {
    "basic": "https://tdx.transportdata.tw/api/basic",
    "advanced": "https://tdx.transportdata.tw/api/advanced",
    "historical": "https://tdx.transportdata.tw/api/historical",
}

# 從環境變數讀取（需要在 app.py 中先 load_dotenv）
TDX_CLIENT_ID = os.getenv("TDX_CLIENT_ID", "")
TDX_CLIENT_SECRET = os.getenv("TDX_CLIENT_SECRET", "")


class TDXBaseAPI:
    """TDX API 基礎類別"""
    
    _token_cache: Dict[str, Any] = {}
    
    @classmethod
    async def get_access_token(cls) -> str:
        """獲取 TDX Access Token（快取至過期前 60 秒）"""
        # 檢查快取
        if cls._token_cache.get("token") and cls._token_cache.get("expires_at"):
            if datetime.now() < cls._token_cache["expires_at"]:
                return cls._token_cache["token"]
        
        # 重新讀取環境變數（確保 load_dotenv 後能取得）
        client_id = os.getenv("TDX_CLIENT_ID", "") or TDX_CLIENT_ID
        client_secret = os.getenv("TDX_CLIENT_SECRET", "") or TDX_CLIENT_SECRET
        
        if not client_id or not client_secret:
            raise ExecutionError("未設定 TDX_CLIENT_ID 或 TDX_CLIENT_SECRET 環境變數")
        
        # 請求新 token
        auth_url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
        data = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret
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
    async def call_api(
        cls, 
        endpoint: str, 
        params: Optional[Dict[str, Any]] = None, 
        cache_ttl: int = 60,
        api_version: str = "v2",
        api_family: str = "basic",
    ) -> Any:
        """
        呼叫 TDX API 並處理快取
        
        Args:
            endpoint: API 端點路徑（不含版本號，如 "Bus/Route/City/Taipei"）
            params: OData 查詢參數
            cache_ttl: 快取時間（秒），0 表示不快取
            api_version: API 版本（v2 或 v3）
        
        Returns:
            API 回應資料（通常是 list 或 dict）
        """
        access_token = await cls.get_access_token()
        
        # 組合完整 URL
        base_url = TDX_BASE_URLS.get(api_family, TDX_BASE_URLS["basic"])
        version_segment = f"/{api_version.strip('/')}" if api_version else ""
        endpoint_segment = endpoint.lstrip("/")
        url = f"{base_url}{version_segment}/{endpoint_segment}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json"
        }
        
        # 確保有 $format 參數
        if params is None:
            params = {}
        if "$format" not in params:
            params["$format"] = "JSON"
        
        # 生成快取鍵
        cache_key = f"tdx:{api_family}:{api_version}:{endpoint}:{json.dumps(params, sort_keys=True)}"
        
        # 檢查快取
        if cache_ttl > 0:
            cached = await db_cache.get_tdx_cached(cache_key)
            if cached is not None:
                logger.debug(f"📦 TDX 快取命中: {endpoint}")
                return cached
        
        # 呼叫 API
        logger.info(f"🌐 TDX API 請求: {url}")
        logger.info(f"   參數: {params}")
        
        retry_delays = [0.8, 1.6, 3.2]
        last_error: Optional[ExecutionError] = None

        for attempt, delay in enumerate([0.0] + retry_delays, start=1):
            if delay > 0:
                await asyncio.sleep(delay)
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        url, 
                        headers=headers,
                        params=params, 
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as resp:
                        response_text = await resp.text()

                # 記錄完整回應（用於除錯）
                logger.info(f"📥 TDX API 回應: HTTP {resp.status}")
                if resp.status != 200:
                    logger.error(f"❌ TDX API 錯誤回應:")
                    logger.error(f"   URL: {url}")
                    logger.error(f"   參數: {params}")
                    logger.error(f"   狀態碼: {resp.status}")
                    logger.error(f"   回應內容: {response_text[:1000]}")

                if resp.status == 304:
                    logger.info("TDX 資料未變更 (304)")
                    return cached if cache_ttl > 0 and 'cached' in locals() and cached else []

                if resp.status == 401:
                    cls._token_cache = {}
                    error_msg = f"TDX Token 已過期，請重試\n[API] {url}\n[回應] {response_text[:500]}"
                    raise ExecutionError(error_msg)

                if resp.status == 429:
                    error_msg = f"TDX API 速率限制: HTTP 429\n[API] {url}\n[參數] {params}\n[回應] {response_text[:500]}"
                    logger.error(error_msg)
                    last_error = ExecutionError(error_msg)
                    if attempt <= len(retry_delays):
                        logger.warning("⏳ TDX API 429，準備第 %s 次重試: %s", attempt, url)
                        continue
                    raise last_error

                if resp.status == 404:
                    error_msg = f"TDX API 找不到資源 (404)\n[API] {url}\n[參數] {params}\n[回應] {response_text[:500]}"
                    logger.error(error_msg)
                    raise ExecutionError(error_msg)

                if resp.status != 200:
                    error_msg = f"TDX API 錯誤: HTTP {resp.status}\n[API] {url}\n[參數] {params}\n[回應] {response_text[:500]}"
                    logger.error(error_msg)
                    raise ExecutionError(error_msg)

                try:
                    data = json.loads(response_text)
                except json.JSONDecodeError:
                    error_msg = f"TDX API 回應非 JSON 格式\n[API] {url}\n[回應] {response_text[:500]}"
                    raise ExecutionError(error_msg)

                data_count = len(data) if isinstance(data, list) else 1
                logger.info(f"✅ TDX API 成功: {endpoint} (共 {data_count} 筆)")

                if isinstance(data, list) and len(data) == 0:
                    logger.warning(f"⚠️ TDX API 回應空陣列: {url}")

                if cache_ttl > 0 and data:
                    await db_cache.set_tdx_cache(cache_key, data, ttl=cache_ttl)

                return data
            except asyncio.TimeoutError:
                error_msg = f"TDX API 逾時\n[API] {url}\n[參數] {params}"
                logger.error(error_msg)
                raise ExecutionError(error_msg)
            except aiohttp.ClientError as e:
                error_msg = f"TDX API 網路錯誤: {e}\n[API] {url}"
                logger.error(error_msg)
                raise ExecutionError(error_msg)

        if last_error:
            raise last_error
        raise ExecutionError(f"TDX API 未知錯誤\n[API] {url}")
    
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
        """格式化 TDX 時間字串為 HH:MM"""
        if not dt_str:
            return "未知"
        try:
            # TDX 格式: 2024-11-01T14:30:00+08:00 或 14:30:00
            if "T" in dt_str:
                dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
                return dt.strftime("%H:%M")
            elif ":" in dt_str:
                return dt_str[:5]
            return dt_str
        except:
            return dt_str
    
    @staticmethod
    def get_today_date() -> str:
        """取得今日日期字串 (YYYY-MM-DD)"""
        return datetime.now().strftime("%Y-%m-%d")
