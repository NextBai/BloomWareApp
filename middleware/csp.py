"""
Content Security Policy 中間件
允許內嵌 script 用於語音沉浸式前端
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest


class CSPMiddleware(BaseHTTPMiddleware):
    """CSP 中間件"""

    async def dispatch(self, request: StarletteRequest, call_next):
        response = await call_next(request)
        
        # 對所有靜態檔案路徑添加寬鬆的 CSP header
        if request.url.path.startswith("/static/"):
            # 移除可能存在的嚴格 CSP
            if "Content-Security-Policy" in response.headers:
                del response.headers["Content-Security-Policy"]

            # 設定寬鬆的 CSP 以允許內嵌 script
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
                "https://accounts.google.com https://www.gstatic.com; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com data:; "
                "connect-src 'self' ws: wss: https://accounts.google.com; "
                "img-src 'self' data: https: blob:; "
                "media-src 'self' blob: data:; "
                "frame-src https://accounts.google.com; "
                "base-uri 'self';"
            )
            
        return response
