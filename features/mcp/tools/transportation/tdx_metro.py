"""
TDX 捷運即時資訊工具
支援台北捷運、高雄捷運、桃園捷運、台中捷運
"""

import logging
from typing import Dict, Any, List, Optional

from ..base_tool import MCPTool, StandardToolSchemas, ExecutionError
from .tdx_base import TDXBaseAPI
from .tdx_location import resolve_location_context, resolve_metro_operator_candidates
from core.database import get_user_env_current

logger = logging.getLogger("mcp.tools.tdx.metro")


class TDXMetroTool(MCPTool):
    """TDX 捷運即時到站查詢"""
    
    NAME = "tdx_metro"
    DESCRIPTION = "Query metro/MRT real-time arrivals and nearest stations (Taipei/Kaohsiung/Taoyuan/Taichung metro systems)"
    CATEGORY = "軌道運輸"
    TAGS = ["tdx", "捷運", "MRT", "即時到站"]
    KEYWORDS = ["捷運", "MRT", "地鐵", "metro", "到站"]
    USAGE_TIPS = [
        "查詢最近捷運站: 「最近的捷運站在哪」",
        "查詢特定站點: 「台北車站捷運幾分鐘到」",
        "指定路線: 「板南線 市政府站」"
    ]
    
    # TDX 捷運系統對應
    METRO_SYSTEMS = {
        "台北": "TRTC",
        "臺北": "TRTC",
        "高雄": "KRTC",
        "桃園": "TYMC",
        "台中": "TMRT",
        "臺中": "TMRT"
    }
    
    @classmethod
    def get_input_schema(cls) -> Dict[str, Any]:
        return StandardToolSchemas.create_input_schema({
            "station_name": {
                "type": "string",
                "description": "車站名稱（如「台北車站」「西門站」）。不提供則查詢最近車站"
            },
            "metro_system": {
                "type": "string",
                "description": "捷運系統（TRTC=台北, KRTC=高雄, TYMC=桃園, TMRT=台中）",
                "enum": ["TRTC", "KRTC", "TYMC", "TMRT"]
            },
            "line": {
                "type": "string",
                "description": "路線名稱（如「板南線」「淡水信義線」）"
            },
            "location_query": {
                "type": "string",
                "description": "精確地址、地標或站區（如「桃園火車站」「台北101」）。提供時優先解析為座標做最近站查詢"
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
            "arrivals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "station_name": {"type": "string"},
                        "line_name": {"type": "string"},
                        "destination": {"type": "string"},
                        "arrival_time_sec": {"type": "integer"},
                        "train_status": {"type": "string"}
                    }
                }
            }
        })
        return schema
    
    @classmethod
    async def execute(cls, arguments: Dict[str, Any]) -> Dict[str, Any]:
        # 從 arguments 中讀取 user_id（由 coordinator 注入）
        user_id = arguments.get("_user_id")
        
        station_name = arguments.get("station_name", "").strip()
        metro_system = arguments.get("metro_system")
        line_filter = arguments.get("line")
        location_query = arguments.get("location_query", "").strip()
        
        # 1. 取得用戶位置和城市（優先從 arguments 讀取，由 coordinator 注入）
        user_lat = arguments.get("lat")
        user_lon = arguments.get("lon")
        user_city = arguments.get("city", "")
        
        logger.info(f"🚇 [Metro] 輸入參數: lat={user_lat}, lon={user_lon}, city={user_city}, station={station_name}, user_id={user_id}")
        
        # 從資料庫補充缺失的位置資訊（僅當 coordinator 沒有注入時）
        if user_id and (user_lat is None or user_lon is None):
            try:
                env_ctx = await get_user_env_current(user_id)
                logger.info(f"📍 [Metro] 資料庫查詢結果: {env_ctx}")
                if env_ctx and env_ctx.get("success"):
                    ctx = env_ctx.get("context", {})
                    if user_lat is None:
                        user_lat = ctx.get("lat")
                    if user_lon is None:
                        user_lon = ctx.get("lon")
                    if not user_city:
                        user_city = ctx.get("city", "")
                    logger.info(f"📍 [Metro] 補充後: lat={user_lat}, lon={user_lon}, city={user_city}")
                else:
                    logger.warning(f"⚠️ [Metro] 資料庫查詢失敗或無資料: {env_ctx}")
            except Exception as e:
                logger.warning(f"⚠️ [Metro] 資料庫查詢異常: {e}")
        
        # 檢查必要條件
        if not station_name and (user_lat is None or user_lon is None):
            logger.error(f"🚇 [Metro] 位置資訊缺失: lat={user_lat}, lon={user_lon}, station_name={station_name}")
            raise ExecutionError("🚇 想幫您找附近的捷運站，但目前沒有您的位置資訊。請在 App 中開啟定位，或告訴我您想查詢哪個車站")
        
        location_ctx = await resolve_location_context(
            lat=user_lat,
            lon=user_lon,
            location_query=location_query,
            city_like=user_city,
        )
        user_lat = location_ctx["lat"]
        user_lon = location_ctx["lon"]
        geo = location_ctx.get("geo") or {}
        operator_candidates = [metro_system] if metro_system else resolve_metro_operator_candidates(
            city_like=user_city,
            geo_city=geo.get("city"),
            geo_admin=geo.get("admin"),
        )
        metro_system = operator_candidates[0] if operator_candidates else "TRTC"
        logger.info(f"🚇 最終使用捷運系統候選: {operator_candidates}")
        
        # 3. 查詢邏輯
        if station_name:
            result = await cls._query_station_arrival(station_name, metro_system, line_filter)
        else:
            if not user_lat or not user_lon:
                raise ExecutionError("🚇 想幫您找附近的捷運站，但目前沒有您的位置資訊。請開啟定位，或直接提供地址/地標")
            result = await cls._query_nearest_station(user_lat, user_lon, operator_candidates)
        
        return result
    
    @classmethod
    async def _query_station_arrival(cls, station_name: str, metro_system: str, 
                                     line_filter: Optional[str]) -> Dict[str, Any]:
        """查詢特定車站的即時到站"""
        # 1. 查詢車站資訊 (v2 API)
        # GET /v2/Rail/Metro/Station/{Operator}
        station_endpoint = f"Rail/Metro/Station/{metro_system}"
        station_params = {
            "$filter": f"contains(StationName/Zh_tw, '{station_name}')",
            "$format": "JSON",
            "$top": 5
        }
        
        stations = await TDXBaseAPI.call_api(station_endpoint, station_params, cache_ttl=3600)
        
        if not stations:
            raise ExecutionError(f"找不到車站「{station_name}」")
        
        # 2. 如果有多個結果，優先選擇完全匹配
        target_station = None
        for station in stations:
            name = station.get("StationName", {}).get("Zh_tw", "")
            if name == station_name:
                target_station = station
                break
        
        if not target_station:
            target_station = stations[0]
        
        station_uid = target_station.get("StationUID")
        full_station_name = target_station.get("StationName", {}).get("Zh_tw", station_name)
        
        # 3. 查詢即時到站 (v2 API)
        # GET /v2/Rail/Metro/LiveBoard/{Operator}
        arrival_endpoint = f"Rail/Metro/LiveBoard/{metro_system}"
        arrival_params = {
            "$filter": f"StationUID eq '{station_uid}'",
            "$format": "JSON"
        }
        
        arrivals = await TDXBaseAPI.call_api(arrival_endpoint, arrival_params, cache_ttl=15)
        
        if not arrivals:
            return cls.create_success_response(
                content=f"🚇 {full_station_name} 目前無即時到站資訊",
                data={"arrivals": []}
            )
        
        # 4. 路線過濾
        if line_filter:
            arrivals = [a for a in arrivals if line_filter in a.get("LineName", {}).get("Zh_tw", "")]
        
        # 5. 格式化結果
        results = []
        for arr in arrivals[:10]:  # 最多 10 筆
            line_name = arr.get("LineName", {}).get("Zh_tw", "未知路線")
            dest = arr.get("DestinationStationName", {}).get("Zh_tw", "未知")
            arrival_time = arr.get("ArrivalTime", 0)
            status_code = arr.get("TrainStatus", 0)
            
            status_map = {
                0: "正常",
                1: "尚未發車",
                2: "交管不停靠",
                3: "末班車已過",
                4: "今日未營運"
            }
            status = status_map.get(status_code, "未知")
            
            results.append({
                "station_name": full_station_name,
                "line_name": line_name,
                "destination": dest,
                "arrival_time_sec": arrival_time,
                "train_status": status
            })
        
        content = cls._format_arrival_result(results, full_station_name)
        
        return cls.create_success_response(
            content=content,
            data={"arrivals": results}
        )
    
    @classmethod
    async def _query_nearest_station(cls, lat: float, lon: float, metro_systems: List[str]) -> Dict[str, Any]:
        """查詢最近的捷運站"""
        all_stations = []
        # 1. 取得所有捷運系統的車站資訊（並行查詢優化）
        tasks = []
        for ms in metro_systems:
            endpoint = f"Rail/Metro/Station/{ms}"
            params = {"$format": "JSON"}
            tasks.append(TDXBaseAPI.call_api(endpoint, params, cache_ttl=3600))
        
        logger.info(f"🚇 [Metro] 開始並行查詢 {len(tasks)} 個捷運系統的車站資料")
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, stations in enumerate(responses):
            if isinstance(stations, Exception):
                logger.warning(f"⚠️ 捷運系統 {metro_systems[i]} 查詢失敗: {stations}")
                continue
            if stations:
                for station in stations:
                    station["_operator"] = metro_systems[i]
                all_stations.extend(stations)

        if not all_stations:
            raise ExecutionError("無法取得捷運站資訊")
        
        # 2. 計算距離
        for station in all_stations:
            pos = station.get("StationPosition", {})
            if pos.get("PositionLat") and pos.get("PositionLon"):
                station["distance_m"] = TDXBaseAPI.haversine_distance(
                    lat, lon,
                    pos["PositionLat"], pos["PositionLon"]
                )
        
        stations_with_distance = [s for s in all_stations if "distance_m" in s]
        
        if not stations_with_distance:
            raise ExecutionError("附近沒有捷運站資訊")
        
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
                "distance_m": int(distance),
                "walking_time_min": walking_time,
                "station_uid": station.get("StationUID"),
                "address": station.get("StationAddress", ""),
                "operator": station.get("_operator"),
            })
        
        content = cls._format_nearest_result(results)
        
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
            ("台中", 24.00, 24.45, 120.45, 121.05),
            ("高雄", 22.45, 23.15, 120.15, 120.80),
        ]
        
        for city_name, lat_min, lat_max, lon_min, lon_max in city_bounds:
            if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
                return city_name
        
        return ""
    
    @staticmethod
    def _detect_metro_system(city: str) -> str:
        """根據城市自動偵測捷運系統"""
        if not city:
            return "TRTC"
        
        for key, code in TDXMetroTool.METRO_SYSTEMS.items():
            if key in city:
                return code
        return "TRTC"  # 預設台北
    
    @staticmethod
    def _format_arrival_result(arrivals: List[Dict], station_name: str) -> str:
        """格式化到站資訊"""
        if not arrivals:
            return f"🚇 {station_name} 目前無列車資訊"
        
        lines = [f"🚇 {station_name} 即時到站：\n"]
        
        # 按路線分組
        lines_dict = {}
        for arr in arrivals:
            line = arr["line_name"]
            if line not in lines_dict:
                lines_dict[line] = []
            lines_dict[line].append(arr)
        
        for line_name, line_arrivals in lines_dict.items():
            lines.append(f"━━ {line_name} ━━")
            
            for arr in line_arrivals[:3]:  # 每條路線最多 3 筆
                dest = arr["destination"]
                time_sec = arr["arrival_time_sec"]
                status = arr["train_status"]
                
                if time_sec > 0:
                    time_min = time_sec // 60
                    time_str = f"{time_min} 分 {time_sec % 60} 秒" if time_min > 0 else f"{time_sec} 秒"
                    lines.append(f"  → {dest}  {time_str}")
                else:
                    lines.append(f"  → {dest}  {status}")
            
            lines.append("")
        
        return "\n".join(lines)
    
    @staticmethod
    def _format_nearest_result(stations: List[Dict]) -> str:
        """格式化最近車站結果"""
        lines = ["📍 最近的捷運站：\n"]
        
        for i, station in enumerate(stations, 1):
            lines.append(
                f"{i}. 🚇 {station['station_name']}\n"
                f"   步行 {station['walking_time_min']} 分鐘 ({station['distance_m']}m)\n"
            )
        
        return "\n".join(lines)
