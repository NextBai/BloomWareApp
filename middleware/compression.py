"""
回應壓縮中間件
使用 gzip 壓縮 API 回應，減少傳輸大小
"""

import gzip
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from core.logging import get_logger

logger = get_logger("middleware.compression")

# 最小壓縮大小（bytes）
MIN_COMPRESS_SIZE = 500

# 可壓縮的 Content-Type
COMPRESSIBLE_TYPES = {
    "application/json",
    "text/html",
    "text/plain",
    "text/css",
    "text/javascript",
    "application/javascript",
}


class GzipMiddleware(BaseHTTPMiddleware):
    """
    Gzip 壓縮中間件

    功能：
    1. 檢查客戶端是否支援 gzip
    2. 壓縮大於閾值的回應
    3. 只壓縮可壓縮的 Content-Type
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 檢查客戶端是否支援 gzip
        accept_encoding = request.headers.get("accept-encoding", "")
        supports_gzip = "gzip" in accept_encoding.lower()

        response = await call_next(request)

        # 不支援 gzip 或已經壓縮，直接返回
        if not supports_gzip:
            return response

        if response.headers.get("content-encoding"):
            return response

        # 檢查 Content-Type 是否可壓縮
        content_type = response.headers.get("content-type", "")
        base_type = content_type.split(";")[0].strip()

        if base_type not in COMPRESSIBLE_TYPES:
            return response

        # 讀取回應內容
        body = b""
        async for chunk in response.body_iterator:
            body += chunk

        # 檢查大小是否值得壓縮
        if len(body) < MIN_COMPRESS_SIZE:
            # 重建回應
            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        # 壓縮內容
        compressed = gzip.compress(body, compresslevel=6)

        # 只有壓縮後更小才使用
        if len(compressed) >= len(body):
            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        # 更新標頭
        headers = dict(response.headers)
        headers["content-encoding"] = "gzip"
        headers["content-length"] = str(len(compressed))
        # 移除可能衝突的標頭
        headers.pop("transfer-encoding", None)

        logger.debug(
            f"壓縮回應: {len(body)} -> {len(compressed)} bytes "
            f"({100 - len(compressed) * 100 // len(body)}% 減少)"
        )

        return Response(
            content=compressed,
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type,
        )
