"""
Rate Limiting 中間件
防止 API 濫用
"""

import logging
import time
from typing import Dict, Tuple
from collections import defaultdict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse

logger = logging.getLogger("middleware.rate_limit")


class RateLimiter:
    """
    簡易 Rate Limiter（記憶體實現）
    
    生產環境建議使用 Redis 實現
    """

    def __init__(
        self,
        requests_per_minute: int = 60,
        requests_per_hour: int = 1000,
    ):
        self.requests_per_minute = requests_per_minute
        self.requests_per_hour = requests_per_hour
        
        # 記錄請求：{ip: [(timestamp, count), ...]}
        self._minute_requests: Dict[str, list] = defaultdict(list)
        self._hour_requests: Dict[str, list] = defaultdict(list)

    def _cleanup_old_requests(self, requests: list, window_seconds: int) -> list:
        """清理過期的請求記錄"""
        current_time = time.time()
        return [
            (ts, count) for ts, count in requests
            if current_time - ts < window_seconds
        ]

    def is_allowed(self, client_ip: str) -> Tuple[bool, str]:
        """
        檢查請求是否被允許
        
        Returns:
            (is_allowed, reason)
        """
        current_time = time.time()

        # 清理過期記錄
        self._minute_requests[client_ip] = self._cleanup_old_requests(
            self._minute_requests[client_ip], 60
        )
        self._hour_requests[client_ip] = self._cleanup_old_requests(
            self._hour_requests[client_ip], 3600
        )

        # 計算當前窗口內的請求數
        minute_count = sum(count for _, count in self._minute_requests[client_ip])
        hour_count = sum(count for _, count in self._hour_requests[client_ip])

        # 檢查限制
        if minute_count >= self.requests_per_minute:
            return False, f"每分鐘請求數超過限制（{self.requests_per_minute}）"
        
        if hour_count >= self.requests_per_hour:
            return False, f"每小時請求數超過限制（{self.requests_per_hour}）"

        # 記錄請求
        self._minute_requests[client_ip].append((current_time, 1))
        self._hour_requests[client_ip].append((current_time, 1))

        return True, ""

    def get_remaining(self, client_ip: str) -> Dict[str, int]:
        """獲取剩餘請求數"""
        # 清理過期記錄
        self._minute_requests[client_ip] = self._cleanup_old_requests(
            self._minute_requests[client_ip], 60
        )
        self._hour_requests[client_ip] = self._cleanup_old_requests(
            self._hour_requests[client_ip], 3600
        )

        minute_count = sum(count for _, count in self._minute_requests[client_ip])
        hour_count = sum(count for _, count in self._hour_requests[client_ip])

        return {
            "minute_remaining": max(0, self.requests_per_minute - minute_count),
            "hour_remaining": max(0, self.requests_per_hour - hour_count),
        }


# 全局 Rate Limiter 實例
rate_limiter = RateLimiter(
    requests_per_minute=60,
    requests_per_hour=1000,
)


def get_client_ip(request: StarletteRequest) -> str:
    """獲取客戶端 IP"""
    # 優先取 X-Forwarded-For
    xff = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
    if xff:
        ip = xff.split(",")[0].strip()
        if ip:
            return ip
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate Limiting 中間件"""

    # 不需要限制的路徑
    EXEMPT_PATHS = {
        "/",
        "/health",
        "/static",
        "/login",
        "/favicon.ico",
    }

    async def dispatch(self, request: StarletteRequest, call_next):
        # 檢查是否豁免
        path = request.url.path
        if any(path.startswith(exempt) for exempt in self.EXEMPT_PATHS):
            return await call_next(request)

        # 獲取客戶端 IP
        client_ip = get_client_ip(request)

        # 檢查 Rate Limit
        is_allowed, reason = rate_limiter.is_allowed(client_ip)
        
        if not is_allowed:
            logger.warning(f"Rate limit exceeded for {client_ip}: {reason}")
            remaining = rate_limiter.get_remaining(client_ip)
            
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Too Many Requests",
                    "message": reason,
                    "retry_after": 60,  # 建議等待時間（秒）
                },
                headers={
                    "Retry-After": "60",
                    "X-RateLimit-Remaining-Minute": str(remaining["minute_remaining"]),
                    "X-RateLimit-Remaining-Hour": str(remaining["hour_remaining"]),
                }
            )

        # 繼續處理請求
        response = await call_next(request)

        # 添加 Rate Limit 頭
        remaining = rate_limiter.get_remaining(client_ip)
        response.headers["X-RateLimit-Remaining-Minute"] = str(remaining["minute_remaining"])
        response.headers["X-RateLimit-Remaining-Hour"] = str(remaining["hour_remaining"])

        return response
