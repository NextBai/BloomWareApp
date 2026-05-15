"""
TDX 停車場與充電站查詢工具
查詢附近停車場、即時剩餘車位、充電站資訊
"""

import logging
from typing import Dict, Any, List, Optional

from ..base_tool import MCPTool, StandardToolSchemas, ExecutionError
from .tdx_base import TDXBaseAPI
from .tdx_location import resolve_location_context, resolve_city_code
from core.database import get_user_env_current

logger = logging.getLogger("mcp.tools.tdx.parking")


class TDXParkingTool(MCPTool):
    """TDX 停車場與充電站查詢"""
    
    NAME = "tdx_parking"
    DESCRIPTION = "Query nearby parking lots with real-time available spaces, pricing, and EV charging station information"
    CATEGORY = "停車與充電"
    TAGS = ["tdx", "停車", "充電站", "電動車"]
    KEYWORDS = ["停車", "停車場", "充電", "充電站", "車位", "電動車"]
    USAGE_TIPS = [
        "查詢附近停車場: 「附近哪裡有停車位」",
        "查詢充電站: 「附近的充電站在哪」",
        "指定停車場: 「台北車站停車場還有位子嗎」"
    ]
    
    @classmethod
    def get_input_schema(cls) -> Dict[str, Any]:
        return StandardToolSchemas.create_input_schema({
            "parking_name": {
                "type": "string",
                "description": "停車場名稱（如「台北車站」「市政府」）。不提供則查詢附近停車場"
            },
            "city": {
                "type": "string",
                "description": "城市代碼（如「Taipei」「Kaohsiung」）",
                "enum": ["Taipei", "NewTaipei", "Taoyuan", "Taichung", "Tainan", "Kaohsiung"]
            },
            "location_query": {
                "type": "string",
                "description": "精確地址、地標或路口（如「台北車站」「中正路100號」）。提供時優先解析為座標"
            },
            "parking_type": {
                "type": "string",
                "description": "停車場類型",
                "enum": ["路邊", "路外"]
            },
            "charge_station": {
                "type": "boolean",
                "description": "是否只查詢有充電站的停車場",
                "default": False
            },
            "radius_m": {
                "type": "integer",
                "description": "搜尋半徑（公尺）",
                "default": 1000
            },
            "limit": {
                "type": "integer",
                "description": "返回結果數量",
                "default": 5
            },
            "lat": {
                "type": "number",
                "description": "用戶緯度（由系統自動注入）"
            },
            "lon": {
                "type": "number",
                "description": "用戶經度（由系統自動注入）"
            }
        }, required=[])
    
    @classmethod
    def get_output_schema(cls) -> Dict[str, Any]:
        schema = StandardToolSchemas.create_output_schema()
        schema["properties"].update({
            "parkings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "parking_name": {"type": "string"},
                        "available_spaces": {"type": "integer"},
                        "total_spaces": {"type": "integer"},
                        "charge_station": {"type": "boolean"},
                        "fee_info": {"type": "string"}
                    }
                }
            }
        })
        return schema
    
    @classmethod
    async def execute(cls, arguments: Dict[str, Any]) -> Dict[str, Any]:
        # 從 arguments 中讀取 user_id（由 coordinator 注入）
        user_id = arguments.get("_user_id")
        
        parking_name = arguments.get("parking_name", "").strip()
        city = arguments.get("city")
        location_query = arguments.get("location_query", "").strip()
        parking_type = arguments.get("parking_type")
        charge_station_only = arguments.get("charge_station", False)
        radius_m = min(int(arguments.get("radius_m", 1000)), 5000)
        limit = min(int(arguments.get("limit", 5)), 20)
        
        # 1. 取得用戶位置和城市（優先從 arguments 讀取，由 coordinator 注入）
        user_lat = arguments.get("lat")
        user_lon = arguments.get("lon")
        user_city = arguments.get("city", "")
        
        logger.info(f"🅿️ [Parking] 輸入參數: lat={user_lat}, lon={user_lon}, city={user_city}, name={parking_name}, user_id={user_id}")
        
        # 從資料庫補充缺失的位置資訊（僅當 coordinator 沒有注入時）
        if user_id and (user_lat is None or user_lon is None):
            try:
                env_ctx = await get_user_env_current(user_id)
                logger.info(f"📍 [Parking] 資料庫查詢結果: {env_ctx}")
                if env_ctx and env_ctx.get("success"):
                    ctx = env_ctx.get("context", {})
                    if user_lat is None:
                        user_lat = ctx.get("lat")
                    if user_lon is None:
                        user_lon = ctx.get("lon")
                    if not user_city:
                        user_city = ctx.get("city", "")
                    logger.info(f"📍 [Parking] 補充後: lat={user_lat}, lon={user_lon}, city={user_city}")
                else:
                    logger.warning(f"⚠️ [Parking] 資料庫查詢失敗或無資料: {env_ctx}")
            except Exception as e:
                logger.warning(f"⚠️ [Parking] 資料庫查詢異常: {e}")
        
        # 檢查必要條件
        if not parking_name and (user_lat is None or user_lon is None):
            logger.error(f"🅿️ [Parking] 位置資訊缺失: lat={user_lat}, lon={user_lon}, parking_name={parking_name}")
            raise ExecutionError("🅿️ 想幫您找附近的停車場，但目前沒有您的位置資訊。請在 App 中開啟定位，或告訴我您想查詢哪個停車場")
        
        location_ctx = await resolve_location_context(
            lat=user_lat,
            lon=user_lon,
            location_query=location_query,
            city_like=city or user_city,
            allowed_city_codes={"Taipei", "NewTaipei", "Taoyuan", "Taichung", "Tainan", "Kaohsiung"},
        )
        user_lat = location_ctx["lat"]
        user_lon = location_ctx["lon"]
        city = resolve_city_code(city or user_city, allowed={"Taipei", "NewTaipei", "Taoyuan", "Taichung", "Tainan", "Kaohsiung"}) or location_ctx["city_code"] or "Taipei"
        logger.info(f"🏙️ 停車主城市: {city}")
        
        # 3. 查詢分支
        if charge_station_only:
            # 查詢充電站
            if not user_lat or not user_lon:
                raise ExecutionError("查詢充電站需要定位權限")
            result = await cls._query_charge_stations(user_lat, user_lon, radius_m, limit)
        elif parking_name:
            if not user_lat or not user_lon:
                raise ExecutionError("🅿️ 若要查特定停車場，請同時提供地址/地標或開啟定位，避免同名停車場誤判")
            result = await cls._query_named_parking_nearby(parking_name, user_lat, user_lon, radius_m, limit)
        else:
            # 查詢附近停車場
            if not user_lat or not user_lon:
                raise ExecutionError("查詢附近停車場需要定位權限")
            result = await cls._query_nearby_parkings(user_lat, user_lon, parking_type, radius_m, limit)
        
        return result
    
    @classmethod
    async def _query_named_parking_nearby(cls, parking_name: str, lat: float, lon: float, radius_m: int, limit: int) -> Dict[str, Any]:
        nearby = await cls._query_nearby_parkings(lat, lon, None, radius_m, max(limit * 3, 10))
        parkings = nearby.get("parkings", [])
        normalized = parking_name.strip()
        matched = [p for p in parkings if normalized in p.get("parking_name", "")]
        if not matched:
            raise ExecutionError(f"附近找不到停車場「{parking_name}」，請提供更精確的地標或放大範圍")

        best = matched[0]
        content = (
            f"🅿️ {best['parking_name']}\n"
            f"剩餘車位: {best['available_spaces']} / {best['total_spaces']}\n"
            f"收費: {best['fee_info']}\n"
            f"充電站: {'有' if best['charge_station'] else '無'}\n"
            f"步行: {best['walking_time_min']} 分鐘 ({best['distance_m']}m)\n"
        )
        return cls.create_success_response(content=content, data={"parking": best})
    
    @classmethod
    async def _query_nearby_parkings(cls, lat: float, lon: float,
                                     parking_type: Optional[str], radius_m: int, limit: int) -> Dict[str, Any]:
        """查詢附近停車場"""
        # 官方 Nearby 端點在 advanced/v1，不是 basic/v2/City 路徑
        if parking_type == "路邊":
            parking_endpoint = "Parking/OnStreet/ParkingSpot/NearBy"
        else:
            parking_endpoint = "Parking/OffStreet/CarPark/NearBy"

        parking_params = {
            "$spatialFilter": f"nearby({lat}, {lon}, {min(radius_m, 1000)})",
            "$format": "JSON",
            "$top": limit * 2
        }

        parkings = await TDXBaseAPI.call_api(parking_endpoint, parking_params, cache_ttl=3600, api_version="v1", api_family="advanced")
        
        if not parkings:
            return cls.create_success_response(
                content=f"附近 {radius_m} 公尺內沒有停車場",
                data={"parkings": []}
            )
        
        # 2. 計算距離並排序
        for parking in parkings:
            pos = parking.get("Position", {})
            if pos.get("PositionLat") and pos.get("PositionLon"):
                parking["distance_m"] = TDXBaseAPI.haversine_distance(
                    lat, lon,
                    pos["PositionLat"], pos["PositionLon"]
                )
        
        parkings = [p for p in parkings if "distance_m" in p]
        parkings.sort(key=lambda x: x["distance_m"])
        parkings = parkings[:limit]
        
        # 3. 路外 nearby 端點已含基礎資訊；即時剩餘車位目前若缺則保守留空，不用錯誤 city path 補查
        if parking_type != "路邊":
            avail_map = {}
        else:
            avail_map = {}
        
        # 4. 組合結果
        results = []
        for parking in parkings:
            parking_id = parking.get("CarParkID") or parking.get("ParkingSpaceID")
            parking_name = (parking.get("CarParkName") or parking.get("ParkingName") or {}).get("Zh_tw", "未知")
            distance = parking["distance_m"]
            walking_time = int(distance / 80)
            
            avail = avail_map.get(parking_id, {})
            total_spaces = parking.get("TotalSpaces", 0)
            available_spaces = avail.get("AvailableSpaces", 0)
            
            fee_info = cls._format_fee_info(parking.get("FareDescription", {}))
            
            results.append({
                "parking_name": parking_name,
                "available_spaces": available_spaces,
                "total_spaces": total_spaces,
                "distance_m": int(distance),
                "walking_time_min": walking_time,
                "charge_station": parking.get("HasChargingPoint", False),
                "fee_info": fee_info
            })
        
        content = cls._format_nearby_result(results, parking_type)
        
        return cls.create_success_response(
            content=content,
            data={"parkings": results}
        )
    
    @classmethod
    async def _query_charge_stations(cls, lat: float, lon: float,
                                    radius_m: int, limit: int) -> Dict[str, Any]:
        """查詢附近充電站"""
        # 官方 Nearby 端點在 advanced/v1
        parking_endpoint = "Parking/OffStreet/CarPark/NearBy"
        parking_params = {
            "$spatialFilter": f"nearby({lat}, {lon}, {min(radius_m, 1000)})",
            "$filter": "HasChargingPoint eq true",
            "$format": "JSON"
        }
        
        parkings = await TDXBaseAPI.call_api(parking_endpoint, parking_params, cache_ttl=3600, api_version="v1", api_family="advanced")
        
        if not parkings:
            return cls.create_success_response(
                content="此區域無充電站資訊",
                data={"charge_stations": []}
            )
        
        # 計算距離並過濾
        for parking in parkings:
            pos = parking.get("Position", {})
            if pos.get("PositionLat") and pos.get("PositionLon"):
                parking["distance_m"] = TDXBaseAPI.haversine_distance(
                    lat, lon,
                    pos["PositionLat"], pos["PositionLon"]
                )
        
        parkings = [p for p in parkings if "distance_m" in p and p["distance_m"] <= radius_m]
        parkings.sort(key=lambda x: x["distance_m"])
        parkings = parkings[:limit]
        
        if not parkings:
            return cls.create_success_response(
                content=f"附近 {radius_m} 公尺內沒有充電站",
                data={"charge_stations": []}
            )
        
        # 格式化結果
        results = []
        for parking in parkings:
            parking_name = parking.get("CarParkName", {}).get("Zh_tw", "未知")
            distance = parking["distance_m"]
            walking_time = int(distance / 80)
            
            results.append({
                "parking_name": parking_name,
                "distance_m": int(distance),
                "walking_time_min": walking_time,
                "address": parking.get("Address", ""),
                "total_spaces": parking.get("TotalSpaces", 0)
            })
        
        content = cls._format_charge_result(results)
        
        return cls.create_success_response(
            content=content,
            data={"charge_stations": results}
        )
    
    @staticmethod
    async def _reverse_geocode_city(lat: float, lon: float) -> Optional[str]:
        """使用 Nominatim 反向地理編碼取得精確城市"""
        import aiohttp
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://nominatim.openstreetmap.org/reverse",
                    params={"format": "jsonv2", "lat": lat, "lon": lon, "zoom": 10, "addressdetails": 1},
                    headers={"User-Agent": "BloomWare/1.0"},
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    addr = data.get("address", {}) if data else {}
                    city = addr.get("city") or addr.get("county") or addr.get("town") or ""
                    return city.replace("市", "").replace("縣", "").strip() or None
        except Exception:
            return None
    
    @staticmethod
    def _guess_city_from_location(lat: float, lon: float) -> str:
        """根據經緯度推斷城市（備用方案）"""
        city_bounds = [
            ("桃園", 24.73, 25.12, 120.90, 121.40),
            ("台北", 24.95, 25.10, 121.45, 121.62),
            ("新北", 24.67, 25.30, 121.35, 122.01),
            ("台中", 24.00, 24.45, 120.45, 121.05),
            ("台南", 22.85, 23.40, 120.00, 120.55),
            ("高雄", 22.45, 23.15, 120.15, 120.80),
        ]
        
        for city_name, lat_min, lat_max, lon_min, lon_max in city_bounds:
            if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
                return city_name
        
        return ""
    
    @staticmethod
    def _map_city_name(chinese_city: str) -> str:
        """中文城市名稱轉 TDX 代碼"""
        if not chinese_city:
            return "Taipei"
        
        city_map = {
            "台北": "Taipei", "臺北": "Taipei",
            "新北": "NewTaipei",
            "桃園": "Taoyuan",
            "台中": "Taichung", "臺中": "Taichung",
            "台南": "Tainan", "臺南": "Tainan",
            "高雄": "Kaohsiung"
        }
        
        for key, value in city_map.items():
            if key in chinese_city:
                return value
        
        return "Taipei"
    
    @staticmethod
    def _format_fee_info(fare_desc: Dict) -> str:
        """格式化收費資訊"""
        if not fare_desc:
            return "未提供"
        
        zh_tw = fare_desc.get("Zh_tw", "")
        if zh_tw:
            # 簡化長文字
            if len(zh_tw) > 50:
                return zh_tw[:47] + "..."
            return zh_tw
        
        return "未提供"
    
    @staticmethod
    def _format_nearby_result(parkings: List[Dict], parking_type: Optional[str]) -> str:
        """格式化附近停車場結果"""
        if not parkings:
            return "附近沒有停車場"
        
        type_emoji = "🅿️" if parking_type == "路外" else "🚗"
        lines = [f"📍 附近的停車場：\n"]
        
        for i, parking in enumerate(parkings, 1):
            charge_emoji = "⚡" if parking["charge_station"] else ""
            
            if parking["total_spaces"] > 0:
                avail_info = f"剩餘 {parking['available_spaces']}/{parking['total_spaces']}"
            else:
                avail_info = "無車位資訊"
            
            lines.append(
                f"{i}. {type_emoji} {parking['parking_name']} {charge_emoji}\n"
                f"   {avail_info}\n"
                f"   {parking['fee_info']}\n"
                f"   步行 {parking['walking_time_min']} 分鐘 ({parking['distance_m']}m)\n"
            )
        
        return "\n".join(lines)
    
    @staticmethod
    def _format_charge_result(stations: List[Dict]) -> str:
        """格式化充電站結果"""
        lines = ["⚡ 附近的充電站：\n"]
        
        for i, station in enumerate(stations, 1):
            lines.append(
                f"{i}. {station['parking_name']}\n"
                f"   步行 {station['walking_time_min']} 分鐘 ({station['distance_m']}m)\n"
                f"   {station['address']}\n"
            )
        
        return "\n".join(lines)
