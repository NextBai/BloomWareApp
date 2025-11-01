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
                    text = await resp.text()
                    raise ExecutionError(f"OpenRouteService HTTP {resp.status}: {text[:200]}")
                data = await resp.json()

        try:
            # 檢查 API 回應是否包含錯誤訊息
            if not isinstance(data, dict):
                raise ExecutionError(f"OpenRouteService 回應格式錯誤: 非字典類型")
            
            # 優先處理 error 欄位（API 標準錯誤格式）
            if "error" in data:
                error_payload = data["error"]
                if isinstance(error_payload, dict):
                    code = error_payload.get("code", "unknown")
                    message = error_payload.get("message", "未知錯誤")
                    raise ExecutionError(f"路線規劃失敗: {message} (錯誤碼: {code})")
                else:
                    raise ExecutionError(f"路線規劃失敗: {error_payload}")
            
            # 檢查是否有 features（標準成功格式）
            if "features" not in data or not data["features"]:
                # 提供友善的錯誤訊息
                if o_lat == d_lat and o_lon == d_lon:
                    raise ExecutionError("起點與終點相同，無需導航")
                else:
                    raise ExecutionError("找不到可行的路線，請確認起點與終點是否在可達範圍內")

            feat = data["features"][0]
            
            # 檢查必要欄位
            if "properties" not in feat or "summary" not in feat["properties"]:
                raise ExecutionError("路線資料缺少必要欄位（summary）")
            
            if "geometry" not in feat or "coordinates" not in feat["geometry"]:
                raise ExecutionError("路線資料缺少必要欄位（geometry）")
            
            summary = feat["properties"]["summary"]
            distance_m = float(summary["distance"])  # meters
            duration_s = float(summary["duration"])  # seconds
            polyline = feat["geometry"]["coordinates"]  # LineString 座標
            
            base_payload = {
                "distance_m": distance_m,
                "duration_s": duration_s,
                "polyline": json.dumps(polyline),
            }
        except ExecutionError:
            # 重新拋出已知錯誤
            raise
        except KeyError as e:
            # 捕捉欄位缺失錯誤，提供更友善的訊息
            raise ExecutionError(f"路線資料格式錯誤: 缺少欄位 {e}")
        except (ValueError, TypeError) as e:
            # 捕捉資料型別轉換錯誤
            raise ExecutionError(f"路線資料解析失敗: {e}")
        except Exception as e:
            # 捕捉所有其他未預期錯誤
            logger.error(f"❌ ORS 回應解析異常: {e}", exc_info=True)
            raise ExecutionError(f"路線資料處理失敗: {type(e).__name__}: {e}")

        # 回寫快取
        await db_cache.set_route_cache(key, base_payload)
        await set_route_cache(key, base_payload)

        return cls.create_success_response(
            content=f"距離 {int(distance_m)}m，約 {int(duration_s/60)} 分鐘",
            data=_attach_labels(base_payload),
        )
