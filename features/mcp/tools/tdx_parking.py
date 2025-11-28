"""
TDX 停車場與充電站查詢工具
查詢附近停車場、即時剩餘車位、充電站資訊
"""

import logging
from typing import Dict, Any, List, Optional

from .base_tool import MCPTool, StandardToolSchemas, ExecutionError
from .tdx_base import TDXBaseAPI
from core.database import get_user_env_current

logger = logging.getLogger("mcp.tools.tdx.parking")


class TDXParkingTool(MCPTool):
    """TDX 停車場與充電站查詢"""
    
    NAME = "tdx_parking"
    DESCRIPTION = "查詢附近停車場、即時剩餘車位、收費標準、充電站資訊"
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
        
        # 2. 自動判斷城市（優先使用反向地理編碼）
        if not city:
            final_city = None
            city_source = "預設"
            
            # 優先：即時反向地理編碼
            if user_lat and user_lon:
                geocoded = await cls._reverse_geocode_city(user_lat, user_lon)
                if geocoded:
                    final_city = geocoded
                    city_source = "反向地理編碼"
            
            # 其次：環境參數
            if not final_city and user_city:
                final_city = user_city
                city_source = "環境參數"
            
            # 最後：經緯度範圍推斷
            if not final_city and user_lat and user_lon:
                guessed = cls._guess_city_from_location(user_lat, user_lon)
                if guessed:
                    final_city = guessed
                    city_source = "經緯度推斷"
            
            city = cls._map_city_name(final_city) if final_city else "Taipei"
            logger.info(f"🏙️ 最終使用城市代碼: {city} (來源={city_source})")
        
        # 3. 查詢分支
        if charge_station_only:
            # 查詢充電站
            if not user_lat or not user_lon:
                raise ExecutionError("查詢充電站需要定位權限")
            result = await cls._query_charge_stations(user_lat, user_lon, city, radius_m, limit)
        elif parking_name:
            # 查詢特定停車場
            result = await cls._query_parking_availability(parking_name, city)
        else:
            # 查詢附近停車場
            if not user_lat or not user_lon:
                raise ExecutionError("查詢附近停車場需要定位權限")
            result = await cls._query_nearby_parkings(user_lat, user_lon, city, parking_type, radius_m, limit)
        
        return result
    
    @classmethod
    async def _query_parking_availability(cls, parking_name: str, city: str) -> Dict[str, Any]:
        """查詢特定停車場即時資訊"""
        # 1. 查詢停車場基本資訊 (v2 API)
        # GET /v2/Parking/OffStreet/CarPark/City/{City}
        parking_endpoint = f"Parking/OffStreet/CarPark/City/{city}"
        parking_params = {
            "$filter": f"contains(CarParkName/Zh_tw, '{parking_name}')",
            "$format": "JSON",
            "$top": 5
        }
        
        parkings = await TDXBaseAPI.call_api(parking_endpoint, parking_params, cache_ttl=3600)
        
        if not parkings:
            raise ExecutionError(f"找不到停車場「{parking_name}」")
        
        # 2. 取得第一個結果
        parking = parkings[0]
        parking_id = parking.get("CarParkID")
        full_parking_name = parking.get("CarParkName", {}).get("Zh_tw", parking_name)
        
        # 3. 查詢即時剩餘車位 (v2 API)
        # GET /v2/Parking/OffStreet/ParkingAvailability/City/{City}
        avail_endpoint = f"Parking/OffStreet/ParkingAvailability/City/{city}"
        avail_params = {
            "$filter": f"CarParkID eq '{parking_id}'",
            "$format": "JSON"
        }
        
        availability = await TDXBaseAPI.call_api(avail_endpoint, avail_params, cache_ttl=60)
        
        # 4. 組合資訊
        total_spaces = parking.get("TotalSpaces", 0)
        available_spaces = 0
        
        if availability and len(availability) > 0:
            avail = availability[0]
            available_spaces = avail.get("AvailableSpaces", 0)
        
        # 收費資訊
        fee_info = cls._format_fee_info(parking.get("FareDescription", {}))
        
        # 充電站資訊
        has_charge = parking.get("HasChargingPoint", False)
        
        result = {
            "parking_name": full_parking_name,
            "available_spaces": available_spaces,
            "total_spaces": total_spaces,
            "charge_station": has_charge,
            "fee_info": fee_info,
            "address": parking.get("Address", ""),
            "service_time": parking.get("ServiceTime", "")
        }
        
        # 5. 格式化結果
        content = (
            f"🅿️ {result['parking_name']}\n"
            f"剩餘車位: {result['available_spaces']} / {result['total_spaces']}\n"
            f"收費: {result['fee_info']}\n"
            f"充電站: {'有' if result['charge_station'] else '無'}\n"
            f"地址: {result['address']}\n"
        )
        
        return cls.create_success_response(
            content=content,
            data={"parking": result}
        )
    
    @classmethod
    async def _query_nearby_parkings(cls, lat: float, lon: float, city: str,
                                     parking_type: Optional[str], radius_m: int, limit: int) -> Dict[str, Any]:
        """查詢附近停車場"""
        # 1. 查詢附近停車場 (v2 API)
        # GET /v2/Parking/OffStreet/CarPark/City/{City}
        # GET /v2/Parking/OnStreet/ParkingSpace/City/{City}
        if parking_type == "路邊":
            parking_endpoint = f"Parking/OnStreet/ParkingSpace/City/{city}"
        else:
            parking_endpoint = f"Parking/OffStreet/CarPark/City/{city}"
        
        parking_params = {
            "$spatialFilter": f"nearby({lat}, {lon}, {radius_m})",
            "$format": "JSON",
            "$top": limit * 2
        }
        
        parkings = await TDXBaseAPI.call_api(parking_endpoint, parking_params, cache_ttl=3600)
        
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
        
        # 3. 批次查詢即時車位（僅路外停車場）(v2 API)
        # GET /v2/Parking/OffStreet/ParkingAvailability/City/{City}
        if parking_type != "路邊":
            parking_ids = [p.get("CarParkID") for p in parkings]
            
            avail_endpoint = f"Parking/OffStreet/ParkingAvailability/City/{city}"
            avail_params = {
                "$filter": " or ".join([f"CarParkID eq '{pid}'" for pid in parking_ids if pid]),
                "$format": "JSON"
            }
            
            availability = await TDXBaseAPI.call_api(avail_endpoint, avail_params, cache_ttl=60)
            
            # 建立 ID -> 可用性 映射
            avail_map = {a.get("CarParkID"): a for a in availability}
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
    async def _query_charge_stations(cls, lat: float, lon: float, city: str,
                                    radius_m: int, limit: int) -> Dict[str, Any]:
        """查詢附近充電站"""
        # 查詢有充電站的停車場 (v2 API)
        # GET /v2/Parking/OffStreet/CarPark/City/{City}
        parking_endpoint = f"Parking/OffStreet/CarPark/City/{city}"
        parking_params = {
            "$filter": "HasChargingPoint eq true",
            "$format": "JSON"
        }
        
        parkings = await TDXBaseAPI.call_api(parking_endpoint, parking_params, cache_ttl=3600)
        
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
