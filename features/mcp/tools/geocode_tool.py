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
            "zoom": 10,
            "addressdetails": 1
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
                city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("county")
                admin = addr.get("state") or addr.get("county") or ""
                country_code = (addr.get("country_code") or "").upper()
                display_name = data.get("display_name") or ""
                road = addr.get("road") or addr.get("pedestrian") or addr.get("footway") or ""
                house_number = addr.get("house_number") or ""
                suburb = addr.get("suburb") or addr.get("neighbourhood") or ""
                label_parts = []
                if road and house_number:
                    label_parts.append(f"{road}{house_number}")
                elif road:
                    label_parts.append(road)
                if suburb:
                    label_parts.append(suburb)
                if city:
                    label_parts.append(city)
                if admin:
                    label_parts.append(admin)
                label = ", ".join(label_parts)
                payload = {
                    "city": city or "",
                    "admin": admin or "",
                    "country_code": country_code,
                    "display_name": display_name,
                    "label": label or display_name,
                    "road": road,
                    "house_number": house_number,
                    "suburb": suburb,
                }

        # 回寫快取
        await db_cache.set_geo_cache(geokey, payload)
        await set_geo_cache(geokey, payload)

        return cls.create_success_response(content=payload.get("label") or f"{payload['city']}, {payload['admin']}", data=payload)
