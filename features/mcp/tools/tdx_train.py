"""
TDX 台鐵時刻表查詢工具
查詢台鐵列車時刻、票價、車站資訊
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from .base_tool import MCPTool, StandardToolSchemas, ExecutionError
from .tdx_base import TDXBaseAPI
from core.database import get_user_env_current

logger = logging.getLogger("mcp.tools.tdx.train")


class TDXTrainTool(MCPTool):
    """TDX 台鐵時刻表查詢"""
    
    NAME = "tdx_train"
    DESCRIPTION = "查詢台鐵列車時刻表、票價、最近車站（含高鐵轉乘資訊）"
    CATEGORY = "軌道運輸"
    TAGS = ["tdx", "台鐵", "TRA", "火車", "時刻表"]
    KEYWORDS = ["台鐵", "臺鐵", "火車", "TRA", "列車", "時刻"]
    USAGE_TIPS = [
        "查詢車次: 「自強號 123 次」",
        "查詢路線: 「台北到台中的火車」",
        "查詢最近車站: 「最近的火車站在哪」",
        "查詢時刻: 「下午3點台北到高雄」"
    ]
    
    @classmethod
    def get_input_schema(cls) -> Dict[str, Any]:
        return StandardToolSchemas.create_input_schema({
            "origin_station": {
                "type": "string",
                "description": "起站名稱（如「台北」「台中」）"
            },
            "destination_station": {
                "type": "string",
                "description": "迄站名稱"
            },
            "train_no": {
                "type": "string",
                "description": "車次號碼（如「123」）"
            },
            "departure_time": {
                "type": "string",
                "description": "出發時間（HH:MM 格式，如「14:30」）"
            },
            "train_type": {
                "type": "string",
                "description": "列車種類",
                "enum": ["自強", "莒光", "區間", "區間快", "普快", "復興", "太魯閣", "普悠瑪"]
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
            "trains": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "train_no": {"type": "string"},
                        "train_type": {"type": "string"},
                        "departure_time": {"type": "string"},
                        "arrival_time": {"type": "string"},
                        "duration_min": {"type": "integer"}
                    }
                }
            }
        })
        return schema
    
    @classmethod
    async def execute(cls, arguments: Dict[str, Any], user_id: str = None) -> Dict[str, Any]:
        origin = arguments.get("origin_station", "").strip()
        destination = arguments.get("destination_station", "").strip()
        train_no = arguments.get("train_no", "").strip()
        departure_time = arguments.get("departure_time", "").strip()
        train_type = arguments.get("train_type")
        limit = min(int(arguments.get("limit", 5)), 20)
        
        # 1. 取得用戶位置（用於最近車站查詢）
        env_ctx = await get_user_env_current(user_id) if user_id else None
        user_lat, user_lon = None, None
        if env_ctx and env_ctx.get("success"):
            ctx = env_ctx.get("context", {})
            user_lat = ctx.get("lat")
            user_lon = ctx.get("lon")
        
        # 2. 查詢分支
        if train_no:
            # 查詢特定車次
            result = await cls._query_train_schedule(train_no)
        elif origin and destination:
            # 查詢起迄站列車
            result = await cls._query_od_trains(origin, destination, departure_time, train_type, limit)
        elif not origin and not destination:
            # 查詢最近車站
            if not user_lat or not user_lon:
                raise ExecutionError("查詢最近車站需要定位權限，或請提供起迄站名稱")
            result = await cls._query_nearest_station(user_lat, user_lon)
        else:
            raise ExecutionError("請提供車次號碼，或起迄站名稱，或開啟定位查詢最近車站")
        
        return result
    
    @classmethod
    async def _query_train_schedule(cls, train_no: str) -> Dict[str, Any]:
        """查詢特定車次時刻表"""
        today = datetime.now().strftime("%Y-%m-%d")
        
        endpoint = "Rail/TRA/DailyTrainInfo/Today"
        params = {
            "$filter": f"TrainNo eq '{train_no}'",
            "$format": "JSON"
        }
        
        trains = await TDXBaseAPI.call_api(endpoint, params, cache_ttl=1800)
        
        if not trains:
            raise ExecutionError(f"找不到車次 {train_no}，請確認車次號碼")
        
        train = trains[0]
        train_type = train.get("TrainTypeName", {}).get("Zh_tw", "未知")
        
        # 取得停靠站資訊
        stops = train.get("StopTimes", [])
        
        if not stops:
            raise ExecutionError(f"車次 {train_no} 無停靠站資訊")
        
        # 格式化時刻表
        schedule_lines = [f"🚂 {train_type} {train_no} 次\n"]
        
        for stop in stops:
            station_name = stop.get("StationName", {}).get("Zh_tw", "未知")
            arrival_time = stop.get("ArrivalTime", "")
            departure_time = stop.get("DepartureTime", "")
            
            if arrival_time == departure_time:
                time_str = arrival_time[:5] if arrival_time else "-"
            else:
                arr = arrival_time[:5] if arrival_time else "-"
                dep = departure_time[:5] if departure_time else "-"
                time_str = f"{arr} / {dep}"
            
            schedule_lines.append(f"  {station_name:<10} {time_str}")
        
        content = "\n".join(schedule_lines)
        
        return cls.create_success_response(
            content=content,
            data={"train": train, "stops": stops}
        )
    
    @classmethod
    async def _query_od_trains(cls, origin: str, destination: str, 
                              departure_time: Optional[str], train_type: Optional[str],
                              limit: int) -> Dict[str, Any]:
        """查詢起迄站列車"""
        # 1. 先取得今日所有列車
        endpoint = "Rail/TRA/DailyTrainInfo/Today"
        params = {
            "$format": "JSON"
        }
        
        all_trains = await TDXBaseAPI.call_api(endpoint, params, cache_ttl=1800)
        
        if not all_trains:
            raise ExecutionError("無法取得台鐵列車資訊")
        
        # 2. 過濾符合起迄站的列車
        matching_trains = []
        
        for train in all_trains:
            stops = train.get("StopTimes", [])
            
            # 找起站和迄站
            origin_idx, dest_idx = -1, -1
            for i, stop in enumerate(stops):
                station = stop.get("StationName", {}).get("Zh_tw", "")
                if origin in station:
                    origin_idx = i
                if destination in station:
                    dest_idx = i
            
            # 起站在迄站之前才符合
            if origin_idx >= 0 and dest_idx > origin_idx:
                origin_stop = stops[origin_idx]
                dest_stop = stops[dest_idx]
                
                train_info = {
                    "train_no": train.get("TrainNo"),
                    "train_type": train.get("TrainTypeName", {}).get("Zh_tw", "未知"),
                    "origin_station": origin_stop.get("StationName", {}).get("Zh_tw"),
                    "destination_station": dest_stop.get("StationName", {}).get("Zh_tw"),
                    "departure_time": origin_stop.get("DepartureTime", ""),
                    "arrival_time": dest_stop.get("ArrivalTime", ""),
                }
                
                # 計算行駛時間
                try:
                    dep_dt = datetime.strptime(train_info["departure_time"], "%H:%M:%S")
                    arr_dt = datetime.strptime(train_info["arrival_time"], "%H:%M:%S")
                    if arr_dt < dep_dt:  # 跨日
                        arr_dt += timedelta(days=1)
                    duration = (arr_dt - dep_dt).total_seconds() / 60
                    train_info["duration_min"] = int(duration)
                except:
                    train_info["duration_min"] = 0
                
                matching_trains.append(train_info)
        
        if not matching_trains:
            raise ExecutionError(f"找不到 {origin} 到 {destination} 的直達列車")
        
        # 3. 時間過濾
        if departure_time:
            try:
                target_time = datetime.strptime(departure_time, "%H:%M")
                matching_trains = [
                    t for t in matching_trains
                    if datetime.strptime(t["departure_time"][:5], "%H:%M") >= target_time
                ]
            except:
                pass
        
        # 4. 車種過濾
        if train_type:
            matching_trains = [t for t in matching_trains if train_type in t["train_type"]]
        
        # 5. 排序並限制數量
        matching_trains.sort(key=lambda x: x["departure_time"])
        matching_trains = matching_trains[:limit]
        
        # 6. 格式化結果
        content = cls._format_od_result(matching_trains, origin, destination)
        
        return cls.create_success_response(
            content=content,
            data={"trains": matching_trains}
        )
    
    @classmethod
    async def _query_nearest_station(cls, lat: float, lon: float) -> Dict[str, Any]:
        """查詢最近的台鐵車站"""
        # 1. 取得所有車站
        endpoint = "Rail/TRA/Station"
        params = {
            "$format": "JSON"
        }
        
        stations = await TDXBaseAPI.call_api(endpoint, params, cache_ttl=86400)
        
        if not stations:
            raise ExecutionError("無法取得台鐵車站資訊")
        
        # 2. 計算距離
        for station in stations:
            pos = station.get("StationPosition", {})
            if pos.get("PositionLat") and pos.get("PositionLon"):
                station["distance_m"] = TDXBaseAPI.haversine_distance(
                    lat, lon,
                    pos["PositionLat"], pos["PositionLon"]
                )
        
        stations_with_distance = [s for s in stations if "distance_m" in s]
        
        if not stations_with_distance:
            raise ExecutionError("附近沒有台鐵車站資訊")
        
        stations_with_distance.sort(key=lambda x: x["distance_m"])
        nearest = stations_with_distance[:3]
        
        # 3. 格式化結果
        results = []
        for station in nearest:
            station_name = station.get("StationName", {}).get("Zh_tw", "未知")
            distance = station["distance_m"]
            walking_time = int(distance / 80)
            
            results.append({
                "station_name": station_name,
                "station_id": station.get("StationID"),
                "distance_m": int(distance),
                "walking_time_min": walking_time,
                "address": station.get("StationAddress", "")
            })
        
        content = cls._format_nearest_result(results)
        
        return cls.create_success_response(
            content=content,
            data={"stations": results}
        )
    
    @staticmethod
    def _format_od_result(trains: List[Dict], origin: str, destination: str) -> str:
        """格式化起迄站查詢結果"""
        if not trains:
            return f"🚂 {origin} → {destination} 目前無可搭乘列車"
        
        lines = [f"🚂 {origin} → {destination}\n"]
        
        for i, train in enumerate(trains, 1):
            duration_hours = train["duration_min"] // 60
            duration_mins = train["duration_min"] % 60
            
            if duration_hours > 0:
                duration_str = f"{duration_hours}小時{duration_mins}分"
            else:
                duration_str = f"{duration_mins}分鐘"
            
            lines.append(
                f"{i}. {train['train_type']} {train['train_no']}次\n"
                f"   {train['departure_time'][:5]} → {train['arrival_time'][:5]}"
                f"  ({duration_str})\n"
            )
        
        return "\n".join(lines)
    
    @staticmethod
    def _format_nearest_result(stations: List[Dict]) -> str:
        """格式化最近車站結果"""
        lines = ["📍 最近的台鐵車站：\n"]
        
        for i, station in enumerate(stations, 1):
            lines.append(
                f"{i}. 🚂 {station['station_name']}\n"
                f"   步行 {station['walking_time_min']} 分鐘 ({station['distance_m']}m)\n"
                f"   {station.get('address', '')}\n"
            )
        
        return "\n".join(lines)
