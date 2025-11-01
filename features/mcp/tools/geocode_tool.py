"""
反地理與時區工具（免費 API 優先）
- reverse_geocode: 使用 Nominatim（OSM）反查城市/行政區（先查 DB/記憶體快取）
"""

import aiohttp
import asyncio
import logging
from typing import Dict, Any

from .base_tool import MCPTool, StandardToolSchemas, ExecutionError
from core.database import get_geo_cache, set_geo_cache
from core.database.cache import db_cache

logger = logging.getLogger("mcp.tools.geocode")


class ReverseGeocodeTool(MCPTool):
    NAME = "reverse_geocode"
    DESCRIPTION = "以經緯度反查城市/行政區（優先使用快取）"
    CATEGORY = "地理"
    TAGS = ["geocode", "reverse", "city"]
    USAGE_TIPS = ["提供 lat/lon 即可"]

    @classmethod
    def get_input_schema(cls) -> Dict[str, Any]:
        return StandardToolSchemas.create_input_schema({
            "lat": {"type": "number", "description": "緯度"},
            "lon": {"type": "number", "description": "經度"}
        }, required=["lat", "lon"])

    @classmethod
    def get_output_schema(cls) -> Dict[str, Any]:
        schema = StandardToolSchemas.create_output_schema()
        schema["properties"].update({
            "city": {"type": "string"},
            "admin": {"type": "string"},
            "country_code": {"type": "string"}
        })
        return schema

    @classmethod
    async def execute(cls, arguments: Dict[str, Any]) -> Dict[str, Any]:
        lat = arguments.get("lat")
        lon = arguments.get("lon")
        if lat is None or lon is None:
            raise ExecutionError("缺少經緯度")

        # 先用 geohash7 當鍵查快取
        try:
            from geohash2 import encode as gh_encode
            geokey = gh_encode(lat, lon, precision=7)
        except Exception:
            geokey = f"{round(lat,4)},{round(lon,4)}"

        # 記憶體快取
        cached = await db_cache.get_geo_cached(geokey)
        if cached:
            return cls.create_success_response(
                content=cached.get("display_name") or f"{cached.get('city')}, {cached.get('admin')}",
                data=cached
            )

        # DB 快取
        db_cached = await get_geo_cache(geokey)
        if db_cached:
            await db_cache.set_geo_cache(geokey, db_cached)
            return cls.create_success_response(
                content=db_cached.get("display_name") or f"{db_cached.get('city')}, {db_cached.get('admin')}",
                data=db_cached
            )

        # 外呼 Nominatim（公共端點，務必節流）
        url = "https://nominatim.openstreetmap.org/reverse"
        params = {
            "format": "jsonv2",
            "lat": lat,
            "lon": lon,
            "zoom": 18,  # 提高 zoom 等級（18 = 建築物級別，可取得門牌號）
            "addressdetails": 1,
            "extratags": 1,  # 取得額外標籤（商店名稱、建築物類型等）
            "namedetails": 1  # 取得多語言名稱
        }
        headers = {
            "User-Agent": "BloomWare/1.0 (contact@example.com)"
        }

        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status != 200:
                    raise ExecutionError(f"Nominatim 失敗: {resp.status}")
                data = await resp.json()
                
                addr = data.get("address", {})
                extratags = data.get("extratags", {})
                
                # 基本地址組件
                road = addr.get("road") or addr.get("pedestrian") or addr.get("footway") or addr.get("cycleway") or ""
                house_number = addr.get("house_number") or ""
                suburb = addr.get("suburb") or addr.get("neighbourhood") or addr.get("quarter") or ""
                city_district = addr.get("city_district") or ""
                city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("county") or ""
                admin = addr.get("state") or addr.get("county") or ""
                country_code = (addr.get("country_code") or "").upper()
                postcode = addr.get("postcode") or ""
                
                # POI 資訊（商店、建築物、設施等）
                amenity = addr.get("amenity") or extratags.get("amenity") or ""
                shop = addr.get("shop") or extratags.get("shop") or ""
                building = addr.get("building") or extratags.get("building") or ""
                office = addr.get("office") or extratags.get("office") or ""
                leisure = addr.get("leisure") or extratags.get("leisure") or ""
                tourism = addr.get("tourism") or extratags.get("tourism") or ""
                
                # 地點名稱（優先使用繁中）
                name = data.get("name") or ""
                namedetails = data.get("namedetails", {})
                name_zh = namedetails.get("name:zh") or namedetails.get("name:zh-TW") or name
                
                display_name = data.get("display_name") or ""
                
                # 組裝精確標籤（優先顯示最精確的資訊）
                label_parts = []
                
                # 1. POI 名稱（如「7-11 明倫門市」「台北101」）
                if name_zh and name_zh != road:
                    label_parts.append(name_zh)
                
                # 2. 門牌號碼 + 路名（如「中正路123號」）
                if road and house_number:
                    label_parts.append(f"{road}{house_number}號")
                elif road:
                    # 如果沒有門牌，但有路口資訊
                    if "路口" in road or "交叉口" in road or "intersection" in road.lower():
                        label_parts.append(road)
                    else:
                        # 嘗試從附近找路口
                        label_parts.append(road)
                
                # 3. 郵遞區號（如「100」）
                if postcode and len(label_parts) > 0:
                    label_parts[0] = f"〒{postcode} {label_parts[0]}"
                
                # 4. 區域（如「大安區」）
                if city_district and city_district not in label_parts:
                    label_parts.append(city_district)
                elif suburb and suburb not in label_parts:
                    label_parts.append(suburb)
                
                # 5. 城市（如「台北市」）
                if city and city not in label_parts:
                    label_parts.append(city)
                
                # 6. 省份/州（如「台灣」）
                if admin and admin not in city and admin not in label_parts:
                    label_parts.append(admin)
                
                label = ", ".join(filter(None, label_parts))
                
                # 組裝詳細地址（用於 AI 顯示）
                detailed_address_parts = []
                if name_zh:
                    detailed_address_parts.append(f"地點: {name_zh}")
                if road and house_number:
                    detailed_address_parts.append(f"地址: {road}{house_number}號")
                elif road:
                    detailed_address_parts.append(f"路段: {road}")
                if suburb:
                    detailed_address_parts.append(f"區域: {suburb}")
                if city:
                    detailed_address_parts.append(f"城市: {city}")
                if postcode:
                    detailed_address_parts.append(f"郵遞區號: {postcode}")
                
                detailed_address = " | ".join(detailed_address_parts) if detailed_address_parts else label
                
                payload = {
                    "city": city or "",
                    "admin": admin or "",
                    "country_code": country_code,
                    "display_name": display_name,
                    "label": label or display_name,
                    "detailed_address": detailed_address,
                    "road": road,
                    "house_number": house_number,
                    "suburb": suburb,
                    "city_district": city_district,
                    "postcode": postcode,
                    "amenity": amenity,
                    "shop": shop,
                    "building": building,
                    "office": office,
                    "leisure": leisure,
                    "tourism": tourism,
                    "name": name_zh or name,
                }

        # 回寫快取
        await db_cache.set_geo_cache(geokey, payload)
        await set_geo_cache(geokey, payload)

        return cls.create_success_response(content=payload.get("label") or f"{payload['city']}, {payload['admin']}", data=payload)
