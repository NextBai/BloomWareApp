"""
新聞查詢 MCP Tool
使用 NewsData.io 實作的新聞功能，提供更可靠的台灣與繁中新聞
"""

import os
import json
import logging
import aiohttp
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from urllib.parse import quote
from dotenv import load_dotenv
from .base_tool import MCPTool, ValidationError, ExecutionError, StandardToolSchemas

# 載入環境變數
load_dotenv()

# 統一配置管理
from core.config import settings

logger = logging.getLogger("mcp.tools.news")

# NewsData.io 配置
NEWSDATA_BASE_URL = "https://newsdata.io/api/1"
NEWSDATA_API_KEY = settings.NEWSDATA_API_KEY


class NewsTool(MCPTool):
    """新聞查詢 MCP 工具 - 使用 NewsData.io（更好的台灣與繁中新聞支援）"""

    NAME = "news_query"
    DESCRIPTION = "Query latest news articles (can specify category, language, and quantity)"
    CATEGORY = "生活資訊"
    TAGS = ["news", "新聞", "資訊"]
    KEYWORDS = ["新聞", "消息", "報導", "news", "頭條", "時事"]
    USAGE_TIPS = [
        "可指定新聞類別（科技、商業、娛樂等）",
        "支援多國新聞（台灣、美國、日本等）",
        "可限制返回數量"
    ]

    @classmethod
    def get_input_schema(cls) -> Dict[str, Any]:
        """獲取輸入參數模式"""
        return StandardToolSchemas.create_input_schema({
            "query": {
                "type": "string",
                "description": "搜尋關鍵詞（可選）"
            },
            "country": {
                "type": "string",
                "description": "新聞國家代碼 (tw, us, cn, jp, kr, hk, sg)",
                "default": "tw",
                "enum": ["tw", "us", "cn", "jp", "kr", "hk", "sg", "gb", "de", "fr"]
            },
            "category": {
                "type": "string",
                "description": "新聞分類 (business, technology, health, science, sports, entertainment, top)",
                "default": "top",
                "enum": ["business", "technology", "health", "science", "sports", "entertainment", "top", "world", "politics"]
            },
            "language": {
                "type": "string",
                "description": "新聞語言 (zh, en, ja, ko)",
                "default": "zh",
                "enum": ["zh", "en", "ja", "ko"]
            },
            "limit": {
                "type": "integer",
                "description": "返回新聞數量限制（免費版最多 10）",
                "default": 10,
                "minimum": 1,
                "maximum": 10
            },
            "timeframe": {
                "type": "integer",
                "description": "查詢過去幾小時的新聞（1-48，可選）",
                "minimum": 1,
                "maximum": 48
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
                        "article_id": {"type": "string"},
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "content": {"type": "string"},
                        "url": {"type": "string"},
                        "published_at": {"type": "string"},
                        "source": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "id": {"type": "string"},
                                "url": {"type": "string"}
                            }
                        },
                        "category": {"type": "array"},
                        "language": {"type": "string"},
                        "sentiment": {"type": "string"}
                    }
                }
            },
            "count": {"type": "integer"},
            "totalResults": {"type": "integer"}
        })
        return base_schema

    @classmethod
    async def execute(cls, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """執行新聞查詢"""
        if not NEWSDATA_API_KEY:
            return cls.create_error_response(
                error="NewsData.io API 金鑰未設置，請設置 NEWSDATA_API_KEY 環境變數",
                code="API_KEY_MISSING"
            )

        # 處理參數，過濾空字串並使用預設值
        query = arguments.get("query", "")
        country = arguments.get("country", "tw") or "tw"
        category = arguments.get("category", "top") or "top"
        language = arguments.get("language", "zh") or "zh"
        limit = min(arguments.get("limit", 10), 10)  # 免費版限制 10
        timeframe = arguments.get("timeframe")

        # 確保 category 是有效值（防止空字串）
        valid_categories = ["business", "technology", "health", "science", "sports", "entertainment", "top", "world", "politics"]
        if category not in valid_categories:
            category = "top"

        try:
            news_data = await cls._fetch_news_from_newsdata(
                query, country, category, language, limit, timeframe
            )

            if news_data.get("success"):
                articles = news_data.get("articles", [])
                total_results = news_data.get("totalResults", 0)

                # 為每篇新聞生成簡短摘要（用於工具卡片顯示）
                articles = await cls._generate_summaries(articles)

                formatted_text = cls._format_newsdata_response(
                    articles, query, country, category, total_results
                )

                return cls.create_success_response(
                    content=formatted_text,
                    data={
                        "raw_data": {
                            "articles": articles,
                            "count": len(articles),
                            "totalResults": total_results
                        }
                    }
                )
            else:
                return cls.create_error_response(
                    error=news_data.get("error", "獲取新聞失敗"),
                    code="FETCH_ERROR"
                )

        except Exception as e:
            logger.error(f"新聞查詢錯誤: {e}")
            raise ExecutionError(f"新聞查詢時發生錯誤: {str(e)}", e)

    @staticmethod
    async def _fetch_news_from_newsdata(
        query: str, country: str, category: str,
        language: str, limit: int, timeframe: Optional[int]
    ) -> Dict[str, Any]:
        """從 NewsData.io 獲取新聞數據"""
        try:
            # 建構 NewsData.io URL
            url = f"{NEWSDATA_BASE_URL}/latest"

            # 構建參數
            params = {
                "apikey": NEWSDATA_API_KEY,
                "size": limit,
                "language": language
            }

            # 關鍵字搜尋
            if query:
                params["q"] = query

            # 國家篩選（僅在沒有關鍵字時使用）
            if country and not query:
                params["country"] = country

            # 分類篩選
            if category and category != "top":
                params["category"] = category

            # 時間範圍
            if timeframe:
                params["timeframe"] = timeframe

            # 排除重複
            params["removeduplicate"] = "1"

            logger.info(f"NewsData.io 請求: {url}")
            logger.info(f"參數: {', '.join([f'{k}={v}' for k, v in params.items() if k != 'apikey'])}")

            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=15) as response:
                    logger.info(f"NewsData.io 響應狀態: {response.status}")

                    if response.status == 200:
                        data = await response.json()

                        # 檢查 API 回應狀態
                        status = data.get("status")
                        if status == "success":
                            articles = data.get("results", [])
                            total_results = data.get("totalResults", 0)

                            logger.info(f"NewsData.io 返回文章數: {len(articles)} / 總數: {total_results}")

                            # 處理文章數據（確保與前端格式兼容）
                            processed_articles = []
                            for article in articles:
                                source_name = article.get("source_name", article.get("source_id", "未知來源"))

                                # 過濾掉付費功能的佔位文字
                                sentiment = article.get("sentiment", "")
                                if "ONLY AVAILABLE" in str(sentiment):
                                    sentiment = ""

                                content = article.get("content", "")
                                if "ONLY AVAILABLE" in str(content):
                                    content = ""

                                processed_article = {
                                    "article_id": article.get("article_id", ""),
                                    "title": article.get("title", "無標題"),
                                    "description": article.get("description", ""),
                                    "content": content,
                                    "url": article.get("link", ""),
                                    "published_at": article.get("pubDate", ""),
                                    # 前端期望 source 是物件 {name: "來源名"}，或字串直接顯示
                                    "source": {
                                        "name": source_name,
                                        "id": article.get("source_id", ""),
                                        "url": article.get("source_url", "")
                                    },
                                    "category": article.get("category", []),
                                    "language": article.get("language", ""),
                                    "country": article.get("country", []),
                                    "sentiment": sentiment,
                                    "image_url": article.get("image_url", "")
                                }
                                processed_articles.append(processed_article)

                            return {
                                "success": True,
                                "articles": processed_articles,
                                "totalResults": total_results
                            }
                        else:
                            # API 返回錯誤狀態
                            error_msg = data.get("results", {}).get("message", "未知錯誤")
                            error_code = data.get("results", {}).get("code", "UNKNOWN")
                            logger.error(f"NewsData.io API 錯誤: {error_code} - {error_msg}")
                            return {
                                "success": False,
                                "error": f"API 錯誤: {error_msg}"
                            }

                    elif response.status == 401:
                        return {
                            "success": False,
                            "error": "NewsData.io API 金鑰無效或已過期"
                        }
                    elif response.status == 429:
                        return {
                            "success": False,
                            "error": "NewsData.io API 請求次數已達上限（免費版每日 200 次）"
                        }
                    else:
                        error_text = await response.text()
                        logger.error(f"NewsData.io HTTP 錯誤 {response.status}: {error_text}")
                        return {
                            "success": False,
                            "error": f"HTTP 錯誤: {response.status}"
                        }

        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": "NewsData.io 請求超時，請稍後再試"
            }
        except aiohttp.ClientError as e:
            logger.error(f"網絡連接錯誤: {e}")
            return {
                "success": False,
                "error": "網絡連接錯誤，無法獲取新聞"
            }
        except Exception as e:
            logger.error(f"NewsData.io 請求錯誤: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    @staticmethod
    async def _generate_summaries(articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """為每篇新聞生成一句話簡短摘要（用於工具卡片顯示）"""
        try:
            from services.ai_service import generate_response_async

            logger.info(f"🤖 開始為 {len(articles)} 則新聞生成摘要")

            # 批量處理：一次請求處理所有新聞
            news_items = []
            for idx, article in enumerate(articles, 1):
                title = article.get("title", "")
                description = article.get("description", "")

                if not title:
                    article["summary"] = "無標題"
                    continue

                # 組合標題和描述
                content = f"{idx}. 標題：{title}"
                if description:
                    content += f"\n   描述：{description[:100]}"
                news_items.append(content)

            if not news_items:
                return articles

            # 一次性請求 AI 生成所有摘要
            batch_prompt = "\n\n".join(news_items)

            try:
                response = await generate_response_async(
                    messages=[
                        {
                            "role": "system",
                            "content": "你是新聞摘要助手。請為每則新聞生成一句話摘要（最多30字），用數字編號回應。"
                        },
                        {
                            "role": "user",
                            "content": f"請為以下新聞各生成一句話摘要（每則最多30字）：\n\n{batch_prompt}"
                        }
                    ],
                    model="gpt-5-nano",
                    reasoning_effort="low"
                )

                # 解析回應
                lines = response.strip().split('\n')
                summaries = []
                for line in lines:
                    line = line.strip()
                    # 移除編號前綴 (1. 2. 等)
                    if line and (line[0].isdigit() or line.startswith('•') or line.startswith('-')):
                        # 去除編號和標點
                        summary = line.lstrip('0123456789.-•) ').strip()
                        if summary:
                            summaries.append(summary[:30])  # 限制 30 字

                # 將摘要分配給文章
                for idx, article in enumerate(articles):
                    if article.get("title"):
                        if idx < len(summaries):
                            article["summary"] = summaries[idx]
                            logger.info(f"📝 新聞{idx+1} 摘要: {summaries[idx]} ({len(summaries[idx])}字)")
                        else:
                            # Fallback
                            title = article.get("title", "")
                            article["summary"] = title[:30]
                            logger.warning(f"⚠️ 新聞{idx+1} 使用 fallback")

            except Exception as e:
                logger.error(f"AI 生成摘要失敗: {e}")
                # Fallback: 使用標題
                for article in articles:
                    title = article.get("title", "無標題")
                    article["summary"] = title[:30]

            return articles

        except Exception as e:
            logger.error(f"批量生成摘要失敗: {e}")
            # 失敗時使用標題作為 fallback
            for article in articles:
                if "summary" not in article:
                    title = article.get("title", "無標題")
                    article["summary"] = title[:30]
            return articles

    @staticmethod
    def _format_newsdata_response(
        articles: List[Dict[str, Any]], query: str,
        country: str, category: str, total_results: int
    ) -> str:
        """格式化 NewsData.io 回應"""
        if not articles:
            return "抱歉，找不到相關新聞"

        # 標題
        header = "📰 最新新聞"
        if query:
            header += f" - 搜尋: {query}"
        else:
            country_names = {
                "tw": "台灣", "us": "美國", "cn": "中國",
                "jp": "日本", "kr": "韓國", "hk": "香港",
                "sg": "新加坡", "gb": "英國", "de": "德國", "fr": "法國"
            }
            header += f" - {country_names.get(country, country.upper())}"

        if category and category != "top":
            category_names = {
                "business": "商業", "technology": "科技",
                "health": "健康", "science": "科學",
                "sports": "體育", "entertainment": "娛樂",
                "world": "國際", "politics": "政治"
            }
            header += f" - {category_names.get(category, category)}"

        result = f"{header}\n\n"

        # 新聞列表
        for i, article in enumerate(articles, 1):
            result += f"📌 {article.get('title', '無標題')}\n"

            # 來源（兼容物件和字串格式）
            source = article.get('source', {})
            if isinstance(source, dict):
                source_name = source.get('name', '未知來源')
            else:
                source_name = source or '未知來源'
            result += f"🗞️ {source_name}"

            # 分類標籤
            categories = article.get('category', [])
            if categories:
                category_str = ", ".join(categories[:2])  # 最多顯示 2 個分類
                result += f" | 🏷️ {category_str}"

            # 情緒標籤（過濾付費功能提示）
            sentiment = article.get('sentiment', '')
            if sentiment and "ONLY AVAILABLE" not in str(sentiment):
                sentiment_emoji = {
                    "positive": "😊 正面",
                    "neutral": "😐 中立",
                    "negative": "😟 負面"
                }.get(sentiment.lower(), sentiment)
                result += f" | {sentiment_emoji}"

            result += "\n"

            # 發布時間
            published_at = article.get('published_at', '')
            if published_at:
                try:
                    # NewsData.io 格式: "2025-01-25 12:34:56"
                    if ' ' in published_at:
                        dt = datetime.strptime(published_at, '%Y-%m-%d %H:%M:%S')
                        formatted_date = dt.strftime('%m/%d %H:%M')
                        result += f"📅 {formatted_date}\n"
                    else:
                        result += f"📅 {published_at[:16]}\n"
                except Exception as e:
                    logger.warning(f"日期解析錯誤: {e}")
                    result += f"📅 {published_at[:16]}\n"

            # 描述
            description = article.get('description', '')
            if description:
                if len(description) > 150:
                    description = description[:150] + "..."
                result += f"📝 {description}\n"

            # 連結
            url = article.get('url', '')
            if url:
                result += f"🔗 {url}\n"

            result += "\n"

        # 底部資訊
        result += f"📊 顯示 {len(articles)} 則 / 共 {total_results} 則新聞 | 🕒 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        result += "\n💡 由 NewsData.io 提供"

        return result
