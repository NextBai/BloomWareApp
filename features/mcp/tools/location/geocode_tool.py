"""
反地理與時區工具（免費 API 優先）
- reverse_geocode: 優先使用 TDX 官方定位服務，失敗時 fallback 到 Nominatim
"""

import aiohttp
import asyncio
import logging
from typing import Dict, Any
from urllib.parse import quote

from ..base_tool import MCPTool, StandardToolSchemas, ExecutionError
from core.database import get_geo_cache, set_geo_cache
from core.database.cache import db_cache
from ..transportation.tdx_base import TDXBaseAPI

logger = logging.getLogger("mcp.tools.geocode")


class ReverseGeocodeTool(MCPTool):
    NAME = "reverse_geocode"
    DESCRIPTION = "Convert coordinates (latitude/longitude) to city/district names (uses cache when available)"
    CATEGORY = "地理定位"
    TAGS = ["geocode", "reverse", "city"]
    KEYWORDS = ["座標", "經緯度", "反查", "地址", "我在哪"]
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
            "country_code": {"type": "string"},
            "address_display": {"type": "string"},
            "precision": {"type": "string"},
            "poi_label": {"type": "string"},
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
            # 補齊缺失欄位（兼容舊版快取）
            cached.setdefault("lat", lat)  # ← 補上座標
            cached.setdefault("lon", lon)  # ← 補上座標
            cached.setdefault("name", "")
            cached.setdefault("detailed_address", cached.get("label") or cached.get("display_name") or "")
            cached.setdefault("postcode", "")
            cached.setdefault("city_district", "")
            cached.setdefault("amenity", "")
            cached.setdefault("shop", "")
            cached.setdefault("building", "")
            cached.setdefault("office", "")
            cached.setdefault("leisure", "")
            cached.setdefault("tourism", "")
            
            return cls.create_success_response(
                content=cached.get("display_name") or f"{cached.get('city')}, {cached.get('admin')}",
                data=cached
            )

        # DB 快取
        db_cached = await get_geo_cache(geokey)
        if db_cached:
            # 補齊缺失欄位（兼容舊版快取）
            db_cached.setdefault("lat", lat)  # ← 補上座標
            db_cached.setdefault("lon", lon)  # ← 補上座標
            db_cached.setdefault("name", "")
            db_cached.setdefault("detailed_address", db_cached.get("label") or db_cached.get("display_name") or "")
            db_cached.setdefault("postcode", "")
            db_cached.setdefault("city_district", "")
            db_cached.setdefault("amenity", "")
            db_cached.setdefault("shop", "")
            db_cached.setdefault("building", "")
            db_cached.setdefault("office", "")
            db_cached.setdefault("leisure", "")
            db_cached.setdefault("tourism", "")
            
            await db_cache.set_geo_cache(geokey, db_cached)
            return cls.create_success_response(
                content=db_cached.get("display_name") or f"{db_cached.get('city')}, {db_cached.get('admin')}",
                data=db_cached
            )

        data = await cls._reverse_geocode_tdx(lat, lon)
        source = "tdx"
        if not data:
            data = await cls._reverse_geocode_nominatim(lat, lon)
            source = "nominatim"

        if data is None:
            raise ExecutionError("reverse geocode 無可用回應")

        if source == "tdx":
            addr = data.get("address", {}) or {}
            extratags = data.get("extratags", {}) or {}
        else:
            if not isinstance(data, dict):
                raise ExecutionError(f"Nominatim 回應格式錯誤: {type(data)}")
            if "error" in data:
                raise ExecutionError(f"Nominatim 錯誤: {data.get('error')}")
            addr = data.get("address") or {}
            extratags = data.get("extratags") or {}
        
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
        namedetails = data.get("namedetails") or {}
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

        address_display_parts = []
        if postcode:
            address_display_parts.append(postcode)
        if city:
            address_display_parts.append(city)
        if city_district:
            address_display_parts.append(city_district)
        elif suburb:
            address_display_parts.append(suburb)
        if road:
            address_display_parts.append(road)
        if house_number:
            address_display_parts.append(house_number)
        address_display = "".join(address_display_parts) or display_name or label

        if house_number and road:
            precision = "address"
        elif name_zh and (amenity or shop or building or office or tourism or leisure):
            precision = "poi"
        elif road:
            precision = "road"
        elif city_district or suburb:
            precision = "district"
        elif city:
            precision = "city"
        else:
            precision = "unknown"
        
        payload = {
            "lat": lat,
            "lon": lon,
            "city": city or "",
            "admin": admin or "",
            "country_code": country_code,
            "display_name": display_name,
            "label": label or display_name,
            "address_display": address_display,
            "detailed_address": detailed_address,
            "precision": precision,
            "poi_label": name_zh or name or label or "",
            "geocode_source": source,
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

    @staticmethod
    async def _reverse_geocode_tdx(lat: float, lon: float) -> Dict[str, Any] | None:
        try:
            endpoint = f"V3/Map/GeoLocating/Address/LocationX/{lon}/LocationY/{lat}"
            rows = await TDXBaseAPI.call_api(
                endpoint,
                {"$format": "JSON"},
                cache_ttl=86400,
                api_version="",
                api_family="advanced",
            )
            if isinstance(rows, list) and rows:
                row = rows[0]
                address = row.get("Address") or ""
                city = row.get("City") or ""
                town = row.get("Town") or ""
                road = row.get("RoadName") or ""
                house_number = str(row.get("AddressNo") or "").strip()
                return {
                    "display_name": address,
                    "address": {
                        "city": city,
                        "city_district": town,
                        "road": road,
                        "house_number": house_number,
                        "postcode": row.get("ZipCode") or "",
                        "country_code": "TW",
                    },
                    "name": row.get("LocationDescription") or row.get("LandMarkName") or "",
                    "namedetails": {},
                    "extratags": {},
                }
        except Exception as exc:
            logger.warning("TDX reverse geocode 失敗，回退 Nominatim: %s", exc)
        return None

    @staticmethod
    async def _reverse_geocode_nominatim(lat: float, lon: float) -> Dict[str, Any] | None:
        url = "https://nominatim.openstreetmap.org/reverse"
        params = {
            "format": "jsonv2",
            "lat": lat,
            "lon": lon,
            "zoom": 18,
            "addressdetails": 1,
            "extratags": 1,
            "namedetails": 1
        }
        headers = {
            "User-Agent": "BloomWare/1.0 (contact@example.com)"
        }
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, params=params, timeout=30) as resp:
                    if resp.status != 200:
                        raise ExecutionError(f"Nominatim 失敗: HTTP {resp.status}")
                    response_text = await resp.text()
                    if not response_text or response_text.strip() == "":
                        raise ExecutionError("Nominatim 回應為空")
                    import json
                    return json.loads(response_text)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            raise ExecutionError(f"Nominatim reverse geocode 失敗: {exc}") from exc
