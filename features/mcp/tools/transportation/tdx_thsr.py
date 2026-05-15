"""
TDX 台灣高鐵查詢工具
查詢高鐵時刻表、票價、最近車站
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from ..base_tool import MCPTool, StandardToolSchemas, ExecutionError
from .tdx_base import TDXBaseAPI
from core.database import get_user_env_current

logger = logging.getLogger("mcp.tools.tdx.thsr")


class TDXTHSRTool(MCPTool):
    """TDX 台灣高鐵時刻表查詢"""
    
    NAME = "tdx_thsr"
    DESCRIPTION = "Query Taiwan High Speed Rail (THSR) schedules, fares, and nearest stations (Nangang to Zuoying)"
    CATEGORY = "軌道運輸"
    TAGS = ["tdx", "高鐵", "THSR", "時刻表", "票價"]
    KEYWORDS = ["高鐵", "THSR", "HSR", "高速鐵路", "時刻", "票價"]
    USAGE_TIPS = [
        "查詢車次: 「高鐵 123 次」",
        "查詢路線: 「台北到台中的高鐵」",
        "查詢最近車站: 「最近的高鐵站在哪」",
        "查詢時刻: 「下午2點台北到高雄的高鐵」"
    ]
    
    # 高鐵車站代碼對照
    STATION_MAP = {
        "南港": "NAG", "台北": "TPE", "臺北": "TPE", "板橋": "BAC",
        "桃園": "TAY", "新竹": "HSC", "苗栗": "MIA", "台中": "TAC", 
        "臺中": "TAC", "彰化": "CHA", "雲林": "YUL", "嘉義": "CHY",
        "台南": "TNN", "臺南": "TNN", "左營": "ZUY", "高雄": "ZUY"
    }
    
    @classmethod
    def get_input_schema(cls) -> Dict[str, Any]:
        return StandardToolSchemas.create_input_schema({
            "origin_station": {
                "type": "string",
                "description": "起站名稱（南港/台北/板橋/桃園/新竹/苗栗/台中/彰化/雲林/嘉義/台南/左營）"
            },
            "destination_station": {
                "type": "string",
                "description": "迄站名稱"
            },
            "train_no": {
                "type": "string",
                "description": "車次號碼（如「123」）"
            },
            "departure_date": {
                "type": "string",
                "description": "出發日期（YYYY-MM-DD 格式，預設今日）"
            },
            "departure_time": {
                "type": "string",
                "description": "出發時間（HH:MM 格式，如「14:30」）"
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
            "trains": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "train_no": {"type": "string"},
                        "train_type": {"type": "string"},
                        "departure_time": {"type": "string"},
                        "arrival_time": {"type": "string"},
                        "duration_min": {"type": "integer"},
                        "fare": {"type": "integer"}
                    }
                }
            }
        })
        return schema
    
    @classmethod
    async def execute(cls, arguments: Dict[str, Any]) -> Dict[str, Any]:
        # 從 arguments 中讀取 user_id（由 coordinator 注入）
        user_id = arguments.get("_user_id")
        
        origin = arguments.get("origin_station", "").strip()
        destination = arguments.get("destination_station", "").strip()
        train_no = arguments.get("train_no", "").strip()
        departure_date = arguments.get("departure_date", "").strip()
        departure_time = arguments.get("departure_time", "").strip()
        limit = min(int(arguments.get("limit", 5)), 20)
        
        # 1. 取得用戶位置（優先從 arguments 讀取，由 coordinator 注入）
        user_lat = arguments.get("lat")
        user_lon = arguments.get("lon")
        
        logger.info(f"🚄 [THSR] 輸入參數: lat={user_lat}, lon={user_lon}, origin={origin}, dest={destination}, user_id={user_id}")
        
        # 從資料庫補充缺失的位置資訊（僅當 coordinator 沒有注入時）
        if user_id and (user_lat is None or user_lon is None):
            try:
                env_ctx = await get_user_env_current(user_id)
                logger.info(f"📍 [THSR] 資料庫查詢結果: {env_ctx}")
                if env_ctx and env_ctx.get("success"):
                    ctx = env_ctx.get("context", {})
                    if user_lat is None:
                        user_lat = ctx.get("lat")
                    if user_lon is None:
                        user_lon = ctx.get("lon")
                    logger.info(f"📍 [THSR] 補充後: lat={user_lat}, lon={user_lon}")
                else:
                    logger.warning(f"⚠️ [THSR] 資料庫查詢失敗或無資料: {env_ctx}")
            except Exception as e:
                logger.warning(f"⚠️ [THSR] 資料庫查詢異常: {e}")
        
        # 2. 驗證並清理站名（過濾無效值）
        origin = cls._validate_station_name(origin)
        destination = cls._validate_station_name(destination)
        logger.info(f"🚄 [THSR] 驗證後: origin={origin}, dest={destination}")
        
        # 3. 查詢分支
        if train_no:
            # 查詢特定車次
            result = await cls._query_train_schedule(train_no, departure_date)
        elif origin and destination:
            # 查詢起迄站列車
            result = await cls._query_od_trains(origin, destination, departure_date, departure_time, limit)
        elif destination and not origin:
            # 只有目的地，用 GPS 找最近高鐵站作為起點
            if not user_lat or not user_lon:
                raise ExecutionError("查詢往某站的高鐵需要定位權限，或請同時提供起站名稱")
            nearest_result = await cls._query_nearest_station(user_lat, user_lon)
            # create_success_response 會把 data 直接 update 到 response，所以 stations 在頂層
            nearest_stations = nearest_result.get("stations", [])
            if not nearest_stations:
                raise ExecutionError("附近沒有高鐵車站")
            origin = nearest_stations[0]["station_name"]
            logger.info(f"🚄 [THSR] 自動設定起站: {origin}")
            result = await cls._query_od_trains(origin, destination, departure_date, departure_time, limit)
        elif not origin and not destination:
            # 查詢最近車站
            if not user_lat or not user_lon:
                raise ExecutionError("查詢最近高鐵站需要定位權限，或請提供起迄站名稱")
            result = await cls._query_nearest_station(user_lat, user_lon)
        else:
            raise ExecutionError("請提供車次號碼，或起迄站名稱，或開啟定位查詢最近高鐵站")
        
        return result
    
    @classmethod
    def _validate_station_name(cls, station_name: str) -> str:
        """驗證並清理站名，過濾無效值"""
        if not station_name:
            return ""
        
        # 無效的站名關鍵字
        invalid_keywords = [
            "台灣", "臺灣", "Taiwan", "taiwan",
            "中華民國", "ROC", "TW",
            "全部", "所有", "任何", "附近"
        ]
        
        for keyword in invalid_keywords:
            if keyword in station_name or station_name == keyword:
                logger.warning(f"⚠️ [THSR] 過濾無效站名: {station_name}")
                return ""
        
        # 移除常見的後綴
        cleaned = station_name.replace("高鐵站", "").replace("車站", "").replace("站", "").strip()
        
        return cleaned if cleaned else station_name
    
    @classmethod
    async def _query_train_schedule(cls, train_no: str, departure_date: str = "") -> Dict[str, Any]:
        """查詢特定車次時刻表"""
        # 日期處理
        if not departure_date:
            date_str = datetime.now().strftime("%Y-%m-%d")
        else:
            date_str = departure_date
        
        # TDX 高鐵每日時刻表 (v2 API)
        # GET /v2/Rail/THSR/DailyTimetable/TrainDates/{TrainDate}
        endpoint = f"Rail/THSR/DailyTimetable/TrainDates/{date_str}"
        params = {
            "$filter": f"DailyTrainInfo/TrainNo eq '{train_no}'",
            "$format": "JSON"
        }
        
        trains = await TDXBaseAPI.call_api(endpoint, params, cache_ttl=1800)
        
        if not trains or len(trains) == 0:
            raise ExecutionError(f"找不到車次 {train_no}，請確認車次號碼與日期")
        
        train = trains[0]
        train_info = train.get("DailyTrainInfo", {})
        stops = train_info.get("StopTimes", [])
        
        if not stops:
            raise ExecutionError(f"車次 {train_no} 無停靠站資訊")
        
        # 判斷車種
        train_type = "標準車廂"
        if any("商務" in stop.get("StationName", {}).get("Zh_tw", "") for stop in stops):
            train_type = "商務車廂"
        
        # 格式化時刻表
        schedule_lines = [f"🚄 高鐵 {train_no} 次 ({train_type})\n"]
        schedule_lines.append(f"日期: {date_str}\n")
        
        for stop in stops:
            station_name = stop.get("StationName", {}).get("Zh_tw", "未知")
            arrival_time = stop.get("ArrivalTime", "")
            departure_time = stop.get("DepartureTime", "")
            
            if arrival_time == departure_time:
                time_str = arrival_time[:5] if arrival_time else "-"
            else:
                arr = arrival_time[:5] if arrival_time else "-"
                dep = departure_time[:5] if departure_time else "-"
                time_str = f"到 {arr} / 開 {dep}"
            
            schedule_lines.append(f"  {station_name:<6} {time_str}")
        
        content = "\n".join(schedule_lines)
        
        return cls.create_success_response(
            content=content,
            data={"train": train_info, "stops": stops}
        )
    
    @classmethod
    async def _query_od_trains(cls, origin: str, destination: str, 
                              departure_date: str, departure_time: Optional[str],
                              limit: int) -> Dict[str, Any]:
        """查詢起迄站列車與票價"""
        # 站點代碼轉換
        origin_code = cls._get_station_code(origin)
        dest_code = cls._get_station_code(destination)
        
        if not origin_code:
            raise ExecutionError(f"找不到車站「{origin}」，請使用正確的高鐵站名")
        if not dest_code:
            raise ExecutionError(f"找不到車站「{destination}」，請使用正確的高鐵站名")
        
        # 日期處理
        if not departure_date:
            date_str = datetime.now().strftime("%Y-%m-%d")
        else:
            date_str = departure_date
        
        # 1. 查詢當日所有班次 (v2 API)
        # GET /v2/Rail/THSR/DailyTimetable/TrainDates/{TrainDate}
        endpoint = f"Rail/THSR/DailyTimetable/TrainDates/{date_str}"
        params = {
            "$format": "JSON"
        }
        
        all_trains = await TDXBaseAPI.call_api(endpoint, params, cache_ttl=1800)
        
        if not all_trains:
            raise ExecutionError("無法取得高鐵時刻表資訊")
        
        # 2. 過濾符合起迄站的列車
        matching_trains = []
        
        for train_data in all_trains:
            train_info = train_data.get("DailyTrainInfo", {})
            stops = train_info.get("StopTimes", [])
            
            # 找起站和迄站
            origin_stop, dest_stop = None, None
            origin_idx, dest_idx = -1, -1
            
            for i, stop in enumerate(stops):
                station_id = stop.get("StationID")
                if station_id == origin_code:
                    origin_stop = stop
                    origin_idx = i
                if station_id == dest_code:
                    dest_stop = stop
                    dest_idx = i
            
            # 起站在迄站之前才符合
            if origin_stop and dest_stop and origin_idx < dest_idx:
                dep_time = origin_stop.get("DepartureTime", "")
                arr_time = dest_stop.get("ArrivalTime", "")
                
                train_result = {
                    "train_no": train_info.get("TrainNo"),
                    "origin_station": origin_stop.get("StationName", {}).get("Zh_tw"),
                    "destination_station": dest_stop.get("StationName", {}).get("Zh_tw"),
                    "departure_time": dep_time,
                    "arrival_time": arr_time,
                }
                
                # 計算行駛時間
                try:
                    dep_dt = datetime.strptime(dep_time, "%H:%M:%S")
                    arr_dt = datetime.strptime(arr_time, "%H:%M:%S")
                    duration = (arr_dt - dep_dt).total_seconds() / 60
                    train_result["duration_min"] = int(duration)
                except:
                    train_result["duration_min"] = 0
                
                matching_trains.append(train_result)
        
        if not matching_trains:
            raise ExecutionError(f"找不到 {origin} 到 {destination} 的直達高鐵")
        
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
        
        # 4. 查詢票價 (v2 API)
        # GET /v2/Rail/THSR/ODFare/{OriginStationID}/to/{DestinationStationID}
        fare_endpoint = f"Rail/THSR/ODFare/{origin_code}/to/{dest_code}"
        fare_params = {
            "$format": "JSON"
        }
        
        try:
            fare_data = await TDXBaseAPI.call_api(fare_endpoint, fare_params, cache_ttl=86400)
            if fare_data and len(fare_data) > 0:
                fares = fare_data[0].get("Fares", [])
                standard_fare = next((f.get("Price") for f in fares if f.get("TicketType") == "標準"), 0)
                
                for train in matching_trains:
                    train["fare"] = standard_fare
        except:
            # 票價查詢失敗不影響時刻表結果
            pass
        
        # 5. 排序並限制數量
        matching_trains.sort(key=lambda x: x["departure_time"])
        matching_trains = matching_trains[:limit]
        
        # 6. 格式化結果
        content = cls._format_od_result(matching_trains, origin, destination, date_str)
        
        return cls.create_success_response(
            content=content,
            data={"trains": matching_trains, "date": date_str}
        )
    
    @classmethod
    async def _query_nearest_station(cls, lat: float, lon: float) -> Dict[str, Any]:
        """查詢最近的高鐵站"""
        # 1. 取得所有高鐵車站 (v2 API)
        # GET /v2/Rail/THSR/Station
        endpoint = "Rail/THSR/Station"
        params = {
            "$format": "JSON"
        }
        
        stations = await TDXBaseAPI.call_api(endpoint, params, cache_ttl=86400)
        
        if not stations:
            raise ExecutionError("無法取得高鐵車站資訊")
        
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
            raise ExecutionError("附近沒有高鐵車站資訊")
        
        stations_with_distance.sort(key=lambda x: x["distance_m"])
        nearest = stations_with_distance[:3]
        
        # 3. 格式化結果
        results = []
        for station in nearest:
            station_name = station.get("StationName", {}).get("Zh_tw", "未知")
            distance = station["distance_m"]
            driving_time = int(distance / 500)  # 假設開車 500m/min (30km/h)
            
            results.append({
                "station_name": station_name,
                "station_id": station.get("StationID"),
                "distance_m": int(distance),
                "driving_time_min": driving_time,
                "address": station.get("StationAddress", "")
            })
        
        content = cls._format_nearest_result(results)
        
        return cls.create_success_response(
            content=content,
            data={"stations": results}
        )
    
    @staticmethod
    def _get_station_code(station_name: str) -> Optional[str]:
        """中文站名轉站點代碼"""
        for name, code in TDXTHSRTool.STATION_MAP.items():
            if name in station_name or station_name in name:
                return code
        return None
    
    @staticmethod
    def _format_od_result(trains: List[Dict], origin: str, destination: str, date: str) -> str:
        """格式化起迄站查詢結果"""
        if not trains:
            return f"🚄 {origin} → {destination} ({date}) 目前無可搭乘高鐵"
        
        lines = [f"🚄 {origin} → {destination} ({date})\n"]
        
        for i, train in enumerate(trains, 1):
            duration_hours = train["duration_min"] // 60
            duration_mins = train["duration_min"] % 60
            
            if duration_hours > 0:
                duration_str = f"{duration_hours}小時{duration_mins}分"
            else:
                duration_str = f"{duration_mins}分鐘"
            
            fare_str = f" - ${train['fare']}" if train.get("fare") else ""
            
            lines.append(
                f"{i}. 高鐵 {train['train_no']}次\n"
                f"   {train['departure_time'][:5]} → {train['arrival_time'][:5]}"
                f"  ({duration_str}){fare_str}\n"
            )
        
        return "\n".join(lines)
    
    @staticmethod
    def _format_nearest_result(stations: List[Dict]) -> str:
        """格式化最近車站結果"""
        lines = ["📍 最近的高鐵站：\n"]
        
        for i, station in enumerate(stations, 1):
            lines.append(
                f"{i}. 🚄 {station['station_name']}\n"
                f"   開車約 {station['driving_time_min']} 分鐘 ({station['distance_m']/1000:.1f}km)\n"
                f"   {station.get('address', '')}\n"
            )
        
        return "\n".join(lines)
