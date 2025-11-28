"""
TDX 公車即時到站工具
查詢附近公車站、特定路線到站時間

TDX CityBus API (v2):
- GET /v2/Bus/EstimatedTimeOfArrival/City/{City}/{RouteName} - 指定路線預估到站
- GET /v2/Bus/Stop/City/{City} - 市區公車站牌資料（支援 $spatialFilter）
- GET /v2/Bus/Route/City/{City}/{RouteName} - 指定路線資料

API 文件: https://tdx.transportdata.tw/api-service/swagger#/CityBus
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
    
    # TDX 城市代碼
    VALID_CITIES = {
        "Taipei", "NewTaipei", "Taoyuan", "Taichung", "Tainan", "Kaohsiung",
        "Keelung", "Hsinchu", "HsinchuCounty", "MiaoliCounty", "ChanghuaCounty",
        "NantouCounty", "YunlinCounty", "ChiayiCounty", "Chiayi", "PingtungCounty",
        "YilanCounty", "HualienCounty", "TaitungCounty", "KinmenCounty", 
        "PenghuCounty", "LienchiangCounty"
    }
    
    @classmethod
    def get_input_schema(cls) -> Dict[str, Any]:
        return StandardToolSchemas.create_input_schema({
            "route_name": {
                "type": "string",
                "description": "路線名稱（如「307」「紅30」）。不提供則查詢附近所有公車站"
            },
            "city": {
                "type": "string",
                "description": "城市（預設從環境感知自動判斷，支援中文或英文代碼）"
            },
            "limit": {
                "type": "integer",
                "description": "返回結果數量上限",
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
            "arrivals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "route_name": {"type": "string"},
                        "stop_name": {"type": "string"},
                        "direction": {"type": "integer"},
                        "estimate_time": {"type": "integer"},
                        "status": {"type": "string"}
                    }
                }
            }
        })
        return schema
    
    @classmethod
    async def execute(cls, arguments: Dict[str, Any]) -> Dict[str, Any]:
        # 從 arguments 中讀取 user_id（由 coordinator 注入）
        user_id = arguments.get("_user_id")
        
        route_name = str(arguments.get("route_name", "")).strip()
        limit = min(int(arguments.get("limit", 5)), 20)
        
        # 1. 取得用戶位置和城市
        user_lat = arguments.get("lat")
        user_lon = arguments.get("lon")
        city_param = str(arguments.get("city", "")).strip()
        
        print(f"🚌 [TDX] tdx_bus_arrival 輸入: route={route_name}, lat={user_lat}, lon={user_lon}, city={city_param}, user_id={user_id}")
        
        # 從資料庫補充位置和城市（僅當 coordinator 沒有注入時）
        if user_id and (user_lat is None or user_lon is None):
            try:
                env_ctx = await get_user_env_current(user_id)
                print(f"📍 [TDX] 資料庫環境查詢結果: {env_ctx}")
                if env_ctx and env_ctx.get("success"):
                    ctx = env_ctx.get("context", {})
                    # 補充缺失的位置資訊
                    if user_lat is None:
                        user_lat = ctx.get("lat")
                        print(f"📍 [TDX] 從資料庫補充 lat: {user_lat}")
                    if user_lon is None:
                        user_lon = ctx.get("lon")
                        print(f"📍 [TDX] 從資料庫補充 lon: {user_lon}")
                    # 優先使用環境中的城市（如果參數沒有指定）
                    if not city_param:
                        city_param = ctx.get("city", "")
                        print(f"📍 [TDX] 從資料庫補充 city: {city_param}")
            except Exception as e:
                print(f"⚠️ [TDX] 資料庫環境查詢失敗: {e}")
        
        print(f"🚌 [TDX] 補充後: lat={user_lat}, lon={user_lon}, city={city_param}")
        
        # 檢查必要條件
        if not route_name and (user_lat is None or user_lon is None):
            raise ExecutionError("無法取得您的位置，請提供路線名稱或開啟定位權限")
        
        # 2. 判斷城市代碼
        # 優先順序：即時反向地理編碼 > 環境參數 > 經緯度範圍推斷 > 預設值
        city_source = "預設"
        final_city = None
        
        # 2a. 如果有經緯度，嘗試即時反向地理編碼取得精確城市
        if user_lat is not None and user_lon is not None:
            print(f"🗺️ [TDX] 嘗試反向地理編碼: ({user_lat}, {user_lon})")
            geocoded_city = await cls._reverse_geocode_city(user_lat, user_lon)
            print(f"🗺️ [TDX] 反向地理編碼結果: {geocoded_city}")
            if geocoded_city:
                final_city = geocoded_city
                city_source = "反向地理編碼"
        
        # 2b. 如果反向地理編碼失敗，使用環境參數
        if not final_city and city_param:
            final_city = city_param
            city_source = "環境參數"
            print(f"📍 [TDX] 使用環境參數城市: {city_param}")
        
        # 2c. 如果還是沒有，使用經緯度範圍推斷
        if not final_city and user_lat is not None and user_lon is not None:
            guessed_city = cls._guess_city_from_location(user_lat, user_lon)
            print(f"📐 [TDX] 經緯度推斷結果: {guessed_city}")
            if guessed_city:
                final_city = guessed_city
                city_source = "經緯度推斷"
        
        # 2d. 轉換為 TDX 城市代碼
        city = cls._resolve_city(final_city or "")
        print(f"🏙️ [TDX] 最終城市: {city} (來源={city_source}, 原始={final_city})")
        
        # 3. 執行查詢
        if route_name:
            return await cls._query_route_arrival(route_name, city, user_lat, user_lon, limit)
        else:
            return await cls._query_nearby_stops(user_lat, user_lon, city, limit)
    
    @classmethod
    async def _query_route_arrival(
        cls, 
        route_name: str, 
        city: str, 
        user_lat: Optional[float], 
        user_lon: Optional[float],
        limit: int
    ) -> Dict[str, Any]:
        """
        查詢特定路線的即時到站（含公車目前位置）
        
        APIs:
        - GET /v2/Bus/EstimatedTimeOfArrival/City/{City}/{RouteName} - 預估到站時間
        - GET /v2/Bus/RealTimeNearStop/City/{City}/{RouteName} - 公車目前在哪站
        """
        print(f"🚌 [TDX] 查詢公車到站: 路線={route_name}, 城市={city}")
        
        # 1. 查詢預估到站時間
        eta_endpoint = f"Bus/EstimatedTimeOfArrival/City/{city}/{route_name}"
        eta_params = {"$orderby": "StopSequence", "$format": "JSON"}
        
        try:
            print(f"🌐 [TDX] 呼叫 API: {eta_endpoint}")
            arrival_data = await TDXBaseAPI.call_api(eta_endpoint, eta_params, cache_ttl=30)
            print(f"✅ [TDX] API 回應: {len(arrival_data) if arrival_data else 0} 筆資料")
            if arrival_data and len(arrival_data) > 0:
                print(f"📋 [TDX] 第一筆: {arrival_data[0].get('StopName', {}).get('Zh_tw')}")
        except ExecutionError as e:
            error_detail = str(e)
            print(f"❌ [TDX] API 錯誤: {error_detail}")
            if "404" in error_detail:
                raise ExecutionError(f"找不到路線「{route_name}」，請確認路線名稱與城市")
            raise ExecutionError(f"查詢路線「{route_name}」失敗: {error_detail}")
        
        if not arrival_data:
            print(f"⚠️ [TDX] 無資料，拋出錯誤")
            raise ExecutionError(f"路線「{route_name}」目前無班次資訊")
        
        # 2. 查詢公車即時位置（目前在哪站）
        realtime_endpoint = f"Bus/RealTimeNearStop/City/{city}/{route_name}"
        realtime_params = {"$format": "JSON"}
        
        bus_positions = {}  # {direction: [{plate, stop_name, stop_sequence, event_type}]}
        try:
            realtime_data = await TDXBaseAPI.call_api(realtime_endpoint, realtime_params, cache_ttl=15)
            if realtime_data:
                for bus in realtime_data:
                    direction = bus.get("Direction", 0)
                    plate = bus.get("PlateNumb", "")
                    stop_name = bus.get("StopName", {}).get("Zh_tw", "")
                    stop_sequence = bus.get("StopSequence", 0)  # 公車目前站序
                    event_type = bus.get("A2EventType", 0)  # 0=離站, 1=進站

                    if direction not in bus_positions:
                        bus_positions[direction] = []
                    bus_positions[direction].append({
                        "plate": plate,
                        "current_stop": stop_name,
                        "stop_sequence": stop_sequence,  # 新增站序
                        "event": "進站中" if event_type == 1 else "已離站"
                    })
        except Exception as e:
            logger.warning(f"⚠️ 無法取得公車即時位置: {e}")
        
        # 3. 取得路線全名
        route_obj = arrival_data[0].get("RouteName", {})
        full_route_name = route_obj.get("Zh_tw") or route_obj.get("En") or route_name
        
        # 4. 查詢站點座標、終點站資訊，並計算距離
        # EstimatedTimeOfArrival 不含座標，需查詢 StopOfRoute API 取得站序和座標
        destination_stations = {}  # {direction: destination_name}

        if user_lat and user_lon:
            try:
                # 使用 StopOfRoute API 取得該路線所有站點的座標
                stop_route_endpoint = f"Bus/StopOfRoute/City/{city}/{route_name}"
                stop_route_params = {"$format": "JSON"}
                stops_of_route = await TDXBaseAPI.call_api(stop_route_endpoint, stop_route_params, cache_ttl=3600)
                
                # 建立 StopUID -> 座標 的映射，並提取終點站資訊
                stop_positions = {}
                destination_stations = {}  # {direction: destination_name}
                if stops_of_route:
                    for route_dir in stops_of_route:
                        direction = route_dir.get("Direction", 0)
                        stops = route_dir.get("Stops", [])

                        # 提取終點站（Stops 陣列的最後一個站點）
                        if stops:
                            last_stop = stops[-1]
                            dest_name = last_stop.get("StopName", {}).get("Zh_tw", "")
                            if dest_name:
                                destination_stations[direction] = dest_name

                        # 建立座標映射
                        for stop in stops:
                            stop_uid = stop.get("StopUID")
                            pos = stop.get("StopPosition", {})
                            if stop_uid and pos.get("PositionLat") and pos.get("PositionLon"):
                                stop_positions[stop_uid] = (pos["PositionLat"], pos["PositionLon"])

                print(f"📍 [TDX] 從 StopOfRoute 取得 {len(stop_positions)} 個站點座標")
                print(f"🎯 [TDX] 終點站資訊: {destination_stations}")
                
                # 為每筆到站資料計算「用戶位置」到「站牌」的距離
                for arr in arrival_data:
                    stop_uid = arr.get("StopUID")
                    if stop_uid and stop_uid in stop_positions:
                        stop_lat, stop_lon = stop_positions[stop_uid]
                        arr["distance_m"] = TDXBaseAPI.haversine_distance(
                            user_lat, user_lon, stop_lat, stop_lon
                        )
                        arr["stop_lat"] = stop_lat
                        arr["stop_lon"] = stop_lon
                
                # 按距離排序（找出離用戶最近的站牌）
                arrival_data_with_dist = [a for a in arrival_data if a.get("distance_m") is not None]
                if arrival_data_with_dist:
                    arrival_data = sorted(arrival_data_with_dist, key=lambda x: x["distance_m"])
                    nearest = arrival_data[0]
                    print(f"📍 [TDX] 按距離排序完成，最近站: {nearest.get('StopName', {}).get('Zh_tw')} ({int(nearest['distance_m'])}m)")
                else:
                    print(f"⚠️ [TDX] 無法計算距離，stop_positions={len(stop_positions)}, arrival_data={len(arrival_data)}")
                    
            except Exception as e:
                print(f"⚠️ [TDX] 查詢站點座標失敗: {e}")
                import traceback
                traceback.print_exc()
        
        # 5. 處理到站資訊（只顯示最近的站牌，分去程/返程）
        arrivals = []
        seen_directions = set()
        
        for arr in arrival_data:
            direction = arr.get("Direction", 0)
            
            # 每個方向只取最近的一個站
            if direction in seen_directions:
                continue
            seen_directions.add(direction)
            
            stop_name = arr.get("StopName", {}).get("Zh_tw", "未知")
            estimate_time = arr.get("EstimateTime")
            stop_status = arr.get("StopStatus", 0)
            next_bus_time = arr.get("NextBusTime")
            user_stop_sequence = arr.get("StopSequence", 0)

            # 取得該方向的公車位置
            buses = bus_positions.get(direction, [])
            bus_info = buses[0] if buses else None

            # 判斷公車是否已過站
            bus_passed = False
            if bus_info and bus_info.get("stop_sequence"):
                bus_sequence = bus_info["stop_sequence"]
                # 如果公車已離站且站序 > 用戶站序，表示已過站
                if bus_info["event"] == "已離站" and bus_sequence > user_stop_sequence:
                    bus_passed = True
                    print(f"🚫 [TDX] 公車已過站: 公車在第 {bus_sequence} 站 > 用戶在第 {user_stop_sequence} 站")

            status_text = cls._get_status_text(stop_status, estimate_time, next_bus_time)

            # 如果公車已過站，標註或修改狀態
            if bus_passed:
                status_text = "已過站（等下一班）"
                # 清除公車位置資訊，因為這班已過站
                bus_info = None
            
            arrivals.append({
                "route_name": full_route_name,
                "stop_name": stop_name,
                "direction": direction,
                "destination_station": destination_stations.get(direction, ""),  # 終點站
                "estimate_time": estimate_time,
                "next_bus_time": next_bus_time,
                "status": status_text,
                "distance_m": int(arr.get("distance_m", 0)),
                "stop_sequence": arr.get("StopSequence", 0),
                "bus_current_stop": bus_info["current_stop"] if bus_info else None,
                "bus_event": bus_info["event"] if bus_info else None,
                "bus_plate": bus_info["plate"] if bus_info else None
            })
            
            if len(arrivals) >= limit:
                break
        
        print(f"📊 [TDX] 最終結果: {len(arrivals)} 筆到站資訊")
        for arr in arrivals:
            print(f"   - {arr['stop_name']} ({arr['status']})")
        
        content = cls._format_arrival_result(arrivals, full_route_name, user_lat is not None)
        print(f"📝 [TDX] 格式化內容:\n{content}")
        
        return cls.create_success_response(
            content=content,
            data={"arrivals": arrivals, "route_name": full_route_name, "bus_positions": bus_positions}
        )
    
    @classmethod
    async def _query_nearby_stops(
        cls, 
        lat: float, 
        lon: float, 
        city: str, 
        limit: int
    ) -> Dict[str, Any]:
        """
        查詢附近公車站
        
        API: GET /v2/Bus/Stop/City/{City}?$spatialFilter=nearby(lat, lon, distance)
        """
        endpoint = f"Bus/Stop/City/{city}"
        params = {
            "$spatialFilter": f"nearby({lat}, {lon}, 500)",
            "$top": limit * 3,
            "$format": "JSON"
        }
        
        stops = await TDXBaseAPI.call_api(endpoint, params, cache_ttl=1800)
        
        if not stops:
            return cls.create_success_response(
                content="附近 500 公尺內沒有公車站，請擴大範圍或移動位置",
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
        
        stops = [s for s in stops if s.get("distance_m") is not None]
        stops.sort(key=lambda x: x["distance_m"])
        
        # 去重複站名
        results = []
        seen_names = set()
        
        for stop in stops:
            name = stop.get("StopName", {}).get("Zh_tw") or stop.get("StopName", {}).get("En") or "未知"
            if name in seen_names:
                continue
            seen_names.add(name)
            
            distance = stop["distance_m"]
            results.append({
                "stop_name": name,
                "distance_m": int(distance),
                "walking_time_min": int(distance / 80),
                "stop_uid": stop.get("StopUID")
            })
            
            if len(results) >= limit:
                break
        
        content = cls._format_nearby_result(results)
        
        return cls.create_success_response(
            content=content,
            data={"stops": results}
        )
    
    @classmethod
    async def _reverse_geocode_city(cls, lat: float, lon: float) -> Optional[str]:
        """使用 Nominatim 反向地理編碼取得精確城市名稱"""
        import aiohttp
        
        url = "https://nominatim.openstreetmap.org/reverse"
        params = {
            "format": "jsonv2",
            "lat": lat,
            "lon": lon,
            "zoom": 10,  # 城市級別
            "addressdetails": 1
        }
        headers = {"User-Agent": "BloomWare/1.0"}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status != 200:
                        logger.warning(f"反向地理編碼失敗: HTTP {resp.status}")
                        return None
                    
                    data = await resp.json()
                    if not data or not isinstance(data, dict):
                        return None
                    
                    addr = data.get("address", {})
                    # 優先使用 city，其次 county
                    city = addr.get("city") or addr.get("county") or addr.get("town") or ""
                    
                    # 移除「市」「縣」後綴以便匹配
                    city = city.replace("市", "").replace("縣", "").strip()
                    
                    logger.debug(f"Nominatim 回應城市: {city}")
                    return city if city else None
                    
        except Exception as e:
            logger.warning(f"反向地理編碼異常: {e}")
            return None
    
    @classmethod
    def _guess_city_from_location(cls, lat: float, lon: float) -> str:
        """根據經緯度推斷城市（台灣主要城市範圍）- 備用方案
        
        注意：順序很重要！較小範圍的城市要放在前面，避免被大範圍城市覆蓋
        """
        # 台灣主要城市的大致經緯度範圍
        # 順序：小範圍城市優先，大範圍城市（新北）放最後
        city_bounds = [
            # (城市名, 緯度下限, 緯度上限, 經度下限, 經度上限)
            # 桃園市（擴大範圍到經度 121.40，涵蓋桃園全境）
            ("桃園", 24.73, 25.12, 120.90, 121.40),
            # 台北市（市中心區域）
            ("台北", 24.95, 25.10, 121.45, 121.62),
            # 基隆市
            ("基隆", 25.08, 25.20, 121.69, 121.82),
            # 新北市（範圍較大，放在最後）
            ("新北", 24.67, 25.30, 121.35, 122.01),
            # 新竹市/縣
            ("新竹", 24.68, 24.90, 120.90, 121.10),
            # 苗栗縣
            ("苗栗", 24.30, 24.75, 120.65, 121.20),
            # 台中市
            ("台中", 24.00, 24.45, 120.45, 121.05),
            # 彰化縣
            ("彰化", 23.80, 24.20, 120.25, 120.70),
            # 南投縣
            ("南投", 23.45, 24.25, 120.55, 121.35),
            # 雲林縣
            ("雲林", 23.50, 23.90, 120.05, 120.60),
            # 嘉義市/縣
            ("嘉義", 23.25, 23.65, 120.15, 120.70),
            ("台南", 22.85, 23.40, 120.00, 120.55),
            ("高雄", 22.45, 23.15, 120.15, 120.80),
            ("屏東", 21.90, 22.90, 120.35, 120.95),
            ("宜蘭", 24.30, 24.85, 121.55, 122.00),
            ("花蓮", 23.50, 24.35, 121.20, 121.70),
            ("台東", 22.35, 23.55, 120.75, 121.55),
        ]
        
        for city_name, lat_min, lat_max, lon_min, lon_max in city_bounds:
            in_lat = lat_min <= lat <= lat_max
            in_lon = lon_min <= lon <= lon_max
            if in_lat and in_lon:
                logger.info(f"🗺️ 座標 ({lat}, {lon}) 匹配城市: {city_name}")
                return city_name
        
        # 無法匹配，記錄詳細資訊
        logger.warning(f"⚠️ 座標 ({lat}, {lon}) 無法匹配任何城市範圍")
        return ""
    
    @classmethod
    def _resolve_city(cls, city_param: str) -> str:
        """解析城市參數為 TDX 城市代碼"""
        if not city_param:
            logger.warning("⚠️ 無法判斷城市，使用預設值 Taipei")
            return "Taipei"
        
        # 已經是有效代碼
        if city_param in cls.VALID_CITIES:
            return city_param
        
        # 中文轉換
        city_map = {
            "台北": "Taipei", "臺北": "Taipei", "台北市": "Taipei", "臺北市": "Taipei",
            "新北": "NewTaipei", "新北市": "NewTaipei",
            "桃園": "Taoyuan", "桃園市": "Taoyuan",
            "台中": "Taichung", "臺中": "Taichung", "台中市": "Taichung", "臺中市": "Taichung",
            "台南": "Tainan", "臺南": "Tainan", "台南市": "Tainan", "臺南市": "Tainan",
            "高雄": "Kaohsiung", "高雄市": "Kaohsiung",
            "基隆": "Keelung", "基隆市": "Keelung",
            "新竹": "Hsinchu", "新竹市": "Hsinchu", "新竹縣": "HsinchuCounty",
            "嘉義": "Chiayi", "嘉義市": "Chiayi", "嘉義縣": "ChiayiCounty",
            "苗栗": "MiaoliCounty", "苗栗縣": "MiaoliCounty",
            "彰化": "ChanghuaCounty", "彰化縣": "ChanghuaCounty",
            "南投": "NantouCounty", "南投縣": "NantouCounty",
            "雲林": "YunlinCounty", "雲林縣": "YunlinCounty",
            "屏東": "PingtungCounty", "屏東縣": "PingtungCounty",
            "宜蘭": "YilanCounty", "宜蘭縣": "YilanCounty",
            "花蓮": "HualienCounty", "花蓮縣": "HualienCounty",
            "台東": "TaitungCounty", "臺東": "TaitungCounty", 
            "台東縣": "TaitungCounty", "臺東縣": "TaitungCounty",
            "金門": "KinmenCounty", "金門縣": "KinmenCounty",
            "澎湖": "PenghuCounty", "澎湖縣": "PenghuCounty",
            "連江": "LienchiangCounty", "連江縣": "LienchiangCounty", "馬祖": "LienchiangCounty"
        }
        
        # 精確匹配
        if city_param in city_map:
            return city_map[city_param]
        
        # 部分匹配
        for key, value in sorted(city_map.items(), key=lambda x: -len(x[0])):
            if key in city_param:
                return value
        
        logger.warning(f"無法識別城市: {city_param}，使用預設值 Taipei")
        return "Taipei"
    
    @staticmethod
    def _get_status_text(stop_status: int, estimate_time: Optional[int], next_bus_time: Optional[str] = None) -> str:
        """根據狀態碼、預估時間和下一班發車時間產生狀態文字"""
        from datetime import datetime
        
        if stop_status == 0:  # 正常
            if estimate_time is not None:
                minutes = estimate_time // 60
                if minutes <= 1:
                    return "即將進站"
                return f"{minutes} 分鐘"
            return "進站中"
        elif stop_status == 1:  # 尚未發車
            # 如果有下一班發車時間，顯示預計發車時間
            if next_bus_time:
                try:
                    # 解析 ISO 格式時間: 2025-11-28T15:23:00+08:00
                    next_time = datetime.fromisoformat(next_bus_time.replace('Z', '+00:00'))
                    time_str = next_time.strftime("%H:%M")
                    return f"預計 {time_str} 發車"
                except Exception:
                    pass
            return "尚未發車"
        elif stop_status == 2:
            return "交管不停靠"
        elif stop_status == 3:
            return "末班車已過"
        elif stop_status == 4:
            return "今日未營運"
        return "未知"
    
    @staticmethod
    def _format_arrival_result(arrivals: List[Dict], route_name: str, has_location: bool) -> str:
        """格式化到站結果（含公車目前位置和終點站）"""
        if not arrivals:
            return f"路線 {route_name} 目前無即時到站資訊"

        lines = [f"🚌 {route_name} 即時資訊：\n"]

        for arr in arrivals:
            direction_text = "去程" if arr["direction"] == 0 else "返程"

            # 終點站資訊
            destination = arr.get("destination_station", "")
            if destination:
                direction_label = f"【{direction_text} → {destination}】"
            else:
                direction_label = f"【{direction_text}】"

            # 最近站牌資訊
            dist_info = ""
            if has_location and arr.get("distance_m"):
                dist = arr["distance_m"]
                walk_time = max(1, int(dist / 80))
                dist_info = f"（步行 {walk_time} 分鐘）"

            lines.append(direction_label)
            lines.append(f"📍 最近站牌: {arr['stop_name']} {dist_info}")

            # 公車目前位置
            if arr.get("bus_current_stop"):
                lines.append(f"🚌 公車位置: {arr['bus_current_stop']}（{arr.get('bus_event', '')}）")

            # 預估到站時間
            lines.append(f"⏱️ 預估到站: {arr['status']}")
            lines.append("")

        return "\n".join(lines).strip()
    
    @staticmethod
    def _format_nearby_result(stops: List[Dict]) -> str:
        """格式化附近站點結果"""
        if not stops:
            return "附近沒有找到公車站"
        
        lines = ["📍 附近的公車站：\n"]
        
        for i, stop in enumerate(stops, 1):
            lines.append(
                f"{i}. 🚏 {stop['stop_name']}\n"
                f"   步行 {stop['walking_time_min']} 分鐘 ({stop['distance_m']}m)"
            )
        
        lines.append("\n💡 提供路線名稱可查詢即時到站時間")
        
        return "\n".join(lines)
