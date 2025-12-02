"""
系統相關 API 路由
包含狀態檢查、效能統計、MCP 工具列表等
"""

from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse

from core.auth import get_current_user_optional
from core.logging import get_logger
from core.config import settings

logger = get_logger("routers.system")

router = APIRouter(tags=["系統"])


@router.get("/")
async def root():
    """根路徑導向登入頁面"""
    return RedirectResponse(url="/login/")


@router.get("/status")
async def get_status():
    """系統狀態檢查"""
    return {
        "status": "running",
        "version": "2.0.0",
        "environment": settings.ENVIRONMENT,
    }


@router.get("/api/mcp/tools")
async def list_mcp_tools(current_user: dict = Depends(get_current_user_optional)):
    """
    列出所有可用的 MCP 工具

    Returns:
        工具列表，包含名稱、描述、參數等
    """
    try:
        # 延遲導入避免循環依賴
        from app import app

        if not hasattr(app.state, 'feature_router'):
            return {
                "success": False,
                "error": "MCP 服務尚未初始化",
                "tools": []
            }

        feature_router = app.state.feature_router
        tools_info = []

        for tool_name, tool in feature_router.mcp_server.tools.items():
            tool_info = {
                "name": tool_name,
                "description": getattr(tool, 'description', '無描述'),
            }

            # 嘗試獲取參數 schema
            if hasattr(tool, 'handler') and hasattr(tool.handler, '__self__'):
                tool_class = tool.handler.__self__
                if hasattr(tool_class, 'get_input_schema'):
                    try:
                        tool_info["parameters"] = tool_class.get_input_schema()
                    except Exception:
                        pass

            tools_info.append(tool_info)

        return {
            "success": True,
            "count": len(tools_info),
            "tools": tools_info
        }

    except Exception as e:
        logger.error(f"獲取 MCP 工具列表失敗: {e}")
        return {
            "success": False,
            "error": str(e),
            "tools": []
        }


@router.get("/api/performance/stats")
async def get_performance_stats(current_user: dict = Depends(get_current_user_optional)):
    """
    獲取系統效能統計

    Returns:
        快取命中率、查詢統計等
    """
    try:
        from core.database.cache import db_cache
        from core.database.optimized import query_optimizer

        cache_stats = db_cache.get_all_stats()
        query_stats = query_optimizer.get_stats()

        return {
            "success": True,
            "cache": cache_stats,
            "queries": query_stats,
        }

    except Exception as e:
        logger.error(f"獲取效能統計失敗: {e}")
        return {
            "success": False,
            "error": str(e)
        }
