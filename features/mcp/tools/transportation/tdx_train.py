"""
TDX 台鐵時刻表查詢工具
查詢台鐵列車時刻、票價、車站資訊
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from ..base_tool import MCPTool, StandardToolSchemas, ExecutionError
from .tdx_base import TDXBaseAPI
from core.database import get_user_env_current

logger = logging.getLogger("mcp.tools.tdx.train")


class TDXTrainTool(MCPTool):
    """TDX 台鐵時刻表查詢"""
    
    NAME = "tdx_train"
    DESCRIPTION = """Query Taiwan Railway (TRA) train schedules.
IMPORTANT Parameter Extraction Rules:
1. "from A to B" or "A to B" -> origin_station="A", destination_station="B"
2. "to B" or "going to B" -> destination_station="B" (origin determined by GPS)
3. "train 123" or "Tze-Chiang 123" -> train_no="123"
4. Includes time -> extract departure_time (HH:MM format)
Example: "Taichung to Kaohsiung" -> origin_station="台中", destination_station="高雄".
Never return empty parameters for station names!"""
    CATEGORY = "軌道運輸"
    TAGS = ["tdx", "台鐵", "TRA", "火車", "時刻表"]
    KEYWORDS = ["台鐵", "臺鐵", "火車", "TRA", "列車", "時刻", "自強號", "莒光號", "區間車"]
    USAGE_TIPS = [
        "「自強號 123 次」→ train_no=123",
        "「台北到台中的火車」→ origin_station=台北, destination_station=台中",
        "「往台北的火車」→ destination_station=台北（起點用 GPS）",
        "「下午3點台北到高雄」→ origin_station=台北, destination_station=高雄, departure_time=15:00"
    ]
    NEGATIVE_EXAMPLES = [
        "「火車票怎麼買」→ 這是詢問購票方式，不是查時刻表",
        "「火車站在哪」→ 這是查位置，應用 reverse_geocode 或 forward_geocode"
    ]
    PRIORITY = 8
    ALIASES = ["train", "台鐵", "火車"]
    
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
                        "duration_min": {"type": "integer"}
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
        
        origin = safe_str(arguments.get("origin_station"))
        destination = safe_str(arguments.get("destination_station"))
        train_no = safe_str(arguments.get("train_no"))
        departure_time = safe_str(arguments.get("departure_time"))
        train_type = arguments.get("train_type")
        limit = min(int(arguments.get("limit", 5)), 20)

        # 環境感知：如果沒有指定出發時間，自動使用當前時間（只顯示未來班次）
        if not departure_time:
            departure_time = datetime.now().strftime("%H:%M")
            logger.info(f"🚂 [Train] 未指定時間，自動使用當前時間: {departure_time}")
        
        # 1. 取得用戶位置（優先從 arguments 讀取，由 coordinator 注入）
        user_lat = arguments.get("lat")
        user_lon = arguments.get("lon")
        
        logger.info(f"🚂 [Train] 輸入參數: lat={user_lat}, lon={user_lon}, origin={origin}, dest={destination}, user_id={user_id}")
        
        # 從資料庫補充缺失的位置資訊（僅當 coordinator 沒有注入時）
        if user_id and (user_lat is None or user_lon is None):
            try:
                env_ctx = await get_user_env_current(user_id)
                logger.info(f"📍 [Train] 資料庫查詢結果: {env_ctx}")
                if env_ctx and env_ctx.get("success"):
                    ctx = env_ctx.get("context", {})
                    if user_lat is None:
                        user_lat = ctx.get("lat")
                    if user_lon is None:
                        user_lon = ctx.get("lon")
                    logger.info(f"📍 [Train] 補充後: lat={user_lat}, lon={user_lon}")
                else:
                    logger.warning(f"⚠️ [Train] 資料庫查詢失敗或無資料: {env_ctx}")
            except Exception as e:
                logger.warning(f"⚠️ [Train] 資料庫查詢異常: {e}")
        
        # 2. 驗證並清理站名（過濾無效值）
        origin = cls._validate_station_name(origin)
        destination = cls._validate_station_name(destination)
        logger.info(f"🚂 [Train] 驗證後: origin={origin}, dest={destination}")
        
        # 3. 查詢分支
        if train_no:
            # 查詢特定車次
            result = await cls._query_train_schedule(train_no)
        elif origin and destination:
            # 查詢起迄站列車
            result = await cls._query_od_trains(origin, destination, departure_time, train_type, limit)
        elif destination and not origin:
            # 只有目的地，用 GPS 找最近車站作為起點
            if not user_lat or not user_lon:
                logger.error(f"🚂 [Train] 查詢往{destination}但位置缺失: lat={user_lat}, lon={user_lon}")
                raise ExecutionError(f"🚂 想幫您查往{destination}的火車，但目前沒有您的位置資訊。請在 App 中開啟定位，或告訴我您從哪個車站出發（例如：從桃園到{destination}）")
            # 找最近車站作為起點
            nearest_result = await cls._query_nearest_station(user_lat, user_lon)
            # create_success_response 會把 data 直接 update 到 response，所以 stations 在頂層
            nearest_stations = nearest_result.get("stations", [])
            if not nearest_stations:
                raise ExecutionError("🚂 附近沒有找到台鐵車站，請直接告訴我您從哪個車站出發")
            origin = nearest_stations[0]["station_name"]
            logger.info(f"🚂 [Train] 自動設定起站: {origin}")
            result = await cls._query_od_trains(origin, destination, departure_time, train_type, limit)
        elif origin and not destination:
            # 只有起點，查詢從該站出發的列車（顯示最近車站資訊）
            if not user_lat or not user_lon:
                raise ExecutionError("🚂 請告訴我您要去哪裡，或開啟定位讓我幫您查詢最近的車站")
            result = await cls._query_nearest_station(user_lat, user_lon)
        elif not origin and not destination:
            # 查詢最近車站
            if not user_lat or not user_lon:
                logger.error(f"🚂 [Train] 查詢最近車站但位置缺失: lat={user_lat}, lon={user_lon}")
                raise ExecutionError("🚂 想幫您找最近的火車站，但目前沒有您的位置資訊。請在 App 中開啟定位，或直接告訴我起迄站（例如：台北到台中）")
            result = await cls._query_nearest_station(user_lat, user_lon)
        else:
            raise ExecutionError("🚂 請告訴我您要查詢的車次號碼，或起迄站名稱（例如：台北到高雄的火車）")
        
        return result
    
    @classmethod
    def _validate_station_name(cls, station_name: str) -> str:
        """驗證並清理站名，過濾無效值"""
        if not station_name:
            return ""
        
        # 無效的站名關鍵字（國家、地區等非具體車站名稱）
        invalid_keywords = [
            "台灣", "臺灣", "Taiwan", "taiwan",
            "中華民國", "ROC", "TW",
            "全部", "所有", "任何", "附近"
        ]
        
        for keyword in invalid_keywords:
            if keyword in station_name or station_name == keyword:
                logger.warning(f"⚠️ [Train] 過濾無效站名: {station_name}")
                return ""
        
        # 移除常見的後綴（如「站」「車站」「火車站」）以便匹配
        cleaned = station_name.replace("火車站", "").replace("車站", "").replace("站", "").strip()
        
        return cleaned if cleaned else station_name
    
    @classmethod
    async def _query_train_schedule(cls, train_no: str) -> Dict[str, Any]:
        """查詢特定車次時刻表"""
        today = datetime.now().strftime("%Y-%m-%d")
        
        # v3 API: GET /v3/Rail/TRA/DailyTrainTimetable/Today/TrainNo/{TrainNo}
        endpoint = f"Rail/TRA/DailyTrainTimetable/Today/TrainNo/{train_no}"
        params = {
            "$format": "JSON"
        }
        
        result = await TDXBaseAPI.call_api(endpoint, params, cache_ttl=1800, api_version="v3")
        
        # v3 回應結構: TrainTimetables 陣列
        trains = result.get("TrainTimetables", []) if isinstance(result, dict) else result
        
        if not trains:
            raise ExecutionError(f"找不到車次 {train_no}，請確認車次號碼")
        
        train_data = trains[0] if isinstance(trains, list) else trains
        
        # v3 結構: TrainInfo 包含列車資訊, StopTimes 包含停靠站
        train_info = train_data.get("TrainInfo", train_data)
        train_type = train_info.get("TrainTypeName", {}).get("Zh_tw", "未知")
        actual_train_no = train_info.get("TrainNo", train_no)
        
        # 取得停靠站資訊
        stops = train_data.get("StopTimes", [])
        
        if not stops:
            raise ExecutionError(f"車次 {train_no} 無停靠站資訊")
        
        # 格式化時刻表
        schedule_lines = [f"🚂 {train_type} {actual_train_no} 次\n"]
        
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
            data={"train": train_info, "stops": stops}
        )
    
    @staticmethod
    def _normalize_station_name(name: str) -> str:
        """正規化站名（處理繁簡字）"""
        # 台 → 臺 統一轉換
        return name.replace("台", "臺")

    @classmethod
    def _station_match(cls, query: str, station: str) -> bool:
        """站名匹配（支援繁簡字）"""
        # 正規化後比較
        query_norm = cls._normalize_station_name(query)
        station_norm = cls._normalize_station_name(station)
        return query_norm in station_norm

    @classmethod
    async def _query_od_trains(cls, origin: str, destination: str,
                              departure_time: Optional[str], train_type: Optional[str],
                              limit: int) -> Dict[str, Any]:
        """查詢起迄站列車"""
        # 1. 先取得今日所有列車 (v3 API)
        # GET /v3/Rail/TRA/DailyTrainTimetable/Today
        endpoint = "Rail/TRA/DailyTrainTimetable/Today"
        params = {
            "$format": "JSON"
        }

        result = await TDXBaseAPI.call_api(endpoint, params, cache_ttl=1800, api_version="v3")

        # v3 回應結構: TrainTimetables 陣列
        all_trains = result.get("TrainTimetables", []) if isinstance(result, dict) else result

        if not all_trains:
            raise ExecutionError("無法取得台鐵列車資訊")

        # 2. 過濾符合起迄站的列車
        matching_trains = []

        # Debug: 收集所有包含起點的車次（用於診斷）
        trains_with_origin = []

        for train_data in all_trains:
            # v3 結構: TrainInfo 包含列車資訊, StopTimes 包含停靠站
            train_info_obj = train_data.get("TrainInfo", train_data)
            stops = train_data.get("StopTimes", [])

            # 找起站和迄站（使用繁簡字相容的匹配）
            origin_idx, dest_idx = -1, -1
            all_station_names = []  # Debug: 收集所有站名
            for i, stop in enumerate(stops):
                station = stop.get("StationName", {}).get("Zh_tw", "")
                all_station_names.append(station)
                if cls._station_match(origin, station):
                    origin_idx = i
                if cls._station_match(destination, station):
                    dest_idx = i

            # Debug: 記錄有經過起點的車次
            if origin_idx >= 0:
                trains_with_origin.append({
                    "train_no": train_info_obj.get("TrainNo"),
                    "train_type": train_info_obj.get("TrainTypeName", {}).get("Zh_tw", "未知"),
                    "has_dest": dest_idx >= 0,
                    "origin_idx": origin_idx,
                    "dest_idx": dest_idx,
                    "all_stations": all_station_names  # 完整站名列表
                })

            # 起站在迄站之前才符合
            if origin_idx >= 0 and dest_idx > origin_idx:
                origin_stop = stops[origin_idx]
                dest_stop = stops[dest_idx]
                
                train_info = {
                    "train_no": train_info_obj.get("TrainNo"),
                    "train_type": train_info_obj.get("TrainTypeName", {}).get("Zh_tw", "未知"),
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
            # Debug 資訊
            logger.error(f"🚂 [Train] 找不到 {origin} 到 {destination} 的列車")
            logger.error(f"🚂 [Train] 經過 {origin} 的車次數: {len(trains_with_origin)}")
            if trains_with_origin:
                first_train = trains_with_origin[0]
                logger.error(f"🚂 [Train] 第一班車 {first_train['train_no']} 的所有站點: {first_train['all_stations']}")
                logger.error(f"🚂 [Train] 查詢目的地: '{destination}'")
                logger.error(f"🚂 [Train] 前 3 個經過起點的車次: {[{'train_no': t['train_no'], 'type': t['train_type'], 'has_dest': t['has_dest']} for t in trains_with_origin[:3]]}")
            raise ExecutionError(f"找不到 {origin} 到 {destination} 的列車（共掃描 {len(all_trains)} 班次，{len(trains_with_origin)} 班經過起點）")
        
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
        # 1. 取得所有車站 (v3 API)
        # GET /v3/Rail/TRA/Station
        endpoint = "Rail/TRA/Station"
        params = {
            "$format": "JSON"
        }
        
        result = await TDXBaseAPI.call_api(endpoint, params, cache_ttl=86400, api_version="v3")

        # v3 API 返回的是 dict，車站列表在 Stations 欄位
        if not result:
            raise ExecutionError("無法取得台鐵車站資訊")

        # 提取車站列表
        if isinstance(result, dict):
            stations = result.get("Stations", [])
        elif isinstance(result, list):
            # 向後兼容：如果直接返回 list
            stations = result
        else:
            logger.error(f"🚂 [Train] API 返回未知類型: {type(result).__name__}")
            raise ExecutionError(f"台鐵車站 API 返回格式錯誤")

        if not stations:
            raise ExecutionError("無法取得台鐵車站資訊（Stations 欄位為空）")

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

        lines = [f"🚂 {origin} → {destination} 有以下列車：\n"]

        for i, train in enumerate(trains, 1):
            duration_hours = train["duration_min"] // 60
            duration_mins = train["duration_min"] % 60

            if duration_hours > 0:
                duration_str = f"{duration_hours}小時{duration_mins}分"
            else:
                duration_str = f"{duration_mins}分鐘"

            # 改進格式：讓車次號碼更突出
            lines.append(
                f"{i}. 【{train['train_type']} {train['train_no']}次】"
                f" {train['departure_time'][:5]}出發 → {train['arrival_time'][:5]}抵達"
                f" (約{duration_str})"
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
