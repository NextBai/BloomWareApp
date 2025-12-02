"""
Bloom Ware API 路由模組
拆分自 app.py，提高可維護性
"""

from .auth import router as auth_router
from .chat import router as chat_router
from .voice import router as voice_router
from .health import router as health_router
from .files import router as files_router
from .system import router as system_router

__all__ = [
    "auth_router",
    "chat_router", 
    "voice_router",
    "health_router",
    "files_router",
    "system_router",
]
