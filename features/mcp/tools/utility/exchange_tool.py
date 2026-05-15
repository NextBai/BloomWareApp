"""
匯率查詢 MCP Tool
使用標準化接口實作的匯率功能
"""

import os
import json
import logging
import aiohttp
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from ..base_tool import MCPTool, ValidationError, ExecutionError, StandardToolSchemas

# 載入環境變數
load_dotenv()

logger = logging.getLogger("mcp.tools.exchange")

# API配置
EXCHANGE_API_BASE = "https://api.exchangerate-api.com/v4/latest"
FIXER_API_BASE = "https://data.fixer.io/api/latest"
FIXER_API_KEY = os.getenv("FIXER_API_KEY", "")


class ExchangeTool(MCPTool):
    """匯率查詢 MCP 工具"""

    NAME = "exchange_query"
    DESCRIPTION = """Query real-time exchange rates between major currencies.
IMPORTANT Parameter Extraction Rules:
1. "A to B", "A into B", "A exchange B" -> from_currency="A", to_currency="B"
2. "[amount] A to B" -> from_currency="A", to_currency="B", amount=[number]
3. Must use ISO 4217 (e.g., USD, TWD, JPY, EUR, GBP, CNY, HKD, KRW).
Example: "100 USD to TWD" -> from_currency="USD", to_currency="TWD", amount=100.
Always extract currency codes from the message!"""
    CATEGORY = "生活資訊"
    TAGS = ["exchange", "匯率", "貨幣"]
    KEYWORDS = ["匯率", "美元", "台幣", "exchange", "USD", "TWD", "貨幣", "換算"]
    USAGE_TIPS = [
        "提供源貨幣和目標貨幣代碼（如 USD, TWD）",
        "支援主要國際貨幣",
        "可查詢即時匯率與歷史趨勢"
    ]

    @classmethod
    def get_input_schema(cls) -> Dict[str, Any]:
        """獲取輸入參數模式"""
        schema = StandardToolSchemas.create_input_schema({
            "from_currency": {
                "type": "string",
                "description": "源貨幣代碼 (如 USD, EUR, TWD)",
                "default": "USD",
                "pattern": "^[A-Z]{3}$"
            },
            "to_currency": {
                "type": "string",
                "description": "目標貨幣代碼 (如 TWD, USD, EUR)",
                "default": "TWD",
                "pattern": "^[A-Z]{3}$"
            },
            "amount": {
                "type": "number",
                "description": "轉換金額",
                "default": 1.0,
                "minimum": 0.01
            },
            "conversion": {
                "type": "boolean",
                "description": "是否進行金額轉換計算",
                "default": True
            }
        }, ["from_currency", "to_currency"])
        return schema

    @classmethod
    def get_output_schema(cls) -> Dict[str, Any]:
        """獲取輸出結果模式"""
        base_schema = StandardToolSchemas.create_output_schema()
        base_schema["properties"].update({
            "rate": {"type": "number"},
            "converted_amount": {"type": ["number", "null"]},
            "raw_data": {"type": "object"}
        })
        return base_schema

    @classmethod
    async def execute(cls, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """執行匯率查詢"""
        from_currency = arguments.get("from_currency", "USD").upper()
        to_currency = arguments.get("to_currency", "TWD").upper()
        amount = arguments.get("amount", 1.0)
        conversion = arguments.get("conversion", True)

        try:
            # 獲取匯率數據
            rate_data = await cls._fetch_exchange_rate(from_currency, to_currency)

            if rate_data.get("success"):
                rate = rate_data.get("rate")
                
                # 生成結構化數據供 AI 格式化
                formatted_text = cls._format_exchange_response(
                    from_currency, to_currency, rate, amount, conversion, rate_data.get("metadata", {})
                )
                
                return cls.create_success_response(
                    content=formatted_text,
                    data={
                        "raw_data": {
                            "rate": rate,
                            "from_currency": from_currency,
                            "to_currency": to_currency,
                            "amount": amount,
                            "converted_amount": amount * rate if conversion else None,
                            "rate_data": rate_data
                        }
                    }
                )
            else:
                return cls.create_error_response(
                    error=rate_data.get("error", "獲取匯率失敗"),
                    code="FETCH_ERROR"
                )

        except Exception as e:
            logger.error(f"匯率查詢錯誤: {e}")
            raise ExecutionError(f"匯率查詢時發生錯誤: {str(e)}", e)

    @staticmethod
    async def _fetch_exchange_rate(from_currency: str, to_currency: str) -> Dict[str, Any]:
        """獲取匯率數據"""
        # 首先嘗試免費 API
        try:
            result = await ExchangeTool._fetch_from_exchangerate_api(from_currency, to_currency)
            if result.get("success"):
                return result
        except Exception as e:
            logger.warning(f"免費匯率 API 失敗: {e}")

        # 如果有 Fixer API Key，嘗試備用 API
        if FIXER_API_KEY:
            try:
                result = await ExchangeTool._fetch_from_fixer_api(from_currency, to_currency)
                if result.get("success"):
                    return result
            except Exception as e:
                logger.warning(f"Fixer API 失敗: {e}")

        return {
            "success": False,
            "error": "所有匯率 API 都無法使用，請稍後再試"
        }

    @staticmethod
    async def _fetch_from_exchangerate_api(from_currency: str, to_currency: str) -> Dict[str, Any]:
        """從 exchangerate-api.com 獲取匯率"""
        url = f"{EXCHANGE_API_BASE}/{from_currency}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    rates = data.get("rates", {})

                    if to_currency in rates:
                        rate = rates[to_currency]
                        return {
                            "success": True,
                            "rate": rate,
                            "metadata": {
                                "source": "exchangerate-api.com",
                                "base": data.get("base"),
                                "date": data.get("date"),
                                "timestamp": data.get("timestamp")
                            }
                        }
                    else:
                        return {
                            "success": False,
                            "error": f"不支援的貨幣: {to_currency}"
                        }
                else:
                    return {
                        "success": False,
                        "error": f"匯率 API 請求失敗，狀態碼: {response.status}"
                    }

    @staticmethod
    async def _fetch_from_fixer_api(from_currency: str, to_currency: str) -> Dict[str, Any]:
        """從 fixer.io API 獲取匯率"""
        url = f"{FIXER_API_BASE}?access_key={FIXER_API_KEY}&base={from_currency}&symbols={to_currency}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()

                    if data.get("success"):
                        rates = data.get("rates", {})
                        if to_currency in rates:
                            rate = rates[to_currency]
                            return {
                                "success": True,
                                "rate": rate,
                                "metadata": {
                                    "source": "fixer.io",
                                    "base": data.get("base"),
                                    "date": data.get("date"),
                                    "timestamp": data.get("timestamp")
                                }
                            }
                        else:
                            return {
                                "success": False,
                                "error": f"不支援的貨幣: {to_currency}"
                            }
                    else:
                        error_info = data.get("error", {})
                        return {
                            "success": False,
                            "error": f"Fixer API 錯誤: {error_info.get('info', '未知錯誤')}"
                        }
                else:
                    return {
                        "success": False,
                        "error": f"Fixer API 請求失敗，狀態碼: {response.status}"
                    }

    @staticmethod
    def _format_exchange_response(from_currency: str, to_currency: str, rate: float,
                                  amount: float, conversion: bool, metadata: Dict) -> str:
        """格式化匯率回應"""
        # 貨幣符號和名稱映射
        currency_info = ExchangeTool._get_currency_info()

        from_symbol = currency_info.get(from_currency, {}).get("symbol", from_currency)
        from_name = currency_info.get(from_currency, {}).get("name", from_currency)
        to_symbol = currency_info.get(to_currency, {}).get("symbol", to_currency)
        to_name = currency_info.get(to_currency, {}).get("name", to_currency)

        # 標題
        result = f"💱 匯率資訊\n\n"

        # 匯率
        result += f"💰 匯率: 1 {from_currency} = {rate:.4f} {to_currency}\n"
        result += f"📈 {from_name} → {to_name}\n\n"

        # 如果是轉換計算
        if conversion and amount != 1.0:
            converted = amount * rate
            result += f"🔄 金額轉換\n"
            result += f"📊 {amount:,.2f} {from_currency} = {converted:,.2f} {to_currency}\n"
            result += f"💸 {from_symbol}{amount:,.2f} → {to_symbol}{converted:,.2f}\n\n"

        # 數據來源和時間
        source = metadata.get("source", "未知")
        date = metadata.get("date", "")
        if date:
            result += f"📅 數據日期: {date}\n"

        result += f"🔗 數據來源: {source}\n"
        result += f"⏰ 查詢時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"

        # 匯率變化提示
        result += f"\n💡 匯率會隨市場變動，僅供參考"

        return result

    @staticmethod
    def _get_currency_info() -> Dict[str, Dict[str, str]]:
        """獲取貨幣資訊映射"""
        return {
            "TWD": {"symbol": "NT$", "name": "新台幣"},
            "USD": {"symbol": "$", "name": "美元"},
            "EUR": {"symbol": "€", "name": "歐元"},
            "JPY": {"symbol": "¥", "name": "日圓"},
            "GBP": {"symbol": "£", "name": "英鎊"},
            "AUD": {"symbol": "A$", "name": "澳幣"},
            "CAD": {"symbol": "C$", "name": "加幣"},
            "CHF": {"symbol": "Fr", "name": "瑞士法郎"},
            "CNY": {"symbol": "¥", "name": "人民幣"},
            "HKD": {"symbol": "HK$", "name": "港幣"},
            "NZD": {"symbol": "NZ$", "name": "紐幣"},
            "KRW": {"symbol": "₩", "name": "韓元"},
            "SGD": {"symbol": "S$", "name": "新加坡幣"},
            "THB": {"symbol": "฿", "name": "泰銖"},
            "MYR": {"symbol": "RM", "name": "馬幣"},
            "IDR": {"symbol": "Rp", "name": "印尼盧比"},
            "PHP": {"symbol": "₱", "name": "菲律賓比索"},
            "VND": {"symbol": "₫", "name": "越南盾"},
            "RUB": {"symbol": "₽", "name": "俄羅斯盧布"},
            "BRL": {"symbol": "R$", "name": "巴西雷亞爾"},
            "ZAR": {"symbol": "R", "name": "南非蘭特"},
            "INR": {"symbol": "₹", "name": "印度盧比"}
        }