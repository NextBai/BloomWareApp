"""
路徑規劃工具（OpenRouteService）
使用免費 ORS API，搭配 DB/記憶體快取
"""

import os
import json
import logging
import re
import aiohttp
from typing import Dict, Any

from .base_tool import MCPTool, StandardToolSchemas, ExecutionError, ValidationError
from core.config import settings
from core.database import get_route_cache, set_route_cache
from core.database.cache import db_cache

logger = logging.getLogger("mcp.tools.directions")

ORS_API_KEY = os.getenv("OPENROUTESERVICE_API_KEY", "")


class DirectionsTool(MCPTool):
    NAME = "directions"
    DESCRIPTION = "規劃兩點之間的路線（walk/drive/cycle），返回距離、時間與 polyline"
    CATEGORY = "地理"
    TAGS = ["route", "navigation", "directions"]
    USAGE_TIPS = ["提供起訖兩點經緯度"]
    _COORDINATE_FIELDS = {
        "origin_lat": "起點緯度",
        "origin_lon": "起點經度",
        "dest_lat": "目的地緯度",
        "dest_lon": "目的地經度",
    }

    @classmethod
    def get_input_schema(cls) -> Dict[str, Any]:
        return StandardToolSchemas.create_input_schema({
            "origin_lat": {"type": "number"},
            "origin_lon": {"type": "number"},
            "dest_lat": {"type": "number"},
            "dest_lon": {"type": "number"},
            "mode": {"type": "string", "enum": ["driving-car", "foot-walking", "cycling-regular"], "default": "foot-walking"},
            "origin_label": {"type": "string"},
            "dest_label": {"type": "string"},
        }, required=["origin_lat", "origin_lon", "dest_lat", "dest_lon"])

    @classmethod
    def get_output_schema(cls) -> Dict[str, Any]:
        schema = StandardToolSchemas.create_output_schema()
        schema["properties"].update({
            "distance_m": {"type": "number"},
            "duration_s": {"type": "number"},
            "polyline": {"type": "string"},
            "origin_label": {"type": "string"},
            "dest_label": {"type": "string"},
        })
        return schema

    @classmethod
    def _parse_coordinate(cls, field: str, value: Any) -> float:
        """將輸入座標柔性轉為浮點數，必要時嘗試從字串萃取第一個數字。"""
        if value is None:
            raise ValidationError(field, f"{cls._COORDINATE_FIELDS[field]}不得為空")

        if isinstance(value, (int, float)):
            return float(value)

        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise ValidationError(field, f"{cls._COORDINATE_FIELDS[field]}不得為空")

            match = re.search(r"-?\d+(?:\.\d+)?", stripped.replace(",", " "))
            if match:
                try:
                    return float(match.group())
                except (TypeError, ValueError):
                    pass

        raise ValidationError(field, f"{cls._COORDINATE_FIELDS[field]}需為有效的數值座標")

    @classmethod
    def validate_input(cls, arguments: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(arguments or {})

        for field in cls._COORDINATE_FIELDS:
            if field not in normalized:
                raise ValidationError(field, f"{cls._COORDINATE_FIELDS[field]}缺失，請提供完整座標")
            normalized[field] = cls._parse_coordinate(field, normalized[field])

        mode = normalized.get("mode")
        if isinstance(mode, str) and not mode.strip():
            normalized.pop("mode")

        try:
            return super().validate_input(normalized)
        except ValidationError as exc:
            # 補上更友善的錯誤訊息
            message = str(exc)
            for field, description in cls._COORDINATE_FIELDS.items():
                if field in message:
                    raise ValidationError(field, f"{description}需為有效的數值座標")
            raise

    @classmethod
    async def execute(cls, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if not ORS_API_KEY:
            raise ExecutionError("未設定 OPENROUTESERVICE_API_KEY")

        o_lat = float(arguments.get("origin_lat"))
        o_lon = float(arguments.get("origin_lon"))
        d_lat = float(arguments.get("dest_lat"))
        d_lon = float(arguments.get("dest_lon"))
        mode = arguments.get("mode", "foot-walking")
        origin_label = (arguments.get("origin_label") or "").strip()
        dest_label = (arguments.get("dest_label") or "").strip()

        def _attach_labels(data: Dict[str, Any]) -> Dict[str, Any]:
            enriched = dict(data)
            if origin_label:
                enriched["origin_label"] = origin_label
            if dest_label:
                enriched["dest_label"] = dest_label
            return enriched

        # 快取鍵（geohash 簡化）
        try:
            from geohash2 import encode as gh_encode
            key = f"{gh_encode(o_lat, o_lon, precision=7)}->{gh_encode(d_lat, d_lon, precision=7)}#{mode}"
        except Exception:
            key = f"{round(o_lat,4)},{round(o_lon,4)}->{round(d_lat,4)},{round(d_lon,4)}#{mode}"

        cached = await db_cache.get_route_cached(key)
        if cached:
            cached_payload = _attach_labels(cached)
            return cls.create_success_response(
                content=f"距離 {int(cached['distance_m'])}m，約 {int(cached['duration_s']/60)} 分鐘",
                data=cached_payload,
            )

        db_cached = await get_route_cache(key)
        if db_cached:
            await db_cache.set_route_cache(key, db_cached)
            db_payload = _attach_labels(db_cached)
            return cls.create_success_response(
                content=f"距離 {int(db_cached['distance_m'])}m，約 {int(db_cached['duration_s']/60)} 分鐘",
                data=db_payload,
            )

        # 呼叫 ORS Directions
        url = f"https://api.openrouteservice.org/v2/directions/{mode}"
        headers = {"Authorization": ORS_API_KEY, "Content-Type": "application/json"}
        body = {
            "coordinates": [
                [o_lon, o_lat],
                [d_lon, d_lat]
            ]
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=json.dumps(body), timeout=15) as resp:
                if resp.status != 200:
                    raise ExecutionError(f"ORS 失敗: HTTP {resp.status}")
                data = await resp.json()

        try:
            feat = data["features"][0]
            summary = feat["properties"]["summary"]
            distance_m = float(summary["distance"])  # meters
            duration_s = float(summary["duration"])  # seconds
            polyline = feat["geometry"]["coordinates"]  # LineString 座標
            base_payload = {
                "distance_m": distance_m,
                "duration_s": duration_s,
                "polyline": json.dumps(polyline),
            }
        except Exception as e:
            raise ExecutionError(f"解析 ORS 回應失敗: {e}")

        # 回寫快取
        await db_cache.set_route_cache(key, base_payload)
        await set_route_cache(key, base_payload)

        return cls.create_success_response(
            content=f"距離 {int(distance_m)}m，約 {int(duration_s/60)} 分鐘",
            data=_attach_labels(base_payload),
        )
