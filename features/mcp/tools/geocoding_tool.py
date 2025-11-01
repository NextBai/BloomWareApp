"""
地點名稱轉座標工具（Forward Geocoding）
使用 Nominatim（OSM）將地點名稱轉換為經緯度座標
"""

import aiohttp
import asyncio
import logging
from typing import Dict, Any, List

from .base_tool import MCPTool, StandardToolSchemas, ExecutionError
from core.database import get_geo_cache, set_geo_cache
from core.database.cache import db_cache

logger = logging.getLogger("mcp.tools.geocoding")


class ForwardGeocodeTool(MCPTool):
    NAME = "forward_geocode"
    DESCRIPTION = "將地點名稱（如「銘傳大學」「桃園火車站」）轉換為經緯度座標"
    CATEGORY = "地理定位"
    TAGS = ["geocode", "forward", "地點", "座標"]
    KEYWORDS = ["地點", "位置", "座標", "在哪裡", "地址查詢"]
    USAGE_TIPS = [
        "提供地點名稱即可（如「台北101」「淡水捷運站」）",
        "支援地標、車站、學校、商圈等",
        "會返回最相關的座標與詳細地址"
    ]

    @classmethod
    def get_input_schema(cls) -> Dict[str, Any]:
        return StandardToolSchemas.create_input_schema({
            "query": {
                "type": "string",
                "description": "地點名稱或地址（如「銘傳大學桃園校區」「桃園火車站」「台北101」）"
            },
            "limit": {
                "type": "integer",
                "description": "返回結果數量（預設 1，最多 5）",
                "default": 1
            }
        }, required=["query"])

    @classmethod
    def get_output_schema(cls) -> Dict[str, Any]:
        schema = StandardToolSchemas.create_output_schema()
        schema["properties"].update({
            "results": {
                "type": "array",
                "description": "地點查詢結果列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number", "description": "緯度"},
                        "lon": {"type": "number", "description": "經度"},
                        "display_name": {"type": "string", "description": "完整地址"},
                        "label": {"type": "string", "description": "簡短標籤"},
                        "importance": {"type": "number", "description": "重要性評分（0-1）"}
                    }
                }
            },
            "best_match": {
                "type": "object",
                "description": "最佳匹配結果",
                "properties": {
                    "lat": {"type": "number"},
                    "lon": {"type": "number"},
                    "label": {"type": "string"}
                }
            }
        })
        return schema

    @classmethod
    async def execute(cls, arguments: Dict[str, Any]) -> Dict[str, Any]:
        query = arguments.get("query", "").strip()
        if not query:
            raise ExecutionError("請提供地點名稱")

        limit = min(int(arguments.get("limit", 1)), 5)

        # 生成快取鍵（基於查詢文字）
        import hashlib
        cache_key = hashlib.md5(f"geocode:{query}".encode()).hexdigest()

        # 記憶體快取
        cached = await db_cache.get_geo_cached(cache_key)
        if cached:
            logger.info(f"📍 Geocoding 快取命中: {query}")
            return cls.create_success_response(
                content=f"找到地點：{cached['best_match']['label']}",
                data=cached
            )

        # DB 快取
        db_cached = await get_geo_cache(cache_key)
        if db_cached:
            await db_cache.set_geo_cache(cache_key, db_cached)
            return cls.create_success_response(
                content=f"找到地點：{db_cached['best_match']['label']}",
                data=db_cached
            )

        # 外呼 Nominatim（公共端點，務必節流）
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            "format": "jsonv2",
            "q": query,
            "limit": limit,
            "addressdetails": 1,
            "extratags": 1,  # 取得額外標籤
            "namedetails": 1,  # 取得多語言名稱
            "accept-language": "zh-TW,zh"
        }
        headers = {
            "User-Agent": "BloomWare/1.0 (contact@example.com)"
        }

        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        raise ExecutionError(f"Nominatim 查詢失敗: HTTP {resp.status}")
                    
                    data = await resp.json()
                    
                    if not data or len(data) == 0:
                        raise ExecutionError(f"找不到地點「{query}」，請確認地點名稱是否正確")

        except asyncio.TimeoutError:
            raise ExecutionError("地點查詢逾時，請稍後再試")
        except aiohttp.ClientError as e:
            raise ExecutionError(f"網路連接錯誤: {str(e)}")

        # 解析結果
        results = []
        for item in data:
            lat = float(item.get("lat", 0))
            lon = float(item.get("lon", 0))
            display_name = item.get("display_name", "")
            importance = float(item.get("importance", 0))
            
            # 解析地址組件
            addr = item.get("address", {})
            extratags = item.get("extratags", {})
            namedetails = item.get("namedetails", {})
            
            name = item.get("name", "")
            name_zh = namedetails.get("name:zh") or namedetails.get("name:zh-TW") or name
            
            # 基本地址組件
            road = addr.get("road") or addr.get("pedestrian") or addr.get("footway") or ""
            house_number = addr.get("house_number") or ""
            suburb = addr.get("suburb") or addr.get("neighbourhood") or ""
            city_district = addr.get("city_district") or ""
            city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("county") or ""
            admin = addr.get("state") or addr.get("county") or ""
            postcode = addr.get("postcode") or ""
            
            # POI 資訊
            amenity = addr.get("amenity") or extratags.get("amenity") or ""
            shop = addr.get("shop") or extratags.get("shop") or ""
            building = addr.get("building") or extratags.get("building") or ""
            
            # 組裝簡短標籤
            label_parts = []
            if name_zh and name_zh != road:
                label_parts.append(name_zh)
            
            if road and house_number:
                label_parts.append(f"{road}{house_number}號")
            elif road:
                label_parts.append(road)
            
            if city_district and city_district not in str(label_parts):
                label_parts.append(city_district)
            elif suburb and suburb not in str(label_parts):
                label_parts.append(suburb)
            
            # 添加城市/區域資訊
            if city and city not in str(label_parts):
                label_parts.append(city)
            
            label = ", ".join(filter(None, label_parts)) if label_parts else display_name
            
            # 組裝詳細地址
            detailed_parts = []
            if name_zh:
                detailed_parts.append(f"地點: {name_zh}")
            if road and house_number:
                detailed_parts.append(f"地址: {road}{house_number}號")
            elif road:
                detailed_parts.append(f"路段: {road}")
            if suburb:
                detailed_parts.append(f"區域: {suburb}")
            if city:
                detailed_parts.append(f"城市: {city}")
            if postcode:
                detailed_parts.append(f"郵遞區號: {postcode}")
            
            detailed_address = " | ".join(detailed_parts) if detailed_parts else label

            results.append({
                "lat": lat,
                "lon": lon,
                "display_name": display_name,
                "label": label,
                "detailed_address": detailed_address,
                "importance": importance,
                # 額外欄位供後續使用
                "name": name_zh or name,
                "road": road,
                "house_number": house_number,
                "suburb": suburb,
                "city_district": city_district,
                "city": city,
                "admin": admin,
                "postcode": postcode,
                "amenity": amenity,
                "shop": shop,
                "building": building,
            })

        # 最佳匹配（重要性最高）
        best_match = max(results, key=lambda x: x["importance"])

        payload = {
            "results": results,
            "best_match": best_match,
            "query": query
        }

        # 回寫快取（雙層）
        await db_cache.set_geo_cache(cache_key, payload)
        await set_geo_cache(cache_key, payload)

        logger.info(f"📍 Geocoding 成功: {query} → {best_match['label']} ({best_match['lat']:.4f}, {best_match['lon']:.4f})")

        # 組裝友善回覆
        content_parts = [f"找到地點：{best_match['label']}"]
        if len(results) > 1:
            content_parts.append(f"（共 {len(results)} 個結果，已選擇最相關的）")
        
        content = "\n".join(content_parts)

        return cls.create_success_response(content=content, data=payload)
