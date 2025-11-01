"""
TDX 公車即時到站工具
查詢附近公車站、特定路線到站時間
"""

import logging
from typing import Dict, Any, List, Optional

from .base_tool import MCPTool, StandardToolSchemas, ExecutionError
from .tdx_base import TDXBaseAPI
from core.database import get_user_env_current

logger = logging.getLogger("mcp.tools.tdx.bus")


class TDXBusArrivalTool(MCPTool):
    """TDX 公車即時到站查詢"""
    
    NAME = "tdx_bus_arrival"
    DESCRIPTION = "查詢公車即時到站時間（自動感知用戶位置，找最近站點）"
    CATEGORY = "道路運輸"
    TAGS = ["tdx", "公車", "即時到站", "公共運輸"]
    KEYWORDS = ["公車", "巴士", "bus", "到站", "即時", "幾分鐘"]
    USAGE_TIPS = [
        "查詢特定路線: 「307 公車還要多久」",
        "查詢附近公車站: 「附近有什麼公車」",
        "指定城市: 「台北 307」「高雄紅30」"
    ]
    
    @classmethod
    def get_input_schema(cls) -> Dict[str, Any]:
        return StandardToolSchemas.create_input_schema({
            "route_name": {
                "type": "string",
                "description": "路線名稱（如「307」「紅30」）。不提供則查詢附近所有公車站"
            },
            "city": {
                "type": "string",
                "description": "城市（預設從環境感知自動判斷）",
                "enum": ["Taipei", "NewTaipei", "Taoyuan", "Taichung", "Tainan", "Kaohsiung", 
                        "Keelung", "Hsinchu", "HsinchuCounty", "MiaoliCounty", "ChanghuaCounty",
                        "NantouCounty", "YunlinCounty", "ChiayiCounty", "Chiayi", "PingtungCounty",
                        "YilanCounty", "HualienCounty", "TaitungCounty", "KinmenCounty", "PenghuCounty",
                        "LienchiangCounty"]
            },
            "limit": {
                "type": "integer",
                "description": "返回結果數量上限",
                "default": 5
            }
        }, required=[])
    
    @classmethod
    def get_output_schema(cls) -> Dict[str, Any]:
        schema = StandardToolSchemas.create_output_schema()
        schema["properties"].update({
            "arrivals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "route_name": {"type": "string"},
                        "stop_name": {"type": "string"},
                        "direction": {"type": "string"},
                        "estimate_time": {"type": "integer"},
                        "status": {"type": "string"}
                    }
                }
            }
        })
        return schema
    
    @classmethod
    async def execute(cls, arguments: Dict[str, Any], user_id: str = None) -> Dict[str, Any]:
        route_name = arguments.get("route_name", "").strip()
        city = arguments.get("city")
        limit = min(int(arguments.get("limit", 5)), 20)
        
        # 1. 取得用戶位置
        env_ctx = await get_user_env_current(user_id) if user_id else None
        if not env_ctx or not env_ctx.get("success"):
            if not route_name:
                raise ExecutionError("無法取得您的位置，請提供路線名稱或開啟定位權限")
            user_lat, user_lon, user_city = None, None, None
        else:
            ctx = env_ctx.get("context", {})
            user_lat = ctx.get("lat")
            user_lon = ctx.get("lon")
            user_city = ctx.get("city", "")
        
        # 2. 自動判斷城市
        if not city:
            city = cls._map_city_name(user_city) if user_city else "Taipei"
        
        # 3. 查詢邏輯分支
        if route_name:
            # 指定路線：找最近站點並查詢到站時間
            result = await cls._query_route_arrival(route_name, city, user_lat, user_lon, limit)
        else:
            # 未指定路線：查詢附近所有站點
            if not user_lat or not user_lon:
                raise ExecutionError("查詢附近公車需要定位權限")
            result = await cls._query_nearby_stops(user_lat, user_lon, city, limit)
        
        return result
    
    @classmethod
    async def _query_route_arrival(cls, route_name: str, city: str, 
                                   user_lat: Optional[float], user_lon: Optional[float],
                                   limit: int) -> Dict[str, Any]:
        """查詢特定路線的即時到站"""
        # 1. 查詢路線基本資訊
        route_endpoint = f"Bus/Route/City/{city}"
        route_params = {
            "$filter": f"contains(RouteName/Zh_tw, '{route_name}')",
            "$format": "JSON",
            "$top": 1
        }
        
        routes = await TDXBaseAPI.call_api(route_endpoint, route_params, cache_ttl=3600)
        
        if not routes or len(routes) == 0:
            raise ExecutionError(f"找不到路線「{route_name}」，請確認路線名稱是否正確")
        
        route = routes[0]
        route_uid = route.get("RouteUID")
        full_route_name = route.get("RouteName", {}).get("Zh_tw", route_name)
        
        # 2. 查詢該路線所有站點
        stop_endpoint = f"Bus/StopOfRoute/City/{city}"
        stop_params = {
            "$filter": f"RouteUID eq '{route_uid}'",
            "$format": "JSON"
        }
        
        stops = await TDXBaseAPI.call_api(stop_endpoint, stop_params, cache_ttl=1800)
        
        if not stops:
            raise ExecutionError(f"路線「{full_route_name}」暫無站點資訊")
        
        # 3. 如果有用戶位置，找最近的站點
        if user_lat and user_lon:
            for stop_seq in stops:
                for stop in stop_seq.get("Stops", []):
                    pos = stop.get("StopPosition", {})
                    if pos.get("PositionLat") and pos.get("PositionLon"):
                        stop["distance_m"] = TDXBaseAPI.haversine_distance(
                            user_lat, user_lon,
                            pos["PositionLat"], pos["PositionLon"]
                        )
            
            # 取前 3 個最近的站點
            all_stops = []
            for stop_seq in stops:
                all_stops.extend(stop_seq.get("Stops", []))
            
            all_stops = [s for s in all_stops if "distance_m" in s]
            all_stops.sort(key=lambda x: x["distance_m"])
            target_stops = all_stops[:3]
        else:
            # 沒有位置，取前幾個站點
            target_stops = []
            for stop_seq in stops[:1]:
                target_stops.extend(stop_seq.get("Stops", [])[:limit])
        
        # 4. 查詢這些站點的即時到站
        arrivals = []
        for stop in target_stops:
            stop_uid = stop.get("StopUID")
            stop_name = stop.get("StopName", {}).get("Zh_tw", "未知")
            
            arrival_endpoint = f"Bus/EstimatedTimeOfArrival/City/{city}"
            arrival_params = {
                "$filter": f"RouteUID eq '{route_uid}' and StopUID eq '{stop_uid}'",
                "$format": "JSON"
            }
            
            arrival_data = await TDXBaseAPI.call_api(arrival_endpoint, arrival_params, cache_ttl=30)
            
            for arr in arrival_data[:2]:  # 每個站點最多 2 筆（雙向）
                estimate_time = arr.get("EstimateTime")
                stop_status = arr.get("StopStatus", 0)
                
                if stop_status == 0:  # 正常
                    status_text = f"{estimate_time // 60} 分鐘" if estimate_time else "即將進站"
                elif stop_status == 1:  # 尚未發車
                    status_text = "尚未發車"
                elif stop_status == 2:  # 交管不停靠
                    status_text = "交管不停靠"
                elif stop_status == 3:  # 末班車已過
                    status_text = "末班車已過"
                elif stop_status == 4:  # 今日未營運
                    status_text = "今日未營運"
                else:
                    status_text = "未知"
                
                arrivals.append({
                    "route_name": full_route_name,
                    "stop_name": stop_name,
                    "direction": arr.get("Direction", 0),
                    "estimate_time": estimate_time,
                    "status": status_text,
                    "distance_m": stop.get("distance_m", 0)
                })
        
        # 5. 格式化回覆
        content = cls._format_arrival_result(arrivals, full_route_name, user_lat is not None)
        
        return cls.create_success_response(
            content=content,
            data={"arrivals": arrivals, "route_name": full_route_name}
        )
    
    @classmethod
    async def _query_nearby_stops(cls, lat: float, lon: float, city: str, limit: int) -> Dict[str, Any]:
        """查詢附近公車站"""
        # TDX 附近站點查詢
        endpoint = f"Bus/Stop/City/{city}"
        params = {
            "$spatialFilter": f"nearby({lat}, {lon}, 300)",  # 300m 範圍
            "$format": "JSON",
            "$top": limit * 3  # 多取一些，後續過濾
        }
        
        stops = await TDXBaseAPI.call_api(endpoint, params, cache_ttl=1800)
        
        if not stops:
            return cls.create_success_response(
                content="附近 300 公尺內沒有公車站，請擴大範圍或移動位置",
                data={"stops": []}
            )
        
        # 計算距離並排序
        for stop in stops:
            pos = stop.get("StopPosition", {})
            if pos.get("PositionLat") and pos.get("PositionLon"):
                stop["distance_m"] = TDXBaseAPI.haversine_distance(
                    lat, lon,
                    pos["PositionLat"], pos["PositionLon"]
                )
        
        stops = [s for s in stops if "distance_m" in s]
        stops.sort(key=lambda x: x["distance_m"])
        stops = stops[:limit]
        
        # 格式化結果
        results = []
        for stop in stops:
            stop_name = stop.get("StopName", {}).get("Zh_tw", "未知")
            distance = stop["distance_m"]
            walking_time = int(distance / 80)  # 80m/min
            
            results.append({
                "stop_name": stop_name,
                "distance_m": int(distance),
                "walking_time_min": walking_time,
                "stop_uid": stop.get("StopUID")
            })
        
        content = cls._format_nearby_result(results)
        
        return cls.create_success_response(
            content=content,
            data={"stops": results}
        )
    
    @staticmethod
    def _map_city_name(chinese_city: str) -> str:
        """中文城市名稱轉 TDX 代碼"""
        city_map = {
            "台北": "Taipei", "臺北": "Taipei",
            "新北": "NewTaipei", "新北市": "NewTaipei",
            "桃園": "Taoyuan",
            "台中": "Taichung", "臺中": "Taichung",
            "台南": "Tainan", "臺南": "Tainan",
            "高雄": "Kaohsiung",
            "基隆": "Keelung",
            "新竹": "Hsinchu",
            "嘉義": "Chiayi"
        }
        
        for key, value in city_map.items():
            if key in chinese_city:
                return value
        
        return "Taipei"  # 預設台北
    
    @staticmethod
    def _format_arrival_result(arrivals: List[Dict], route_name: str, has_location: bool) -> str:
        """格式化到站結果"""
        if not arrivals:
            return f"路線 {route_name} 目前無即時到站資訊"
        
        lines = [f"🚌 {route_name} 即時到站資訊：\n"]
        
        # 按站點分組
        stops_dict = {}
        for arr in arrivals:
            stop = arr["stop_name"]
            if stop not in stops_dict:
                stops_dict[stop] = []
            stops_dict[stop].append(arr)
        
        for i, (stop_name, stop_arrivals) in enumerate(stops_dict.items(), 1):
            dist_info = ""
            if has_location and stop_arrivals[0].get("distance_m"):
                dist = stop_arrivals[0]["distance_m"]
                walk_time = int(dist / 80)
                dist_info = f" - 步行 {walk_time} 分鐘 ({int(dist)}m)"
            
            lines.append(f"{i}. 🚏 {stop_name}{dist_info}")
            
            for arr in stop_arrivals:
                direction = "往 ↑" if arr["direction"] == 0 else "返 ↓"
                lines.append(f"   {direction} {arr['status']}")
            
            lines.append("")
        
        return "\n".join(lines)
    
    @staticmethod
    def _format_nearby_result(stops: List[Dict]) -> str:
        """格式化附近站點結果"""
        if not stops:
            return "附近沒有找到公車站"
        
        lines = ["📍 附近的公車站：\n"]
        
        for i, stop in enumerate(stops, 1):
            lines.append(
                f"{i}. 🚏 {stop['stop_name']}\n"
                f"   步行 {stop['walking_time_min']} 分鐘 ({stop['distance_m']}m)\n"
            )
        
        lines.append("💡 提供路線名稱查詢即時到站時間")
        
        return "\n".join(lines)
