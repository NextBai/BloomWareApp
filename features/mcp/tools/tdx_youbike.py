"""
TDX YouBike 即時查詢工具
查詢附近 YouBike 站點、即時車輛數、空位數
"""

import logging
from typing import Dict, Any, List

from .base_tool import MCPTool, StandardToolSchemas, ExecutionError
from .tdx_base import TDXBaseAPI
from core.database import get_user_env_current

logger = logging.getLogger("mcp.tools.tdx.bike")


class TDXBikeTool(MCPTool):
    """TDX YouBike 即時查詢"""
    
    NAME = "tdx_youbike"
    DESCRIPTION = "查詢附近 YouBike 站點、即時車輛數、空位數（支援 YouBike 1.0/2.0）"
    CATEGORY = "微型運具"
    TAGS = ["tdx", "youbike", "ubike", "共享單車", "微笑單車"]
    KEYWORDS = ["YouBike", "UBike", "微笑單車", "共享單車", "腳踏車", "自行車"]
    USAGE_TIPS = [
        "查詢附近站點: 「附近的 YouBike 在哪」",
        "查詢特定站點: 「市政府 YouBike 還有車嗎」",
        "指定城市: 「台北 YouBike」「高雄 CityBike」"
    ]
    
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
        return StandardToolSchemas.create_input_schema({
            "station_name": {
                "type": "string",
                "description": "站點名稱（如「市政府」「台北車站」）。不提供則查詢附近站點"
            },
            "city": {
                "type": "string",
                "description": "城市名稱（如「Taipei」「Kaohsiung」）",
                "enum": list(cls.CITY_MAP.values())
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
    async def execute(cls, arguments: Dict[str, Any], user_id: str = None) -> Dict[str, Any]:
        station_name = arguments.get("station_name", "").strip()
        city = arguments.get("city")
        radius_m = min(int(arguments.get("radius_m", 500)), 2000)
        limit = min(int(arguments.get("limit", 5)), 20)
        
        # 1. 取得用戶位置
        env_ctx = await get_user_env_current(user_id) if user_id else None
        if not env_ctx or not env_ctx.get("success"):
            if not station_name:
                raise ExecutionError("無法取得您的位置，請提供站點名稱或開啟定位權限")
            user_lat, user_lon, user_city = None, None, None
        else:
            ctx = env_ctx.get("context", {})
            user_lat = ctx.get("lat")
            user_lon = ctx.get("lon")
            user_city = ctx.get("city", "")
        
        # 2. 自動判斷城市
        if not city:
            city = cls._map_city_name(user_city) if user_city else "Taipei"
        
        # 3. 查詢分支
        if station_name:
            result = await cls._query_station_availability(station_name, city)
        else:
            if not user_lat or not user_lon:
                raise ExecutionError("查詢附近 YouBike 需要定位權限")
            result = await cls._query_nearby_stations(user_lat, user_lon, city, radius_m, limit)
        
        return result
    
    @classmethod
    async def _query_station_availability(cls, station_name: str, city: str) -> Dict[str, Any]:
        """查詢特定站點即時資訊"""
        # 1. 查詢站點基本資訊
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
        
        # 3. 查詢即時可用車輛數
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
            "bike_type": "YouBike 2.0" if "2.0" in target_station.get("BikesCapacity", "") else "YouBike 1.0"
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
    async def _query_nearby_stations(cls, lat: float, lon: float, city: str, 
                                     radius_m: int, limit: int) -> Dict[str, Any]:
        """查詢附近站點"""
        # 1. 查詢附近站點（使用空間過濾）
        station_endpoint = f"Bike/Station/City/{city}"
        station_params = {
            "$spatialFilter": f"nearby({lat}, {lon}, {radius_m})",
            "$format": "JSON",
            "$top": limit * 2
        }
        
        stations = await TDXBaseAPI.call_api(station_endpoint, station_params, cache_ttl=1800)
        
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
        
        # 3. 批次查詢即時資訊
        station_uids = [s.get("StationUID") for s in stations]
        
        avail_endpoint = f"Bike/Availability/City/{city}"
        avail_params = {
            "$filter": " or ".join([f"StationUID eq '{uid}'" for uid in station_uids]),
            "$format": "JSON"
        }
        
        availability = await TDXBaseAPI.call_api(avail_endpoint, avail_params, cache_ttl=30)
        
        # 建立 UID -> 可用性 映射
        avail_map = {a.get("StationUID"): a for a in availability}
        
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
                "bike_type": "YouBike 2.0" if "2.0" in station.get("BikesCapacity", "") else "YouBike 1.0"
            })
        
        content = cls._format_nearby_result(results)
        
        return cls.create_success_response(
            content=content,
            data={"stations": results}
        )
    
    @staticmethod
    def _map_city_name(chinese_city: str) -> str:
        """中文城市名稱轉 TDX 代碼"""
        for key, value in TDXBikeTool.CITY_MAP.items():
            if key in chinese_city:
                return value
        return "Taipei"
    
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
