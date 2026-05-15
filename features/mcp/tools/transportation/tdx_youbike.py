"""
TDX YouBike 即時查詢工具
查詢附近 YouBike 站點、即時車輛數、空位數
"""

import logging
from typing import Dict, Any, List, Optional

from ..base_tool import MCPTool, StandardToolSchemas, ExecutionError
from .tdx_base import TDXBaseAPI
from .tdx_location import resolve_location_context, resolve_city_code, resolve_city_candidates
from core.database import get_user_env_current

logger = logging.getLogger("mcp.tools.tdx.bike")


class TDXBikeTool(MCPTool):
    """TDX YouBike 即時查詢"""
    
    NAME = "tdx_youbike"
    DESCRIPTION = """Query nearby YouBike stations with real-time available bikes and parking spaces (supports YouBike 1.0/2.0).
IMPORTANT Parameter Extraction Rules:
1. "nearby YouBike" -> leave station_name and city empty (use GPS)
2. "[station] YouBike" or "any bikes at [station]" -> station_name="[station]" (leave city empty)
3. "Taipei YouBike" -> city="Taipei"
Only fill city if explicitly mentioned! Station names can be in Chinese."""
    CATEGORY = "微型運具"
    TAGS = ["tdx", "youbike", "ubike", "共享單車", "微笑單車"]
    KEYWORDS = [
        "YouBike", "Youbike", "youbike", "YOUBIKE",
        "UBike", "Ubike", "ubike", "UBIKE",
        "微笑單車", "共享單車", "公共單車",
        "腳踏車站", "單車站", "自行車站",
        "借車", "還車", "腳踏車"
    ]
    USAGE_TIPS = [
        "「附近的 YouBike」→ 查詢最近站點",
        "「Ubike 在哪」→ 查詢最近站點",
        "「市政府 YouBike 還有車嗎」→ station_name=市政府"
    ]
    NEGATIVE_EXAMPLES = [
        "「YouBike 怎麼註冊」→ 這是詢問註冊方式，不是查站點",
        "「YouBike 費率」→ 這是詢問價格，不是查站點"
    ]
    PRIORITY = 6
    ALIASES = ["youbike", "ubike", "微笑單車", "共享單車"]
    
    # 城市對應
    CITY_MAP = {
        "台北": "Taipei",
        "臺北": "Taipei",
        "新北": "NewTaipei",
        "桃園": "Taoyuan",
        "台中": "Taichung",
        "臺中": "Taichung",
        "台南": "Tainan",
        "臺南": "Tainan",
        "高雄": "Kaohsiung",
        "新竹": "Hsinchu"
    }
    
    @classmethod
    def get_input_schema(cls) -> Dict[str, Any]:
        # 建立包含中文和英文的城市列表
        all_cities = list(cls.CITY_MAP.keys()) + list(cls.CITY_MAP.values())
        # 去重並保持順序
        unique_cities = []
        seen = set()
        for city in all_cities:
            if city not in seen:
                unique_cities.append(city)
                seen.add(city)
        
        return StandardToolSchemas.create_input_schema({
            "station_name": {
                "type": "string",
                "description": "站點名稱（如「市政府」「台北車站」）。不提供則查詢附近站點"
            },
            "city": {
                "type": "string",
                "description": "城市名稱（支援中文如「台北」「桃園」或英文如「Taipei」「Taoyuan」）",
                "enum": unique_cities
            },
            "location_query": {
                "type": "string",
                "description": "精確地址、路口或地標（如「桃園火車站」「中正路100號」）。提供時優先解析為座標做附近查詢"
            },
            "radius_m": {
                "type": "integer",
                "description": "搜尋半徑（公尺）",
                "default": 500
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
            "stations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "station_name": {"type": "string"},
                        "available_bikes": {"type": "integer"},
                        "available_spaces": {"type": "integer"},
                        "distance_m": {"type": "integer"},
                        "bike_type": {"type": "string"}
                    }
                }
            }
        })
        return schema
    
    @classmethod
    async def execute(cls, arguments: Dict[str, Any]) -> Dict[str, Any]:
        # 安全取得字串參數
        def safe_str(val) -> str:
            if val is None:
                return ""
            if isinstance(val, dict):
                return ""
            return str(val).strip()

        # 從 arguments 中讀取 user_id（由 coordinator 注入）
        user_id = arguments.get("_user_id")
        
        station_name = safe_str(arguments.get("station_name"))
        city = arguments.get("city")
        location_query = safe_str(arguments.get("location_query"))
        
        # 如果 city 是中文，轉換為英文
        if city:
            city = resolve_city_code(city, allowed=cls.CITY_MAP.values()) or cls._map_city_name(city)
        
        radius_m = min(int(arguments.get("radius_m", 500)), 2000)
        limit = min(int(arguments.get("limit", 5)), 20)
        
        # 1. 取得用戶位置和城市（優先從 arguments 讀取，由 coordinator 注入）
        user_lat = arguments.get("lat")
        user_lon = arguments.get("lon")
        user_city = safe_str(arguments.get("city"))
        
        logger.info(f"🚲 [YouBike] 輸入參數: lat={user_lat}, lon={user_lon}, city={user_city}, station={station_name}, user_id={user_id}")
        
        # 從資料庫補充缺失的位置資訊（僅當 coordinator 沒有注入時）
        if user_id and (user_lat is None or user_lon is None):
            try:
                env_ctx = await get_user_env_current(user_id)
                logger.info(f"📍 [YouBike] 資料庫查詢結果: {env_ctx}")
                if env_ctx and env_ctx.get("success"):
                    ctx = env_ctx.get("context", {})
                    if user_lat is None:
                        user_lat = ctx.get("lat")
                    if user_lon is None:
                        user_lon = ctx.get("lon")
                    if not user_city:
                        user_city = safe_str(ctx.get("city"))
                    logger.info(f"📍 [YouBike] 補充後: lat={user_lat}, lon={user_lon}, city={user_city}")
                else:
                    logger.warning(f"⚠️ [YouBike] 資料庫查詢失敗或無資料: {env_ctx}")
            except Exception as e:
                logger.warning(f"⚠️ [YouBike] 資料庫查詢異常: {e}")
        
        location_ctx = await resolve_location_context(
            lat=user_lat,
            lon=user_lon,
            location_query=location_query,
            city_like=city or user_city,
            allowed_city_codes=set(cls.CITY_MAP.values()),
        )
        user_lat = location_ctx["lat"]
        user_lon = location_ctx["lon"]
        geo = location_ctx.get("geo") or {}
        city = city or location_ctx["city_code"]
        city_candidates = resolve_city_candidates(
            city_like=city or user_city,
            geo_city=geo.get("city"),
            geo_admin=geo.get("admin"),
            allowed_city_codes=set(cls.CITY_MAP.values()),
        )

        # 檢查必要條件
        if not station_name and (user_lat is None or user_lon is None):
            logger.error(f"🚲 [YouBike] 位置資訊缺失: lat={user_lat}, lon={user_lon}, station_name={station_name}, location_query={location_query}")
            raise ExecutionError("🚲 想幫您找附近的 YouBike，但目前沒有您的位置資訊。請在 App 中開啟定位，或直接提供地址/地標（例如：桃園火車站、台北101）")

        if not city:
            final_city = (location_ctx.get("geo") or {}).get("city") or (location_ctx.get("geo") or {}).get("admin") or user_city
            if final_city:
                nearest_city = cls._find_nearest_supported_city(user_lat, user_lon) if user_lat and user_lon else "台北"
                raise ExecutionError(
                    f"🚲 很抱歉，{final_city}目前無法對應到支援的 YouBike 城市。\n\n"
                    f"最近有 YouBike 的城市可能是：{nearest_city}\n"
                    f"支援 YouBike 的城市：台北、新北、桃園、新竹、台中、台南、高雄"
                )
            city = "Taipei"

        logger.info(f"🏙️ 最終使用城市代碼: {city}")
        
        # 3. 查詢分支
        if station_name:
            result = await cls._query_station_availability(station_name, city)
        else:
            if not user_lat or not user_lon:
                logger.error(f"🚲 [YouBike] 查詢附近站點但位置缺失: lat={user_lat}, lon={user_lon}")
                raise ExecutionError("🚲 想幫您找附近的 YouBike，但目前沒有您的位置資訊。請在 App 中開啟定位功能")
            result = await cls._query_nearby_stations(user_lat, user_lon, city_candidates, radius_m, limit)
        
        return result
    
    @classmethod
    async def _query_station_availability(cls, station_name: str, city: str) -> Dict[str, Any]:
        """查詢特定站點即時資訊"""
        # 1. 查詢站點基本資訊 (v2 API)
        # GET /v2/Bike/Station/City/{City}
        station_endpoint = f"Bike/Station/City/{city}"
        station_params = {
            "$filter": f"contains(StationName/Zh_tw, '{station_name}')",
            "$format": "JSON",
            "$top": 5
        }
        
        stations = await TDXBaseAPI.call_api(station_endpoint, station_params, cache_ttl=1800)
        
        if not stations:
            raise ExecutionError(f"找不到站點「{station_name}」")
        
        # 2. 取得完全匹配或第一個結果
        target_station = None
        for station in stations:
            name = station.get("StationName", {}).get("Zh_tw", "")
            if station_name in name:
                target_station = station
                break
        
        if not target_station:
            target_station = stations[0]
        
        station_uid = target_station.get("StationUID")
        full_station_name = target_station.get("StationName", {}).get("Zh_tw", station_name)
        
        # 3. 查詢即時可用車輛數 (v2 API)
        # GET /v2/Bike/Availability/City/{City}
        avail_endpoint = f"Bike/Availability/City/{city}"
        avail_params = {
            "$filter": f"StationUID eq '{station_uid}'",
            "$format": "JSON"
        }
        
        availability = await TDXBaseAPI.call_api(avail_endpoint, avail_params, cache_ttl=30)
        
        if not availability or len(availability) == 0:
            return cls.create_success_response(
                content=f"🚲 {full_station_name} 目前無即時資訊",
                data={"stations": []}
            )
        
        avail = availability[0]
        
        result = {
            "station_name": full_station_name,
            "available_bikes": avail.get("AvailableRentBikes", 0),
            "available_spaces": avail.get("AvailableReturnBikes", 0),
            "service_status": avail.get("ServiceStatus", 1),
            "update_time": avail.get("UpdateTime", ""),
            "bike_type": cls._detect_bike_type(target_station, full_station_name)
        }
        
        # 4. 格式化結果
        status_map = {
            0: "停止營運",
            1: "正常營運",
            2: "暫停營運"
        }
        status = status_map.get(result["service_status"], "未知")
        
        content = (
            f"🚲 {result['station_name']}\n"
            f"狀態: {status}\n"
            f"可借: {result['available_bikes']} 輛\n"
            f"可還: {result['available_spaces']} 位\n"
            f"類型: {result['bike_type']}\n"
        )
        
        return cls.create_success_response(
            content=content,
            data={"station": result}
        )
    
    @classmethod
    async def _query_nearby_stations(cls, lat: float, lon: float, cities: List[str],
                                     radius_m: int, limit: int) -> Dict[str, Any]:
        """查詢附近站點"""
        stations = []
        for city in cities:
            station_endpoint = f"Bike/Station/City/{city}"
            station_params = {
                "$spatialFilter": f"nearby({lat}, {lon}, {radius_m})",
                "$format": "JSON",
                "$top": limit * 2
            }
            city_stations = await TDXBaseAPI.call_api(station_endpoint, station_params, cache_ttl=1800)
            for station in city_stations or []:
                station["_city_code"] = city
            stations.extend(city_stations or [])
        
        if not stations:
            return cls.create_success_response(
                content=f"附近 {radius_m} 公尺內沒有 YouBike 站點",
                data={"stations": []}
            )
        
        # 2. 計算距離並排序
        for station in stations:
            pos = station.get("StationPosition", {})
            if pos.get("PositionLat") and pos.get("PositionLon"):
                station["distance_m"] = TDXBaseAPI.haversine_distance(
                    lat, lon,
                    pos["PositionLat"], pos["PositionLon"]
                )
        
        stations = [s for s in stations if "distance_m" in s]
        stations.sort(key=lambda x: x["distance_m"])
        stations = stations[:limit]
        
        # 3. 批次查詢即時資訊 (v2 API)
        # GET /v2/Bike/Availability/City/{City}
        avail_map = {}
        grouped_uids: Dict[str, List[str]] = {}
        for station in stations:
            grouped_uids.setdefault(station.get("_city_code"), []).append(station.get("StationUID"))

        for city, station_uids in grouped_uids.items():
            avail_endpoint = f"Bike/Availability/City/{city}"
            avail_params = {
                "$filter": " or ".join([f"StationUID eq '{uid}'" for uid in station_uids if uid]),
                "$format": "JSON"
            }
            availability = await TDXBaseAPI.call_api(avail_endpoint, avail_params, cache_ttl=30)
            avail_map.update({a.get("StationUID"): a for a in availability})
        
        # 4. 組合結果
        results = []
        for station in stations:
            station_uid = station.get("StationUID")
            station_name = station.get("StationName", {}).get("Zh_tw", "未知")
            distance = station["distance_m"]
            walking_time = int(distance / 80)
            
            avail = avail_map.get(station_uid, {})
            
            results.append({
                "station_name": station_name,
                "available_bikes": avail.get("AvailableRentBikes", 0),
                "available_spaces": avail.get("AvailableReturnBikes", 0),
                "distance_m": int(distance),
                "walking_time_min": walking_time,
                "service_status": avail.get("ServiceStatus", 1),
                "bike_type": cls._detect_bike_type(station, station_name)
            })
        
        content = cls._format_nearby_result(results)
        
        return cls.create_success_response(
            content=content,
            data={"stations": results}
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
            ("新竹", 24.68, 24.90, 120.90, 121.10),
            ("台中", 24.00, 24.45, 120.45, 121.05),
            ("彰化", 23.85, 24.15, 120.35, 120.70),  # 新增彰化範圍
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
        
        for key, value in TDXBikeTool.CITY_MAP.items():
            if key in chinese_city:
                return value
        return "Taipei"
    
    @staticmethod
    def _find_nearest_supported_city(lat: float, lon: float) -> str:
        """找出最近的支援 YouBike 的城市"""
        # 支援 YouBike 的城市中心點（大約位置）
        city_centers = {
            "台北": (25.033, 121.565),
            "新北": (25.012, 121.466),
            "桃園": (24.994, 121.301),
            "新竹": (24.806, 120.968),
            "台中": (24.148, 120.674),
            "台南": (22.997, 120.213),
            "高雄": (22.627, 120.301),
        }
        
        min_distance = float('inf')
        nearest_city = "台北"
        
        for city_name, (city_lat, city_lon) in city_centers.items():
            distance = TDXBaseAPI.haversine_distance(lat, lon, city_lat, city_lon)
            if distance < min_distance:
                min_distance = distance
                nearest_city = city_name
        
        return nearest_city
    
    @staticmethod
    def _detect_bike_type(station: Dict, station_name: str) -> str:
        """判斷 YouBike 類型（優先從站名判斷，其次從 BikesCapacity）"""
        # 優先從站名判斷
        if "2.0" in station_name or "YouBike2.0" in station_name:
            return "YouBike 2.0"
        if "1.0" in station_name or "YouBike1.0" in station_name:
            return "YouBike 1.0"
        
        # 其次從 BikesCapacity 判斷
        capacity = str(station.get("BikesCapacity", ""))
        if "2.0" in capacity:
            return "YouBike 2.0"
        
        # 預設為 2.0（新站點大多是 2.0）
        return "YouBike 2.0"
    
    @staticmethod
    def _format_nearby_result(stations: List[Dict]) -> str:
        """格式化附近站點結果"""
        if not stations:
            return "附近沒有 YouBike 站點"
        
        lines = ["📍 附近的 YouBike 站點：\n"]
        
        for i, station in enumerate(stations, 1):
            status_emoji = "✅" if station["service_status"] == 1 else "⚠️"
            bikes = station["available_bikes"]
            spaces = station["available_spaces"]
            
            lines.append(
                f"{i}. {status_emoji} {station['station_name']}\n"
                f"   可借 {bikes} 輛 | 可還 {spaces} 位\n"
                f"   步行 {station['walking_time_min']} 分鐘 ({station['distance_m']}m)\n"
            )
        
        return "\n".join(lines)
