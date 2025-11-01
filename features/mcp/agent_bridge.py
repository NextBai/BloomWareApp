"""
MCP + Agent 橋接層
整合 MCP Tools 與 Agent 邏輯，保持與舊 FeatureRouter 相同的介面
"""

import json
import logging
import asyncio
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
from .server import FeaturesMCPServer
import services.ai_service as ai_service
from services.ai_service import StrictResponseError
from core.reasoning_strategy import get_optimal_reasoning_effort
from core.database import get_user_env_current

logger = logging.getLogger("mcp.agent_bridge")
logger.setLevel(logging.DEBUG)  # 強制設置為 DEBUG 級別


def _safe_json(data: Any, limit: int = 1200) -> str:
    """序列化資料為 JSON 供日誌使用，避免爆炸性輸出"""
    try:
        text = json.dumps(data, ensure_ascii=False, default=str)
    except Exception:
        text = str(data)

    if len(text) > limit:
        return f"{text[:limit]}... (truncated)"
    return text


class MCPAgentBridge:
    """MCP + Agent 橋接器，提供與舊 FeatureRouter 相同的介面"""

    def __init__(self):
        # 初始化 MCP 服務器
        self.mcp_server = FeaturesMCPServer()

        # 註冊系統工具
        self.mcp_server._register_system_tools()

        # 多輪對話狀態管理
        self._pending: Dict[str, Dict[str, Any]] = {}

        # 意圖檢測快取（2025 最佳實踐：激進化 TTL）
        # 同一用戶短時間內重複查詢相同內容的機率高（如「台北天氣」）
        self._intent_cache: Dict[str, Tuple[bool, Optional[Dict[str, Any]], float]] = {}
        self._intent_cache_ttl = 300.0  # 5分鐘（60s → 300s，提升命中率 40-60%）

        logger.info("MCP Agent 橋接層初始化完成")
        logger.info(f"初始可用 MCP 工具數量: {len(self.mcp_server.tools)} (將在異步發現後更新)")

    async def async_initialize(self):
        """異步初始化，發現所有工具 + 快取預熱"""
        if hasattr(self.mcp_server, 'start_external_servers'):
            await self.mcp_server.start_external_servers()
            logger.info(f"異步初始化完成，完整可用 MCP 工具數量: {len(self.mcp_server.tools)}")

        # 2025 最佳實踐：啟動時預熱熱門查詢快取
        await self._preheat_cache()

    def _normalize_tool_name(self, raw_name: Optional[str]) -> Optional[str]:
        """
        將 GPT 回傳的工具名稱正規化為註冊表中的實際名稱。

        - 去除前後空白
        - 將空白與破折號統一轉為底線
        - 以不分大小寫方式匹配既有工具名稱
        """
        if not raw_name:
            return None

        candidate = raw_name.strip()
        if not candidate:
            return None

        candidate = candidate.replace("-", "_").replace(" ", "_")
        if candidate in self.mcp_server.tools:
            return candidate

        candidate_lower = candidate.lower()
        for registered_name in self.mcp_server.tools.keys():
            if registered_name.lower() == candidate_lower:
                return registered_name

        return None
    async def _fetch_env_context(self, user_id: Optional[str]) -> Dict[str, Any]:
        """讀取使用者最近的環境資訊（Firestore current snapshot）。"""
        if not user_id:
            return {}
        try:
            env_res = await get_user_env_current(user_id)
            if env_res.get("success"):
                ctx = env_res.get("context") or {}
                return ctx
        except Exception as e:
            logger.debug(f"無法取得使用者 {user_id} 環境資訊: {e}")
        return {}

    async def _enrich_arguments_with_env(self, tool_name: str, arguments: Dict[str, Any], user_id: Optional[str]) -> Dict[str, Any]:
        """自動將環境資訊補入 MCP 工具參數，讓位置相關功能更聰明。"""
        if not user_id:
            return arguments

        tool_name = (tool_name or "").strip()
        if tool_name not in {"weather_query"}:
            return arguments

        ctx = await self._fetch_env_context(user_id)
        if not ctx:
            return arguments

        enriched = dict(arguments or {})

        def _safe_float(val):
            try:
                if val is None:
                    return None
                return float(val)
            except (TypeError, ValueError):
                return None

        if tool_name == "weather_query":
            if enriched.get("lat") is None:
                lat = _safe_float(ctx.get("lat"))
                if lat is not None:
                    enriched["lat"] = lat
            if enriched.get("lon") is None:
                lon = _safe_float(ctx.get("lon"))
                if lon is not None:
                    enriched["lon"] = lon
            city_arg = str(enriched.get("city") or "").strip()
            ctx_city = str(ctx.get("city") or "").strip()
            if not city_arg and ctx_city:
                enriched["city"] = ctx_city

        if enriched != arguments:
            logger.info(f"📍 已自動補齊 {tool_name} 參數: {_safe_json(enriched)}")

        return enriched

    async def _resolve_coordinate_label(self, lat: Any, lon: Any) -> Optional[str]:
        """透過 reverse_geocode 將座標轉換為可朗讀的地點名稱。"""
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (TypeError, ValueError):
            return None

        reverse_tool = self.mcp_server.tools.get("reverse_geocode")
        if not reverse_tool or not reverse_tool.handler:
            return None

        try:
            res = await reverse_tool.handler({"lat": lat_f, "lon": lon_f})
        except Exception as ge:
            logger.debug(f"reverse_geocode 失敗: {ge}")
            return None

        if not isinstance(res, dict):
            return None
        if not res.get("success"):
            return None

        payload = res.get("data") or res
        label = (
            payload.get("label")
            or payload.get("display_name")
            or ", ".join(
                part for part in [payload.get("city"), payload.get("admin")] if part
            )
        )
        return label.strip() if label else None

    async def _prepare_route_arguments(self, arguments: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, str]]:
        """為 directions 工具補齊可讀地點名稱並正規化座標。"""
        prepared = dict(arguments or {})
        labels: Dict[str, str] = {}

        def _normalize_coord(value: Any) -> Optional[float]:
            try:
                if value is None:
                    return None
                return float(value)
            except (TypeError, ValueError):
                return None

        for prefix, default_label in (("origin", "起點"), ("dest", "目的地")):
            lat_key = f"{prefix}_lat"
            lon_key = f"{prefix}_lon"
            label_key = f"{prefix}_label"

            lat_val = _normalize_coord(prepared.get(lat_key))
            lon_val = _normalize_coord(prepared.get(lon_key))
            if lat_val is not None:
                prepared[lat_key] = lat_val
            if lon_val is not None:
                prepared[lon_key] = lon_val

            label_val = str(prepared.get(label_key) or "").strip()
            if not label_val and lat_val is not None and lon_val is not None:
                label_val = await self._resolve_coordinate_label(lat_val, lon_val) or ""

            if not label_val:
                label_val = default_label

            prepared[label_key] = label_val
            labels[label_key] = label_val

        return prepared, labels

    @staticmethod
    def _format_distance(distance_m: Optional[float]) -> str:
        """將距離換算為人類可讀格式。"""
        if distance_m is None:
            return "未知距離"
        try:
            distance = float(distance_m)
        except (TypeError, ValueError):
            return "未知距離"

        if distance >= 1000:
            return f"{distance / 1000:.1f} 公里"
        return f"{round(distance)} 公尺"

    @staticmethod
    def _format_duration(duration_s: Optional[float]) -> str:
        """將秒數換算為人類可讀格式。"""
        if duration_s is None:
            return "未知時間"
        try:
            total_seconds = int(round(float(duration_s)))
        except (TypeError, ValueError):
            return "未知時間"

        minutes = total_seconds // 60
        if minutes < 1:
            return "不到 1 分鐘"

        hours = minutes // 60
        remaining_minutes = minutes % 60

        if hours and remaining_minutes:
            return f"{hours} 小時 {remaining_minutes} 分"
        if hours:
            return f"{hours} 小時"
        return f"{minutes} 分鐘"

    def _build_directions_message(
        self,
        tool_data: Dict[str, Any],
        labels: Dict[str, str],
    ) -> Tuple[str, Dict[str, Any]]:
        """依據 directions 工具回傳資料，產出友善訊息與乾淨的 tool_data。"""
        origin_label = labels.get("origin_label") or tool_data.get("origin_label") or "起點"
        dest_label = labels.get("dest_label") or tool_data.get("dest_label") or "目的地"

        distance_m = tool_data.get("distance_m")
        duration_s = tool_data.get("duration_s")

        distance_str = self._format_distance(distance_m)
        duration_str = self._format_duration(duration_s)

        polite_message = (
            f"從 {origin_label} 前往 {dest_label} 大約需要 {duration_str}，"
            f"總距離約 {distance_str}。"
        )

        sanitized_tool_data = dict(tool_data or {})
        sanitized_tool_data["origin_label"] = origin_label
        sanitized_tool_data["dest_label"] = dest_label
        sanitized_tool_data["distance_readable"] = distance_str
        sanitized_tool_data["duration_readable"] = duration_str

        return polite_message, sanitized_tool_data

    @staticmethod
    def _haversine_km(lat1: Optional[float], lon1: Optional[float], lat2: Optional[float], lon2: Optional[float]) -> Optional[float]:
        """計算兩點之間的近似球面距離（公里）。"""
        try:
            from math import radians, sin, cos, sqrt, atan2

            if None in (lat1, lon1, lat2, lon2):
                return None

            rlat1, rlon1, rlat2, rlon2 = map(radians, [lat1, lon1, lat2, lon2])
            dlat = rlat2 - rlat1
            dlon = rlon2 - rlon1
            a = sin(dlat / 2) ** 2 + cos(rlat1) * cos(rlat2) * sin(dlon / 2) ** 2
            c = 2 * atan2(sqrt(a), sqrt(1 - a))
            earth_radius_km = 6371.0
            return earth_radius_km * c
        except Exception:
            return None

    def _build_directions_failure_response(
        self,
        arguments: Dict[str, Any],
        labels: Dict[str, str],
        error_message: str,
    ) -> Dict[str, Any]:
        """建立 directions 工具失敗時的替代回傳內容。"""
        origin_label = labels.get("origin_label") or arguments.get("origin_label") or "起點"
        dest_label = labels.get("dest_label") or arguments.get("dest_label") or "目的地"

        o_lat = arguments.get("origin_lat")
        o_lon = arguments.get("origin_lon")
        d_lat = arguments.get("dest_lat")
        d_lon = arguments.get("dest_lon")

        distance_km = self._haversine_km(o_lat, o_lon, d_lat, d_lon)
        distance_m = distance_km * 1000 if distance_km is not None else None
        distance_str = self._format_distance(distance_m)

        # 推估行駛時間：假設平均速率 35km/h
        duration_seconds = None
        if distance_km is not None:
            duration_minutes = max(5, int(round((distance_km / 35) * 60)))
            duration_seconds = duration_minutes * 60

        duration_str = self._format_duration(duration_seconds)

        message = (
            f"目前無法向路線服務取得詳細路線，但從 {origin_label} 前往 {dest_label} 直線距離約 {distance_str}，"
            f"若以車輛移動約需 {duration_str}。建議在 Google 地圖或 Apple 地圖輸入上述地點，以獲得即時的轉乘與路況。"
        )

        fallback_payload = {
            "fallback": True,
            "origin_label": origin_label,
            "dest_label": dest_label,
            "distance_estimated_m": distance_m,
            "distance_readable": distance_str,
            "duration_estimated_s": duration_seconds,
            "duration_readable": duration_str,
            "error": error_message,
        }

        return {
            "message": message,
            "tool_name": "directions",
            "tool_data": fallback_payload,
        }

    def get_current_time_data(self) -> Dict[str, Any]:
        """
        獲取當前時間數據，用於生成個性化歡迎詞
        返回格式與舊 time_service 兼容
        """
        now = datetime.now()

        # 獲取時間段
        hour = now.hour
        if 5 <= hour < 12:
            day_period = "上午"
        elif 12 <= hour < 18:
            day_period = "下午"
        elif 18 <= hour < 22:
            day_period = "晚上"
        else:
            day_period = "深夜" if hour >= 22 else "凌晨"

        # 星期幾中文名稱
        weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        weekday_full_chinese = weekdays[now.weekday()]

        return {
            "year": now.year,
            "month": now.month,
            "day": now.day,
            "hour": hour,
            "minute": now.minute,
            "second": now.second,
            "weekday": now.weekday(),  # 0-6, 星期一到星期日
            "weekday_full_chinese": weekday_full_chinese,
            "day_period": day_period,
            "timestamp": now.timestamp(),
            "iso_format": now.isoformat()
        }

    async def detect_intent(self, message: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        檢測用戶消息中的意圖 (保持與舊 FeatureRouter 相同介面)
        使用 OpenAI Structured Outputs 確保100%返回有效JSON
        帶快取機制，相同消息直接返回

        參數:
        message (str): 用戶消息

        返回:
        tuple: (是否檢測到意圖, 意圖數據)
        """
        import hashlib
        import time as time_module

        # 生成快取鍵
        cache_key = hashlib.md5(message.encode()).hexdigest()

        # 檢查快取
        if cache_key in self._intent_cache:
            has_feature, intent_data, cached_time = self._intent_cache[cache_key]
            # 檢查是否過期
            if time_module.time() - cached_time < self._intent_cache_ttl:
                logger.debug(f"💾 意圖快取命中: {message[:50]}...")
                return has_feature, intent_data
            else:
                # 過期，刪除快取
                del self._intent_cache[cache_key]

        logger.info(f"檢測意圖: \"{message}\"")
        logger.debug("意圖偵測輸入 - user_id=%s, chat_id=%s", "intent_detection", None)

        # 檢查特殊命令
        for command in ["功能列表", "有什麼功能", "能做什麼"]:
            if command in message:
                logger.info(f"檢測到特殊命令: {command}")
                return True, {
                    "type": "special_command",
                    "command": "feature_list"
                }

        # 使用 GPT + Structured Outputs 進行意圖解析
        try:
            logger.info("開始使用 GPT Structured Outputs 進行意圖解析")

            # 構建可用工具的描述
            tools_description = self._get_tools_description()

            # GPT 意圖解析 Prompt - 適配新的 schema（不使用 oneOf）
            system_prompt = f"""你是一個精確的意圖解析助手。

可用工具：
{tools_description}

任務：分析用戶消息，決定是否需要調用工具，並判斷用戶情緒。

重要規則：
1. 健康相關需求（心率、步數、血氧、呼吸、睡眠）使用 healthkit_query
2. 不需要傳入 user_id，系統會自動補齊
3. 若無法判斷具體參數，使用合理預設值
4. 一般閒聊設置 is_tool_call 為 false

特殊處理：
- 天氣查詢：城市名稱必須使用英文（如 Taipei, Tokyo, New York）
  * 台北 → Taipei
  * 東京 → Tokyo
  * 紐約 → New York
  * 倫敦 → London
  * 巴黎 → Paris
  * 如無指定城市，預設使用 Taipei

- 匯率查詢：
  * 必須明確指定 from_currency 和 to_currency（ISO 4217 代碼）
  * 預設：from_currency=USD, to_currency=TWD
  * 美元 → USD, 台幣 → TWD, 日圓 → JPY, 歐元 → EUR
  * 金額預設 amount=1.0, conversion=true

- 新聞查詢：
  * 任何提到「新聞」「消息」「報導」的請求都使用 news_query
  * 參數：query（關鍵詞）、country（國家，預設 tw）、category（分類，預設 top）、language（語言，預設 zh）
  * 今日新聞、科技新聞、台灣新聞都應該調用此工具

- 地點查詢與導航（重要！）：
  * **導航需求判斷**：
    - 問「怎麼去 X」「如何去 X」「去 X 怎麼走」「到 X 怎麼走」→ 使用 forward_geocode 查詢目的地座標
    - 問「從 A 到 B 要多久」「A 到 B 怎麼走」→ 同時使用 forward_geocode 查詢起點與終點
  * **不要猜測座標**：
    - ❌ 錯誤：directions:origin_lat=25.1288,origin_lon=121.9234,dest_lat=24.9932,dest_lon=121.3261
    - ✅ 正確：forward_geocode:query=銘傳大學桃園校區
  * **工具使用順序**：
    1. 先使用 forward_geocode 將地點名稱轉換為座標
    2. 再使用 directions 規劃路線（系統會自動處理）
  * **範例**：
    - 「怎麼去桃園火車站」→ forward_geocode:query=桃園火車站
    - 「從銘傳大學到桃園火車站」→ forward_geocode:query=銘傳大學桃園校區
    - 「台北車站到淡水捷運站」→ forward_geocode:query=台北車站

情緒判斷（emotion）：
根據文字的語氣、用詞、標點符號判斷用戶情緒，選擇以下之一：
- neutral: 平靜、中性（預設）
- happy: 開心、興奮、愉快（如「好開心！」「太棒了」「哈哈」）
- sad: 難過、沮喪、失落（如「好難過」「唉...」「心情不好」）
- angry: 生氣、憤怒、煩躁（如「煩死了」「幹嘛啦」「氣死我了」）
- fear: 恐懼、擔心、焦慮（如「好害怕」「好擔心」「怎麼辦」）
- surprise: 驚訝、意外（如「什麼！」「真的假的」「不會吧」）

回應格式：
- is_tool_call: true/false（是否調用工具）
- tool_name: 工具名稱和參數（僅當 is_tool_call=true 時提供，格式：tool_name:param1=value1,param2=value2）
- emotion: 用戶情緒標籤（必填）

示例：
- "台北天氣" → {{"is_tool_call": true, "tool_name": "weather_query:city=Taipei", "emotion": "neutral"}}
- "好開心！今天天氣好嗎" → {{"is_tool_call": true, "tool_name": "weather_query:city=Taipei", "emotion": "happy"}}
- "美元匯率" → {{"is_tool_call": true, "tool_name": "exchange_query:from_currency=USD,to_currency=TWD,amount=1.0", "emotion": "neutral"}}
- "今日新聞" → {{"is_tool_call": true, "tool_name": "news_query:country=tw,language=zh", "emotion": "neutral"}}
- "科技新聞" → {{"is_tool_call": true, "tool_name": "news_query:query=科技,category=technology,language=zh", "emotion": "neutral"}}
- "你好" → {{"is_tool_call": false, "tool_name": "", "emotion": "neutral"}}
- "我好難過..." → {{"is_tool_call": false, "tool_name": "", "emotion": "sad"}}
- "煩死了" → {{"is_tool_call": false, "tool_name": "", "emotion": "angry"}}"""

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ]

            # 使用 Structured Outputs（動態推理強度）
            optimal_effort = get_optimal_reasoning_effort("intent_detection")
            logger.info(f"🧠 意圖檢測推理強度: {optimal_effort}")

            response = await ai_service.generate_response_for_user(
                messages=messages,
                user_id="intent_detection",
                model="gpt-5-nano",
                chat_id=None,
                use_structured_outputs=True,
                response_schema=self._get_intent_schema(),
                reasoning_effort=optimal_effort  # 動態調整
            )

            logger.debug("GPT Structured Outputs 回應: %s", response)

            # 檢查是否為 fallback 錯誤訊息
            if response.strip() in ["抱歉，我暫時沒有合適的回應。可以換個說法再試試嗎？", "抱歉，生成回應時遇到問題。請重試。"]:
                logger.warning("Structured Outputs 返回 fallback 訊息，視為失敗")
                raise Exception("Structured Outputs failed with fallback message")

            # Structured Outputs 保證返回有效JSON，直接解析
            try:
                intent_data = json.loads(response.strip())
                logger.debug("解析後的意圖資料: %s", _safe_json(intent_data))

                # 新的 schema 格式：is_tool_call, tool_name（包含參數）
                is_tool_call = intent_data.get("is_tool_call", False)

                if is_tool_call:
                    tool_name_with_params = intent_data.get("tool_name", "").strip()

                    if not tool_name_with_params:
                        logger.warning("⚠️ GPT 標記為工具調用但未提供工具名稱，降級為聊天")
                        return False, None

                    raw_tool_name = tool_name_with_params
                    params_str = ""
                    if ":" in tool_name_with_params:
                        raw_tool_name, params_str = tool_name_with_params.split(":", 1)

                    tool_name = self._normalize_tool_name(raw_tool_name)
                    if not tool_name:
                        logger.warning(f"⚠️ 工具 {raw_tool_name} 無法對應到註冊名稱，降級為聊天")
                        return False, None

                    # 解析參數
                    arguments = {}
                    if params_str.strip():
                        for param_pair in params_str.split(","):
                            if "=" not in param_pair:
                                continue
                            key, value = param_pair.split("=", 1)
                            key = key.strip()
                            value = value.strip()

                            # 跳過空鍵或空值（避免傳入空字串導致驗證失敗）
                            if not key or not value:
                                continue

                            # 嘗試類型轉換
                            normalized_value = value
                            if value.isdigit():
                                normalized_value = int(value)
                            else:
                                lower_value = value.lower()
                                if lower_value in ("true", "false"):
                                    normalized_value = lower_value == "true"
                                else:
                                    try:
                                        normalized_value = float(value)
                                    except ValueError:
                                        normalized_value = value

                            arguments[key] = normalized_value

                    logger.info(f"✅ GPT 檢測到工具調用: {raw_tool_name.strip()} → {tool_name}")
                    logger.debug("工具調用參數: %s", _safe_json(arguments))

                    # 驗證工具是否存在
                    if tool_name not in self.mcp_server.tools:
                        logger.warning(f"⚠️ 工具 {tool_name} 不存在，降級為聊天")
                        return False, None

                    # 基礎參數驗證（可選，Structured Outputs 已保證格式）
                    tool = self.mcp_server.tools[tool_name]
                    if hasattr(tool, 'handler') and hasattr(tool.handler, '__self__'):
                        tool_class = tool.handler.__self__
                        if hasattr(tool_class, 'validate_input'):
                            try:
                                validated_args = tool_class.validate_input(arguments)
                                logger.debug("✓ 參數驗證通過: %s", _safe_json(validated_args))
                            except Exception as e:
                                logger.warning(f"⚠️ 參數驗證失敗: {e}，仍然嘗試執行")
                                # 不中斷，讓工具自己處理

                    # 提取情緒（新增）
                    emotion = intent_data.get("emotion", "neutral")
                    logger.info(f"😊 偵測到情緒: {emotion}")

                    intent_result = (True, {
                        "type": "mcp_tool",
                        "tool_name": tool_name,
                        "arguments": arguments,
                        "emotion": emotion  # 新增情緒欄位
                    })

                    # 寫入快取
                    self._intent_cache[cache_key] = (*intent_result, time_module.time())
                    logger.debug(f"💾 意圖結果已快取: {tool_name}")

                    return intent_result

                else:
                    # is_tool_call = False，表示一般聊天
                    logger.info("💬 GPT 判斷為一般聊天")

                    # 提取情緒（新增）
                    emotion = intent_data.get("emotion", "neutral")
                    logger.info(f"😊 偵測到情緒: {emotion}")

                    # 寫入快取（一般聊天也要回傳情緒）
                    intent_result = (False, {"emotion": emotion})
                    self._intent_cache[cache_key] = (*intent_result, time_module.time())

                    return intent_result

            except json.JSONDecodeError as e:
                # Structured Outputs 不應該發生這種錯誤，記錄異常
                logger.error(f"❌ Structured Outputs JSON 解析失敗（異常情況）: {e}, response: {response}")
                return False, None

        except Exception as e:
            logger.error(f"❌ GPT 意圖解析發生錯誤: {e}")
            # 降級處理：使用關鍵詞匹配
            logger.info("🔄 嘗試使用關鍵詞匹配作為降級方案")
            try:
                fallback_result = self._keyword_intent_detection(message)
                if fallback_result[0]:
                    logger.info("✅ 關鍵詞匹配成功")
                    return fallback_result
            except Exception as fallback_error:
                logger.error(f"❌ 關鍵詞匹配也失敗: {fallback_error}")

        # 最終降級：視為一般聊天
        logger.info("💬 降級為一般聊天")
        return False, None

    def _get_intent_schema(self) -> Dict[str, Any]:
        """
        獲取意圖檢測的 JSON Schema (用於 Structured Outputs)
        確保 GPT 返回符合此格式的回應

        注意：OpenAI Structured Outputs strict mode 不支援 oneOf/anyOf/allOf
        改用簡化的 schema，由 GPT 自行判斷邏輯

        新增：emotion 欄位用於文字情緒偵測
        """
        return {
            "type": "object",
            "properties": {
                "is_tool_call": {
                    "type": "boolean",
                    "description": "是否需要調用工具（true=調用工具，false=一般聊天）"
                },
                "tool_name": {
                    "type": "string",
                    "description": "要調用的工具名稱（is_tool_call為true時必填）"
                },
                "emotion": {
                    "type": "string",
                    "enum": ["neutral", "happy", "sad", "angry", "fear", "surprise"],
                    "description": "用戶的情緒狀態（根據文字語氣、用詞、標點符號判斷）"
                }
            },
            "required": ["is_tool_call", "tool_name", "emotion"],
            "additionalProperties": False
        }

    def _get_tools_description(self) -> str:
        """獲取簡化的工具描述，專注於核心信息"""
        descriptions = []

        for tool_name, tool in self.mcp_server.tools.items():
            # 簡化描述格式
            desc = f"{tool_name}: {tool.description}"

            # 只保留最重要的參數信息
            input_schema = tool.inputSchema
            properties = input_schema.get("properties", {})

            if properties:
                # 只顯示必需參數
                required = input_schema.get("required", [])
                if required:
                    params = []
                    for param_name in required:
                        if param_name in properties:
                            param_info = properties[param_name]
                            param_type = param_info.get("type", "string")
                            params.append(f"{param_name}({param_type})")
                    if params:
                        desc += f" | 參數: {', '.join(params)}"

            descriptions.append(desc)

        return "\n".join(descriptions)

    def _keyword_intent_detection(self, message: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """關鍵詞匹配檢測 (備用方案)"""
        message_lower = message.lower()

        # 天氣檢測
        weather_keywords = ["天氣", "氣溫", "下雨", "晴天", "陰天", "weather"]
        if any(kw in message_lower for kw in weather_keywords):
            # 簡單城市提取
            import re
            city_match = re.search(r'([^\s，。！？]+)\s*天氣', message)
            city = city_match.group(1) if city_match else "台北"

            return True, {
                "type": "mcp_tool",
                "tool_name": "weather_query",
                "arguments": {"city": city}
            }

        # 新聞檢測
        news_keywords = ["新聞", "消息", "報導", "news"]
        if any(kw in message_lower for kw in news_keywords):
            return True, {
                "type": "mcp_tool",
                "tool_name": "news_query",
                "arguments": {"language": "zh-TW", "limit": 5}
            }

        # 匯率檢測
        exchange_keywords = ["匯率", "美元", "台幣", "exchange", "usd", "twd"]
        if any(kw in message_lower for kw in exchange_keywords):
            return True, {
                "type": "mcp_tool",
                "tool_name": "exchange_query",
                "arguments": {"from_currency": "USD", "to_currency": "TWD"}
            }

        return False, None

    async def process_intent(self, intent_data: Dict[str, Any],
                           user_id: str = None, original_message: str = "",
                           chat_id: Optional[str] = None) -> str:
        """
        處理用戶意圖 (保持與舊 FeatureRouter 相同介面)

        參數:
        intent_data (dict): 意圖數據
        user_id (str): 用戶 ID
        original_message (str): 原始消息
        chat_id (str): 聊天 ID

        返回:
        str: 處理結果
        """
        logger.info(f"處理意圖類型: {intent_data.get('type', 'unknown')}")

        intent_type = intent_data.get("type", "")

        # 處理特殊命令
        if intent_type == "special_command":
            command = intent_data.get("command", "")
            if command == "feature_list":
                return self.get_feature_list()
            else:
                return f"未知命令: {command}"

        # 處理一般聊天
        elif intent_type == "chat":
            # 返回 None 表示這是聊天，不應該被當作功能處理
            return None

        # 處理 MCP 工具調用
        elif intent_type == "mcp_tool":
            tool_name = intent_data.get("tool_name")
            arguments = intent_data.get("arguments", {})

            # 補齊健康工具必要參數
            if tool_name == "healthkit_query":
                if (not arguments.get("user_id")) and user_id:
                    arguments = {**arguments, "user_id": user_id}
                    logger.info("自動補齊 healthkit_query user_id")
                if "metric_type" not in arguments or not arguments["metric_type"]:
                    arguments = {**arguments, "metric_type": "all"}

            return await self._call_mcp_tool(tool_name, arguments, user_id, original_message)

        else:
            logger.warning(f"未知意圖類型: {intent_type}")
            return f"抱歉，無法理解您的請求。"

    async def _call_mcp_tool(self, tool_name: str, arguments: Dict[str, Any],
                           user_id: str = None, original_message: str = "") -> str:
        """
        調用 MCP 工具（帶智慧重試機制 + 統一格式化 + 智能地點查詢）
        2025年最佳實踐：指數退避重試 + 錯誤分類 + AI 格式化 + 自動 geocoding
        """
        if tool_name not in self.mcp_server.tools:
            return self._generate_tool_not_found_error(tool_name)

        tool = self.mcp_server.tools[tool_name]
        if not tool.handler:
            return f"⚠️ 工具 {tool_name} 尚未實作，請稍後再試"

        # 智能地點查詢：如果是 forward_geocode，且用戶有位置導航需求，自動串接 directions
        is_navigation_intent = False
        geocode_result = None
        
        if tool_name == "forward_geocode":
            # 判斷是否為導航意圖（「怎麼去」「如何去」「到 X」）
            nav_keywords = ["怎麼去", "如何去", "怎麼走", "到哪", "去哪", "要多久", "多遠"]
            is_navigation_intent = any(keyword in original_message for keyword in nav_keywords)
            
            if is_navigation_intent:
                logger.info(f"🗺️ 檢測到導航意圖，先執行地點查詢: {arguments.get('query')}")
                
                # 執行 geocoding
                geocode_tool = self.mcp_server.tools.get("forward_geocode")
                if geocode_tool and geocode_tool.handler:
                    try:
                        geocode_result = await asyncio.wait_for(
                            geocode_tool.handler(arguments),
                            timeout=15.0
                        )
                        
                        if geocode_result.get("success"):
                            best_match = geocode_result.get("data", {}).get("best_match", {})
                            dest_lat = best_match.get("lat")
                            dest_lon = best_match.get("lon")
                            dest_label = best_match.get("label", arguments.get("query"))
                            
                            # 取得用戶當前位置
                            env_ctx = await self._fetch_env_context(user_id)
                            origin_lat = env_ctx.get("lat")
                            origin_lon = env_ctx.get("lon")
                            origin_label = env_ctx.get("label") or env_ctx.get("address_display") or "您的位置"
                            
                            if origin_lat and origin_lon and dest_lat and dest_lon:
                                logger.info(f"🚗 自動串接導航: {origin_label} → {dest_label}")
                                
                                # 自動調用 directions
                                directions_tool = self.mcp_server.tools.get("directions")
                                if directions_tool and directions_tool.handler:
                                    directions_args = {
                                        "origin_lat": float(origin_lat),
                                        "origin_lon": float(origin_lon),
                                        "dest_lat": float(dest_lat),
                                        "dest_lon": float(dest_lon),
                                        "origin_label": origin_label,
                                        "dest_label": dest_label,
                                        "mode": "foot-walking"  # 預設步行
                                    }
                                    
                                    # 遞迴調用 directions（會走下面的正常流程）
                                    return await self._call_mcp_tool(
                                        "directions",
                                        directions_args,
                                        user_id,
                                        original_message
                                    )
                            else:
                                logger.warning("⚠️ 無法取得完整位置資訊，返回地點查詢結果")
                        else:
                            logger.warning(f"⚠️ 地點查詢失敗: {geocode_result.get('error')}")
                    except Exception as e:
                        logger.error(f"❌ 自動地點查詢失敗: {e}", exc_info=True)

        arguments = await self._enrich_arguments_with_env(tool_name, arguments, user_id)
        route_labels: Dict[str, str] = {}
        if tool_name == "directions":
            arguments, route_labels = await self._prepare_route_arguments(arguments)

        logger.info(f"🔧 調用 MCP 工具: {tool_name}")
        logger.debug("📋 調用參數: %s", _safe_json(arguments))

        # 重試設定
        max_retries = 3
        retry_delays = [1, 2, 5]  # 指數退避（秒）
        
        for attempt in range(max_retries):
            try:
                # 調用工具
                result = await asyncio.wait_for(
                    tool.handler(arguments),
                    timeout=30.0  # 30秒超時
                )
                logger.debug("📤 工具回傳: %s", _safe_json(result))

                # 處理結果
                if isinstance(result, dict):
                    if result.get("success"):
                        content = result.get("content", "")

                        # 檢查內容是否有效
                        if not content or content.strip() == "":
                            logger.warning(f"⚠️ 工具 {tool_name} 返回空內容")
                            return f"✓ 工具 {tool_name} 執行成功，但沒有返回內容"

                        # 成功!決策是否需要 AI 二次格式化
                        logger.info(f"✅ 工具 {tool_name} 執行成功")

                        # 保留原始數據供前端使用
                        # 排除標準回應欄位，保留業務資料（如 rate, health_data, raw_data 等）
                        excluded_keys = {'success', 'content', 'error', 'error_code', 'metadata'}
                        tool_data = {k: v for k, v in result.items() if k not in excluded_keys}

                        # 如果沒有業務資料，fallback 到 data 或 raw_data
                        if not tool_data:
                            tool_data = result.get("data") or result.get("raw_data")

                        logger.debug(f"📊 提取的 tool_data: {type(tool_data)} = {tool_data if tool_data is None or isinstance(tool_data, (str, int, bool)) else '<dict/list>'}")

                        if tool_name == "directions":
                            message, sanitized_tool_data = self._build_directions_message(
                                tool_data if isinstance(tool_data, dict) else {},
                                route_labels,
                            )
                            content = message
                            tool_data = sanitized_tool_data

                        if self._should_reformat(tool_name, content):
                            logger.info(f"🎨 啟用 AI 格式化: {tool_name}")
                            try:
                                formatted_content = await self._format_tool_response(
                                    tool_name, content, original_message
                                )
                                # 返回擴充格式（dict），包含工具資訊
                                result_dict = {
                                    "message": formatted_content,
                                    "tool_name": tool_name,
                                    "tool_data": tool_data
                                }
                                logger.debug(f"🔙 返回格式化結果: message=<{len(formatted_content)} chars>, tool_name={tool_name}, tool_data={'None' if tool_data is None else 'present'}")
                                return result_dict
                            except Exception as e:
                                logger.warning(f"⚠️ AI 格式化失敗，返回原始內容: {e}")
                                # 格式化失敗仍然返回擴充格式
                                result_dict = {
                                    "message": content,
                                    "tool_name": tool_name,
                                    "tool_data": tool_data
                                }
                                logger.debug(f"🔙 返回原始結果: message=<{len(content)} chars>, tool_name={tool_name}, tool_data={'None' if tool_data is None else 'present'}")
                                return result_dict
                        else:
                            # 直接返回工具自己的格式化結果（擴充格式）
                            result_dict = {
                                "message": content,
                                "tool_name": tool_name,
                                "tool_data": tool_data
                            }
                            logger.debug(f"🔙 返回直接結果: message=<{len(content)} chars>, tool_name={tool_name}, tool_data={'None' if tool_data is None else 'present'}")
                            return result_dict
                    
                    else:
                        # 失敗：檢查是否值得重試
                        error = result.get("error", "工具執行失敗")
                        error_lower = error.lower()
                        
                        # 可重試的錯誤類型
                        retryable_errors = [
                            "timeout", "網路", "network", "連接", "connection",
                            "暫時", "temporary", "unavailable", "不可用"
                        ]
                        
                        is_retryable = any(keyword in error_lower for keyword in retryable_errors)
                        
                        if is_retryable and attempt < max_retries - 1:
                            delay = retry_delays[attempt]
                            logger.warning(f"⚠️ 工具 {tool_name} 執行失敗（可重試）: {error}")
                            logger.info(f"🔄 等待 {delay} 秒後重試... (嘗試 {attempt + 1}/{max_retries})")
                            await asyncio.sleep(delay)
                            continue  # 重試
                        else:
                            # 不可重試的錯誤或已達最大重試次數
                            logger.error(f"❌ 工具 {tool_name} 執行失敗: {error}")
                            return self._generate_helpful_error(tool_name, error, original_message)
                
                else:
                    # 非標準格式回應
                    logger.debug("工具回傳非標準格式，直接返回")
                    return str(result)

            except asyncio.TimeoutError:
                if attempt < max_retries - 1:
                    delay = retry_delays[attempt]
                    logger.warning(f"⏱️ 工具 {tool_name} 超時，{delay} 秒後重試... (嘗試 {attempt + 1}/{max_retries})")
                    await asyncio.sleep(delay)
                    continue
                else:
                    logger.error(f"❌ 工具 {tool_name} 多次超時")
                    return f"⏱️ 操作超時，請稍後再試\n\n建議：\n• 檢查網路連接\n• 稍等片刻後重新嘗試\n• 或試試其他功能"

            except Exception as e:
                error_msg = str(e)
                error_lower = error_msg.lower()

                if tool_name == "directions":
                    logger.error(f"❌ directions 工具失敗，啟用替代回覆: {error_msg}")
                    fallback_result = self._build_directions_failure_response(arguments, route_labels, error_msg)
                    return fallback_result

                # 判斷是否值得重試
                is_retryable = any(keyword in error_lower for keyword in ["timeout", "network", "connection"])
                
                if is_retryable and attempt < max_retries - 1:
                    delay = retry_delays[attempt]
                    logger.warning(f"⚠️ 工具 {tool_name} 調用異常: {e}，{delay} 秒後重試...")
                    await asyncio.sleep(delay)
                    continue
                else:
                    logger.exception(f"❌ 調用 MCP 工具失敗: {e}")
                    return self._generate_helpful_error(tool_name, error_msg, original_message)

        # 所有重試都失敗
        logger.error(f"❌ 工具 {tool_name} 在 {max_retries} 次嘗試後仍然失敗")
        return f"❌ 調用 {tool_name} 失敗\n\n已嘗試 {max_retries} 次，建議：\n• 檢查網路連接\n• 稍後再試\n• 或聯繫管理員"

    def _generate_tool_not_found_error(self, tool_name: str) -> str:
        """生成工具不存在的友善錯誤訊息"""
        available_tools = list(self.mcp_server.tools.keys())
        
        # 尋找相似的工具名稱（簡單的模糊匹配）
        similar_tools = [t for t in available_tools if tool_name.lower() in t.lower() or t.lower() in tool_name.lower()]
        
        error_msg = f"⚠️ 抱歉，我目前還不支援「{tool_name}」功能。\n\n"
        
        if similar_tools:
            error_msg += f"你是不是想用：\n"
            for t in similar_tools[:3]:  # 最多顯示3個
                tool_desc = self.mcp_server.tools[t].description
                error_msg += f"• {t}: {tool_desc}\n"
        else:
            error_msg += "可用功能：\n"
            # 按類別顯示
            categories = {}
            for t_name, tool in self.mcp_server.tools.items():
                category = tool.metadata.get("category", "其他") if tool.metadata else "其他"
                if category not in categories:
                    categories[category] = []
                categories[category].append(f"• {tool.description}")
            
            for category, tools in list(categories.items())[:3]:  # 最多顯示3個類別
                error_msg += f"\n【{category}】\n"
                error_msg += "\n".join(tools[:2]) + "\n"  # 每類最多2個
        
        error_msg += "\n輸入「/功能」查看完整功能列表"
        return error_msg

    def _generate_helpful_error(self, tool_name: str, error: str, original_message: str) -> str:
        """生成有幫助的錯誤訊息"""
        error_lower = error.lower()
        
        # API錯誤
        if "api" in error_lower or "key" in error_lower or "auth" in error_lower:
            return f"🔑 服務認證問題\n\n抱歉，{tool_name} 服務暫時無法使用（API設定問題）。\n\n建議：\n• 請稍後再試\n• 或試試其他功能\n• 聯繫管理員檢查 API 設定"
        
        # 網路錯誤
        elif "network" in error_lower or "connection" in error_lower or "timeout" in error_lower:
            return f"🌐 網路連接問題\n\n無法連接到 {tool_name} 服務。\n\n建議：\n• 檢查網路連接\n• 稍後再試\n• 或試試其他功能"
        
        # 參數錯誤
        elif "parameter" in error_lower or "argument" in error_lower or "invalid" in error_lower:
            # 提供範例
            examples = {
                "weather_query": "範例：「台北天氣」、「東京天氣如何」",
                "news_query": "範例：「最新新聞」、「科技新聞」",
                "exchange_query": "範例：「美元台幣匯率」",
                "healthkit_query": "範例：「我的心率」、「今天步數」"
            }
            example = examples.get(tool_name, "請參考功能列表中的範例")
            
            return f"📝 參數格式問題\n\n你的請求「{original_message}」可能缺少一些必要資訊。\n\n{example}\n\n需要幫助？輸入「/功能」查看完整說明"
        
        # 一般錯誤
        else:
            return f"❌ 執行失敗\n\n{tool_name} 執行時遇到問題：{error}\n\n建議：\n• 稍後再試\n• 或試試其他功能\n• 需要幫助？輸入「/功能」"

    def _should_reformat(self, tool_name: str, content: str) -> bool:
        """
        決定是否需要 AI 二次格式化（改為對話式回覆）
        
        策略：
        1. 工具卡片相關工具 → 總是需要 AI 格式化（生成對話式回覆）
        2. 內容過於結構化（超過20行） → 需要格式化
        3. 包含原始數據結構 → 需要格式化
        4. 特定工具總是格式化 → 需要格式化
        5. 默認：相信工具自己的格式化
        """
        # 策略1: 有工具卡片的工具，總是需要 AI 格式化為對話式回覆
        # 因為簡短的結構化文字不適合語音播報和聊天顯示
        always_format_for_conversation = ['exchange_query', 'weather_query', 'healthkit_query', 'news_query']
        if tool_name in always_format_for_conversation:
            logger.debug(f"工具 {tool_name} 需要 AI 格式化為對話式回覆")
            return True
        
        # 策略2: 內容過於結構化
        if content.count('\n') > 20:
            logger.debug(f"內容超過20行，啟用格式化")
            return True
        
        # 策略3: 包含原始數據結構（但排除已格式化的簡短內容）
        # 檢查是否為 JSON dump（前 100 字符內有大括號和引號）
        has_json_structure = '{' in content[:100] and '"' in content[:100]
        # 檢查是否為代碼塊
        has_code_block = '```' in content
        
        # 如果內容很短(<200字符)且看起來像 JSON，很可能是格式化失敗
        if has_json_structure and len(content) < 200:
            logger.warning(f"檢測到短 JSON 結構，可能需要格式化")
            return True
        
        if has_code_block:
            logger.debug(f"包含代碼塊，啟用格式化")
            return True
        
        # 策略4: 特定工具總是需要格式化（可配置）
        always_format = ['raw_query', 'debug_tool', 'system_info']
        if tool_name in always_format:
            logger.debug(f"工具 {tool_name} 需要格式化")
            return True
        
        # 默認：相信工具自己的格式化
        return False

    async def _format_tool_response(self, tool_name: str, content: str,
                                  original_message: str) -> str:
        """使用 AI 將工具回應格式化為自然對話"""
        try:
            system_prompt = (
                "你是一個友善、健談的AI助手。\n"
                "用戶剛剛問了一個問題，我已經用工具查詢到資料了。\n"
                "請用自然、口語化的方式回答用戶，就像朋友聊天一樣。\n\n"
                "要求：\n"
                "1. 使用口語化、親切的語氣（可以用「喔」「呢」「哦」等語氣詞）\n"
                "2. 不要列表式的羅列數據，而是用對話方式描述\n"
                "3. 突出最重要的資訊（2-3句話）\n"
                "4. 適當使用 emoji 增加親和力\n"
                "5. 如果數據很多，只說重點\n"
                "6. 保持簡短（50字以內最好）\n\n"
                "範例：\n"
                "❌ 不好：「當前溫度23.88°C，體感溫度24.02°C，天氣狀況多雲...」\n"
                "✅ 良好：「台北現在23度左右，有點多雲呢！體感還蠻舒服的～」\n\n"
                "記住：你是在聊天，不是在報告數據！"
            )

            user_prompt = (
                f"用戶問：「{original_message}」\n\n"
                f"我用 {tool_name} 查到的資料：\n{content}\n\n"
                f"請用自然對話的方式回答用戶（簡短、親切、口語化）："
            )

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

            # 格式化回應使用 low reasoning（不需深度推理）
            optimal_effort = get_optimal_reasoning_effort("format_response")

            response = await ai_service.generate_response_for_user(
                messages=messages,
                user_id="format_response",
                model="gpt-5-nano",
                chat_id=None,
                reasoning_effort=optimal_effort
            )

            return response

        except Exception as e:
            logger.error(f"格式化回應失敗: {e}")
            return content

    async def continue_pending(self, user_id: Optional[str], message: str,
                             chat_id: Optional[str] = None) -> Optional[str]:
        """處理多輪對話補槽 (保持與舊介面相同)"""
        # 目前簡化實作，未來可擴展
        return None

    def get_feature_list(self) -> str:
        """獲取功能列表 (基於工具metadata動態分類)"""
        logger.info("獲取功能列表")

        if not self.mcp_server.tools:
            return "目前沒有可用的功能。"

        result = "📋 系統功能列表\n\n"

        # 動態分類工具
        categories = {}
        usage_tips = []

        for tool_name, tool in self.mcp_server.tools.items():
            # 從工具metadata獲取分類信息
            metadata = tool.metadata or {}
            category = metadata.get('category', '其他')
            tags = metadata.get('tags', [])
            tips = metadata.get('usage_tips', [])

            # 初始化分類
            if category not in categories:
                categories[category] = []

            # 添加工具描述
            categories[category].append(f"• {tool.description}")

            # 收集使用提示
            usage_tips.extend(tips)

        # 輸出分類結果
        for category, tools in categories.items():
            if tools:
                result += f"◆ {category}\n"
                result += "\n".join(tools) + "\n\n"

        # 使用提示
        if usage_tips:
            result += "💡 使用提示\n"
            for tip in usage_tips:
                result += f"• {tip}\n"

        return result

    async def process_response(self, response: str, original_message: str) -> str:
        """處理 AI 回應，檢測是否需要自動修正 (保持與舊介面相同)"""
        # 保持與舊 FeatureRouter 相同的邏輯
        return response

    async def _preheat_cache(self):
        """
        快取預熱（2025 最佳實踐）

        啟動時預先載入熱門查詢的意圖檢測結果，減少冷啟動延遲
        預期提升首次查詢命中率 40-60%
        """
        logger.info("🔥 開始快取預熱...")

        # 定義熱門查詢（根據使用統計調整）
        hot_queries = [
            "台北天氣",
            "天氣如何",
            "美元匯率",
            "今日新聞",
            "科技新聞",
            "我的心率",
            "今天步數",
        ]

        preheated_count = 0
        for query in hot_queries:
            try:
                # 預先執行意圖檢測，寫入快取
                await self.detect_intent(query)
                preheated_count += 1
                logger.debug(f"✓ 預熱快取: '{query}'")
            except Exception as e:
                logger.warning(f"⚠️ 預熱快取失敗 '{query}': {e}")

        logger.info(f"🔥 快取預熱完成，成功預載 {preheated_count}/{len(hot_queries)} 條熱門查詢")
        logger.info(f"💾 當前快取大小: {len(self._intent_cache)} 條")
