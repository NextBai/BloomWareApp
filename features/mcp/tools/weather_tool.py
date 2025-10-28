"""
天氣查詢 MCP Tool
使用標準化接口實作的天氣功能
"""

import os
import json
import logging
import aiohttp
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from .base_tool import MCPTool, ValidationError, ExecutionError, StandardToolSchemas

# 載入環境變數
load_dotenv()

# 統一配置管理
from core.config import settings

logger = logging.getLogger("mcp.tools.weather")

# API配置
WEATHER_API_KEY = settings.WEATHER_API_KEY
WEATHER_API_URL = "https://api.openweathermap.org/data/2.5/weather"


class WeatherTool(MCPTool):
    """天氣查詢 MCP 工具"""

    NAME = "weather_query"
    DESCRIPTION = "查詢指定城市的天氣資訊，支援城市名稱或座標查詢"
    CATEGORY = "天氣"
    TAGS = ["weather", "climate", "forecast"]
    USAGE_TIPS = ["直接說「台北天氣」或「東京天氣」"]

    @classmethod
    def get_input_schema(cls) -> Dict[str, Any]:
        """獲取輸入參數模式"""
        return StandardToolSchemas.create_input_schema({
            "city": {
                "type": "string",
                "description": "城市名稱（請使用英文，例如：Taipei, Tokyo, London, New York）或座標 (lat,lon 格式)"
            },
            "language": {
                "type": "string",
                "description": "回覆語言 (zh_tw, en, zh_cn)",
                "default": "zh_tw",
                "enum": ["zh_tw", "en", "zh_cn"]
            }
        }, ["city"])

    @classmethod
    def get_output_schema(cls) -> Dict[str, Any]:
        """獲取輸出結果模式"""
        base_schema = StandardToolSchemas.create_output_schema()
        base_schema["properties"].update({
            "raw_data": {"type": "object"}
        })
        return base_schema

    @classmethod
    async def execute(cls, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """執行天氣查詢"""
        city = arguments.get("city")
        language = arguments.get("language", "zh_tw")

        if not city:
            raise ValidationError("city", "未提供城市名稱")

        if not WEATHER_API_KEY:
            raise ExecutionError("未設置天氣 API 密鑰，請在 .env 文件中添加 WEATHER_API_KEY")

        try:
            weather_data = await cls._get_weather_data(city, language)

            if weather_data.get("success"):
                # 生成結構化數據供 AI 格式化
                formatted_text = cls._format_weather_response(weather_data)
                
                # 保留完整的原始數據供工具卡片使用
                return cls.create_success_response(
                    content=formatted_text,
                    data={"raw_data": weather_data.get("data")}
                )
            else:
                return cls.create_error_response(
                    error=weather_data.get("error", "獲取天氣資訊失敗"),
                    code="FETCH_ERROR"
                )

        except Exception as e:
            logger.error(f"天氣查詢錯誤: {e}")
            raise ExecutionError(f"天氣查詢時發生錯誤: {str(e)}", e)

    @staticmethod
    async def _get_weather_data(city: str, language: str = "zh_tw") -> Dict[str, Any]:
        """獲取天氣數據"""
        try:
            logger.info(f"查詢 {city} 的天氣資訊")

            params = {
                "appid": WEATHER_API_KEY,
                "units": "metric",
                "lang": language
            }

            # 判斷是座標還是城市名
            if "," in city and len(city.split(",")) == 2:
                try:
                    lat, lon = city.split(",")
                    lat_float = float(lat.strip())
                    lon_float = float(lon.strip())
                    params["lat"] = lat_float
                    params["lon"] = lon_float
                    logger.info(f"使用座標查詢: 緯度={lat_float}, 經度={lon_float}")
                except ValueError:
                    params["q"] = city
            else:
                params["q"] = city

            async with aiohttp.ClientSession() as session:
                async with session.get(WEATHER_API_URL, params=params, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {"success": True, "data": data}
                    elif response.status == 401:
                        return {"success": False, "error": "天氣 API 授權失敗，請檢查 API 密鑰"}
                    elif response.status == 404:
                        return {"success": False, "error": f"找不到城市 {city} 的天氣資訊"}
                    elif response.status == 429:
                        return {"success": False, "error": "天氣 API 請求次數超限，請稍後再試"}
                    else:
                        return {"success": False, "error": f"天氣 API 請求失敗，狀態碼: {response.status}"}

        except asyncio.TimeoutError:
            return {"success": False, "error": "獲取天氣資訊超時"}
        except aiohttp.ClientError:
            return {"success": False, "error": "網絡連接錯誤，無法獲取天氣資訊"}
        except Exception as e:
            logger.error(f"獲取天氣資訊錯誤: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def _format_weather_response(weather_data: Dict[str, Any]) -> str:
        """格式化天氣回應"""
        if not weather_data.get("success"):
            return f"天氣查詢失敗: {weather_data.get('error', '未知錯誤')}"

        data = weather_data.get("data", {})
        if not data:
            return "獲取的天氣數據為空"

        try:
            # 基本資訊
            city_name = data.get("name", "未知城市")
            country = data.get("sys", {}).get("country", "")
            weather_main = data.get("weather", [{}])[0].get("main", "未知")
            weather_description = data.get("weather", [{}])[0].get("description", "未知天氣狀況")
            temperature = data.get("main", {}).get("temp", 0)
            feels_like = data.get("main", {}).get("feels_like", 0)
            humidity = data.get("main", {}).get("humidity", 0)
            pressure = data.get("main", {}).get("pressure", 0)
            wind_speed = data.get("wind", {}).get("speed", 0)

            # 日出日落
            sunrise_ts = data.get("sys", {}).get("sunrise", 0)
            sunset_ts = data.get("sys", {}).get("sunset", 0)
            sunrise_time = datetime.fromtimestamp(sunrise_ts).strftime("%H:%M") if sunrise_ts else "未知"
            sunset_time = datetime.fromtimestamp(sunset_ts).strftime("%H:%M") if sunset_ts else "未知"

            # 當地時間
            timezone_offset = data.get("timezone", 0)
            local_time = datetime.utcnow() + timedelta(seconds=timezone_offset)
            local_time_str = local_time.strftime("%Y-%m-%d %H:%M")

            # 天氣表情符號
            weather_emoji = WeatherTool._get_weather_emoji(weather_main, sunrise_ts < datetime.now().timestamp() < sunset_ts)

            # 格式化輸出
            result = f"🌍 {city_name} 天氣資訊 {weather_emoji}\n\n"
            result += f"📅 當前時間: {local_time_str}\n"
            result += f"🌡️ 當前溫度: {temperature}°C\n"
            result += f"🤔 體感溫度: {feels_like}°C\n"
            result += f"☁️ 天氣狀況: {weather_description}\n"
            result += f"💧 濕度: {humidity}%\n"
            result += f"🌪️ 風速: {wind_speed} m/s\n"
            result += f"📊 氣壓: {pressure} hPa\n"
            result += f"🌅 日出: {sunrise_time}\n"
            result += f"🌇 日落: {sunset_time}\n"

            return result

        except Exception as e:
            logger.error(f"格式化天氣數據失敗: {e}")
            return f"處理天氣數據時出現錯誤: {str(e)}"

    @staticmethod
    def _get_weather_emoji(weather_main: str, is_daytime: bool = True) -> str:
        """根據天氣狀況返回表情符號"""
        weather_emojis = {
            "Clear": "☀️" if is_daytime else "🌙",
            "Clouds": "⛅" if is_daytime else "☁️",
            "Rain": "🌧️",
            "Drizzle": "🌦️",
            "Thunderstorm": "⛈️",
            "Snow": "❄️",
            "Mist": "🌫️",
            "Fog": "🌫️",
            "Haze": "🌫️",
            "Dust": "🌫️",
            "Sand": "🌫️",
            "Smoke": "🌫️",
            "Squall": "💨",
            "Tornado": "🌪️"
        }
        return weather_emojis.get(weather_main, "🌡️")