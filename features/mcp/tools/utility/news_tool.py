"""
新聞查詢 MCP Tool - 已遷移至 Tavily API
提供更精準、即時且經過過濾的新聞搜尋結果
"""

import os
import json
import logging
import aiohttp
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv
from ..base_tool import MCPTool, ValidationError, ExecutionError, StandardToolSchemas

# 載入環境變數
load_dotenv()

# 統一配置管理
from core.config import settings

logger = logging.getLogger("mcp.tools.news")

# Tavily API 配置
TAVILY_BASE_URL = "https://api.tavily.com/search"
TAVILY_API_KEY = settings.TAVILY_API_KEY


class NewsTool(MCPTool):
    """新聞查詢 MCP 工具 - 使用 Tavily API（優化 AI 搜尋與新聞時效性）"""

    NAME = "news_query"
    DESCRIPTION = "Query latest news articles and real-time information using Tavily AI search"
    CATEGORY = "生活資訊"
    TAGS = ["news", "新聞", "search", "即時"]
    KEYWORDS = ["新聞", "消息", "報導", "news", "頭條", "時事", "搜尋"]
    USAGE_TIPS = [
        "可搜尋特定主題的最新進展",
        "支援全球新聞與即時資訊",
        "自動過濾無關內容並提供摘要"
    ]

    @classmethod
    def get_input_schema(cls) -> Dict[str, Any]:
        """獲獲取輸入參數模式"""
        return StandardToolSchemas.create_input_schema({
            "query": {
                "type": "string",
                "description": "搜尋關鍵詞或新聞主題"
            },
            "limit": {
                "type": "integer",
                "description": "返回結果數量限制（預設 5，最多 10）",
                "default": 5,
                "minimum": 1,
                "maximum": 10
            },
            "search_depth": {
                "type": "string",
                "description": "搜尋深度 (basic 或 advanced)",
                "default": "basic",
                "enum": ["basic", "advanced"]
            }
        })

    @classmethod
    def get_output_schema(cls) -> Dict[str, Any]:
        """獲取輸出結果模式"""
        base_schema = StandardToolSchemas.create_output_schema()
        base_schema["properties"].update({
            "articles": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "url": {"type": "string"},
                        "published_at": {"type": "string"},
                        "source": {"type": "string"},
                        "score": {"type": "number"},
                        "image": {"type": "string"}
                    }
                }
            },
            "answer": {"type": "string"},
            "count": {"type": "integer"}
        })
        return base_schema

    @classmethod
    async def execute(cls, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """執行新聞查詢"""
        if not TAVILY_API_KEY:
            return cls.create_error_response(
                error="Tavily API 金鑰未設置，請設置 TAVILY_API_KEY 環境變數",
                code="API_KEY_MISSING"
            )

        query = arguments.get("query", "").strip()
        if not query:
            return cls.create_error_response(
                error="請提供搜尋關鍵詞",
                code="MISSING_QUERY"
            )

        # 優先以台灣為出發點，如果 query 沒提到地區，自動加上「台灣」
        if "台灣" not in query and "taiwan" not in query.lower():
            query_for_tavily = f"{query} 台灣"
        else:
            query_for_tavily = query

        limit = min(arguments.get("limit", 5), 10)
        # 預設使用 basic 深度以確保低延遲，除非明確要求 advanced
        search_depth = arguments.get("search_depth", "basic")

        try:
            # 呼叫 Tavily API，設定 10 秒超時避免阻塞整個 Pipeline
            try:
                news_data = await asyncio.wait_for(
                    cls._fetch_from_tavily(query_for_tavily, limit, search_depth),
                    timeout=10.0
                )
            except asyncio.TimeoutError:
                logger.warning(f"⚠️ Tavily 搜尋超時 ({search_depth})，嘗試回退至 basic")
                if search_depth == "advanced":
                    news_data = await asyncio.wait_for(
                        cls._fetch_from_tavily(query_for_tavily, limit, "basic"),
                        timeout=5.0
                    )
                else:
                    return cls.create_error_response(error="搜尋服務響應過慢，請稍後再試", code="TIMEOUT")

            if news_data.get("success"):
                articles = news_data.get("results", [])
                answer = news_data.get("answer", "")
                
                formatted_text = cls._format_tavily_response(articles, answer, query)

                return cls.create_success_response(
                    content=formatted_text,
                    data={
                        "articles": articles,
                        "answer": answer,
                        "count": len(articles)
                    }
                )
            else:
                return cls.create_error_response(
                    error=news_data.get("error", "獲取搜尋結果失敗"),
                    code="FETCH_ERROR"
                )

        except Exception as e:
            logger.error(f"Tavily 查詢錯誤: {e}")
            raise ExecutionError(f"查詢時發生錯誤: {str(e)}", e)

    @staticmethod
    async def _fetch_from_tavily(query: str, limit: int, search_depth: str) -> Dict[str, Any]:
        """從 Tavily API 獲取數據"""
        try:
            payload = {
                "api_key": TAVILY_API_KEY,
                "query": query,
                "search_depth": search_depth,
                "topic": "news",
                "max_results": limit,
                "include_answer": True,
                "include_images": True
            }

            logger.info(f"🚀 Tavily 新聞請求: {query} (depth: {search_depth})")

            async with aiohttp.ClientSession() as session:
                async with session.post(TAVILY_BASE_URL, json=payload, timeout=20) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "success": True,
                            "results": data.get("results", []),
                            "answer": data.get("answer", "")
                        }
                    else:
                        error_text = await response.text()
                        logger.error(f"Tavily API 錯誤 {response.status}: {error_text}")
                        return {
                            "success": False,
                            "error": f"API 錯誤: {response.status}"
                        }

        except asyncio.TimeoutError:
            return {"success": False, "error": "請求超時"}
        except Exception as e:
            logger.error(f"Tavily 請求異常: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def _format_tavily_response(articles: List[Dict[str, Any]], answer: str, query: str) -> str:
        """格式化 Tavily 回應"""
        if not articles and not answer:
            return "抱歉，找不到相關的新聞或資訊"

        header = f"🌐 Tavily 即時新聞搜尋: {query}"
        result = f"{header}\n\n"

        # 如果有 Tavily AI 生成的回答，優先顯示
        if answer:
            result += f"💡 快速摘要：\n{answer}\n\n"
            result += "--- 詳細報導 ---\n\n"

        for i, article in enumerate(articles, 1):
            title = article.get("title", "無標題")
            url = article.get("url", "")
            content = article.get("content", "")
            # Tavily 有時不提供發布時間，我們顯示來源 URL 的網域
            source = article.get("url", "").split("//")[-1].split("/")[0]
            
            result += f"{i}. {title}\n"
            if source:
                result += f"   🗞️ 來源: {source}\n"
            if content:
                # 限制內容長度
                short_content = content[:150] + "..." if len(content) > 150 else content
                result += f"   📝 {short_content}\n"
            if url:
                result += f"   🔗 {url}\n"
            result += "\n"

        result += f"📊 找到 {len(articles)} 則相關內容 | 🕒 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        result += "\n💡 由 Tavily AI 驅動"

        return result
