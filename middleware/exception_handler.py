"""
全域異常處理中間件
統一處理所有未捕獲的異常，返回標準化錯誤回應
"""

import logging
import traceback
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from core.exceptions import BloomWareException, handle_exception
from core.logging import get_logger

logger = get_logger("middleware.exception_handler")


class ExceptionHandlerMiddleware(BaseHTTPMiddleware):
    """
    全域異常處理中間件

    功能：
    1. 捕獲所有未處理的異常
    2. 轉換為標準化 JSON 錯誤回應
    3. 記錄錯誤日誌（生產環境隱藏堆疊）
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            response = await call_next(request)
            return response

        except BloomWareException as e:
            # 已知的業務異常
            logger.warning(f"業務異常: {e.code} - {e.message}")
            return e.to_response()

        except Exception as e:
            # 未知異常
            logger.error(f"未處理的異常: {type(e).__name__}: {e}")
            logger.debug(f"堆疊追蹤:\n{traceback.format_exc()}")

            # 返回標準化錯誤回應
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "內部伺服器錯誤",
                        "details": {}
                    }
                }
            )


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    請求日誌中間件

    功能：
    1. 記錄所有 API 請求
    2. 計算請求處理時間
    3. 記錄回應狀態碼
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        import time

        start_time = time.time()
        method = request.method
        path = request.url.path

        # 跳過健康檢查和靜態資源的日誌
        skip_paths = ["/health", "/static/", "/favicon.ico"]
        should_log = not any(path.startswith(p) for p in skip_paths)

        try:
            response = await call_next(request)
            process_time = (time.time() - start_time) * 1000

            if should_log:
                logger.info(
                    f"{method} {path} - {response.status_code} - {process_time:.2f}ms"
                )

            # 添加處理時間到回應標頭
            response.headers["X-Process-Time"] = f"{process_time:.2f}ms"
            return response

        except Exception as e:
            process_time = (time.time() - start_time) * 1000
            if should_log:
                logger.error(
                    f"{method} {path} - ERROR - {process_time:.2f}ms - {e}"
                )
            raise
