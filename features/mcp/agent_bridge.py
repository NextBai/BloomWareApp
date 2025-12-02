"""
MCP + Agent 橋接層
整合 MCP Tools 與 Agent 邏輯，保持與舊 FeatureRouter 相同的介面
"""

import json
import logging
import asyncio
from typing import Dict, Any, Optional, List, Tuple, Callable, Awaitable
from datetime import datetime
from .server import FeaturesMCPServer
import services.ai_service as ai_service
from services.ai_service import StrictResponseError
from core.reasoning_strategy import get_optimal_reasoning_effort
from core.database import get_user_env_current
from .coordinator import ToolCoordinator
from .tool_models import ToolMetadata, ToolResult

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


EnvProvider = Callable[[Optional[str]], Awaitable[Dict[str, Any]]]


class MCPAgentBridge:
    """MCP + Agent 橋接器，提供與舊 FeatureRouter 相同的介面"""

    def __init__(self, env_provider: Optional[EnvProvider] = None):
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

        self._env_provider: EnvProvider = env_provider or self._default_env_provider
        self._tool_coordinator = ToolCoordinator(
            env_provider=self._delegated_env_provider,
            tool_lookup=self._lookup_tool_handler,
            formatter=self._format_with_ai,
            failure_handlers={
                'directions': self._directions_failure_fallback,
            },
        )
        self._register_tool_metadata()

        logger.info("MCP Agent 橋接層初始化完成")
        logger.info(f"初始可用 MCP 工具數量: {len(self.mcp_server.tools)} (將在異步發現後更新)")

    async def _default_env_provider(self, user_id: Optional[str]) -> Dict[str, Any]:
        if not user_id:
            return {}
        try:
            env_res = await get_user_env_current(user_id)
            if env_res.get("success"):
                return env_res.get("context") or {}
        except Exception as exc:  # noqa: BLE001
            logger.debug("讀取使用者 %s 環境資訊失敗: %s", user_id, exc)
        return {}

    async def _delegated_env_provider(self, user_id: Optional[str]) -> Dict[str, Any]:
        provider = self._env_provider or self._default_env_provider
        return await provider(user_id)

    def bind_env_provider(self, provider: EnvProvider) -> None:
        self._env_provider = provider

    def _lookup_tool_handler(self, tool_name: str):
        tool = self.mcp_server.tools.get(tool_name)
        return getattr(tool, "handler", None) if tool else None

    async def _format_with_ai(
        self,
        tool_name: str,
        message: str,
        payload: Dict[str, Any],
        original_message: str,
    ) -> str:
        return await self._format_tool_response(tool_name, message, original_message)

    def _register_tool_metadata(self) -> None:
        register = self._tool_coordinator.register
        register(
            ToolMetadata(
                name="weather_query",
                requires_env={"lat", "lon", "city"},
                enable_reformat=True,
            )
        )
        register(
            ToolMetadata(
                name="reverse_geocode",
                requires_env={"lat", "lon"},
                enable_reformat=True,
            )
        )
        register(
            ToolMetadata(
                name="exchange_query",
                enable_reformat=True,
            )
        )
        register(
            ToolMetadata(
                name="news_query",
                enable_reformat=True,
            )
        )
        register(
            ToolMetadata(
                name="healthkit_query",
                enable_reformat=True,
            )
        )
        register(
            ToolMetadata(
                name="directions",
                enable_reformat=True,
            )
        )
        register(
            ToolMetadata(
                name="forward_geocode",
                flow="navigation",
            )
        )
        # TDX 公車到站查詢（需要位置資訊）
        register(
            ToolMetadata(
                name="tdx_bus_arrival",
                requires_env={"lat", "lon", "city"},
                enable_reformat=True,
            )
        )
        # TDX YouBike 查詢（需要位置資訊）
        register(
            ToolMetadata(
                name="tdx_youbike",
                requires_env={"lat", "lon", "city"},
                enable_reformat=True,
            )
        )
        # TDX 捷運查詢（需要位置資訊）
        register(
            ToolMetadata(
                name="tdx_metro",
                requires_env={"lat", "lon", "city"},
                enable_reformat=True,
            )
        )
        # TDX 停車場查詢（需要位置資訊）
        register(
            ToolMetadata(
                name="tdx_parking",
                requires_env={"lat", "lon", "city"},
                enable_reformat=True,
            )
        )
        # TDX 台鐵查詢（需要位置資訊）
        register(
            ToolMetadata(
                name="tdx_train",
                requires_env={"lat", "lon", "city"},
                enable_reformat=True,
            )
        )
        # TDX 高鐵查詢（需要位置資訊）
        register(
            ToolMetadata(
                name="tdx_thsr",
                requires_env={"lat", "lon", "city"},
                enable_reformat=True,
            )
        )

    def _directions_failure_fallback(self, arguments: Dict[str, Any], exc: Exception) -> ToolResult:
        labels = {
            "origin_label": arguments.get("origin_label") or "起點",
            "dest_label": arguments.get("dest_label") or "目的地",
        }
        fallback = self._build_directions_failure_response(
            arguments,
            labels,
            str(exc),
        )
        return ToolResult(
            name="directions",
            message=fallback["message"],
            data=fallback.get("tool_data"),
        )

    async def async_initialize(self):
        """異步初始化，發現所有工具 + 快取預熱"""
        if hasattr(self.mcp_server, 'start_external_servers'):
            await self.mcp_server.start_external_servers()
            logger.info(f"異步初始化完成，完整可用 MCP 工具數量: {len(self.mcp_server.tools)}")

        # 將 MCP Server 的工具註冊到 tool_registry
        self._sync_tools_to_registry()

        # 2025 最佳實踐：啟動時預熱熱門查詢快取
        await self._preheat_cache()

    def _sync_tools_to_registry(self) -> int:
        """
        將 MCP Server 的工具同步到 tool_registry
        
        Returns:
            註冊的工具數量
        """
        from core.tool_registry import tool_registry
        
        count = 0
        for tool_name, tool in self.mcp_server.tools.items():
            # 取得工具描述
            description = getattr(tool, 'description', f'{tool_name} 工具')
            
            # 取得參數 Schema
            parameters = {"type": "object", "properties": {}, "required": []}
            keywords = []
            examples = []
            negative_examples = []
            category = "general"
            priority = 100
            
            if hasattr(tool, 'handler') and hasattr(tool.handler, '__self__'):
                tool_class = tool.handler.__self__
                
                # 嘗試從 MCPTool 類別提取完整資訊
                if hasattr(tool_class, 'get_input_schema'):
                    try:
                        parameters = tool_class.get_input_schema()
                    except Exception as e:
                        logger.warning(f"取得 {tool_name} schema 失敗: {e}")
                
                # 提取增強元資料
                keywords = getattr(tool_class, 'KEYWORDS', [])
                examples = getattr(tool_class, 'USAGE_TIPS', [])
                negative_examples = getattr(tool_class, 'NEGATIVE_EXAMPLES', [])
                category = getattr(tool_class, 'CATEGORY', 'general')
                priority = getattr(tool_class, 'PRIORITY', 100)
            
            # 判斷是否需要位置
            props = parameters.get("properties", {})
            requires_location = "lat" in props or "lon" in props
            
            tool_registry.register(
                name=tool_name,
                description=description,
                parameters=parameters,
                handler=getattr(tool, 'handler', None),
                category=category,
                requires_location=requires_location,
                keywords=keywords,
                examples=examples,
            )
            count += 1
        
        logger.info(f"🔧 同步 {count} 個工具到 tool_registry")
        return count

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
        
        2025 重構版：使用 OpenAI 原生 Function Calling
        - 不再使用巨大的 system_prompt 描述每個工具
        - 工具定義由 tools 參數傳遞，GPT 原生選擇
        - 新增工具只需註冊到 Registry，不需更新任何 prompt

        參數:
        message (str): 用戶消息

        返回:
        tuple: (是否檢測到意圖, 意圖數據)
        """
        # 使用新的 IntentDetector（基於 OpenAI Function Calling）
        return await self._detect_intent_with_function_calling(message)

    async def _detect_intent_with_function_calling(self, message: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        使用 OpenAI 原生 Function Calling 進行意圖檢測
        
        核心改進：
        1. 工具定義自動從 Registry 生成
        2. GPT 原生選擇工具並生成結構化參數
        3. 不需要自定義 prompt 描述每個工具
        """
        import hashlib
        import time as time_module
        
        # 生成快取鍵
        cache_key = hashlib.md5(message.encode()).hexdigest()

        # 檢查快取
        if cache_key in self._intent_cache:
            has_feature, intent_data, cached_time = self._intent_cache[cache_key]
            if time_module.time() - cached_time < self._intent_cache_ttl:
                logger.debug(f"💾 意圖快取命中: {message[:50]}...")
                return has_feature, intent_data
            else:
                del self._intent_cache[cache_key]

        logger.info(f"🔍 檢測意圖（Function Calling）: \"{message[:100]}...\"")

        # 檢查特殊命令
        for command in ["功能列表", "有什麼功能", "能做什麼"]:
            if command in message:
                logger.info(f"檢測到特殊命令: {command}")
                return True, {"type": "special_command", "command": "feature_list"}

        try:
            # 從 tool_registry 取得 OpenAI tools 格式
            from core.tool_registry import tool_registry
            from core.tool_router import tool_router
            
            all_tools = tool_registry.get_openai_tools(strict=False)
            
            if not all_tools:
                logger.warning("⚠️ 沒有可用的工具，降級為聊天")
                return False, {"emotion": "neutral"}
            
            # 使用 ToolRouter 動態過濾和排序工具
            context = {"hour": datetime.now().hour}
            tools = tool_router.filter_tools(all_tools, message, context)
            
            logger.info(f"🔧 載入 {len(all_tools)} 個工具，過濾後 {len(tools)} 個")
            
            # 建構精簡的 system prompt（只處理特殊規則）
            system_prompt = self._build_function_calling_prompt()
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ]
            
            # 使用 OpenAI Function Calling
            from core.reasoning_strategy import get_optimal_reasoning_effort
            optimal_effort = get_optimal_reasoning_effort("intent_detection")
            logger.info(f"🧠 意圖檢測推理強度: {optimal_effort}")
            
            response = await ai_service.generate_response_with_tools(
                messages=messages,
                tools=tools,
                user_id="intent_detection",
                model="gpt-4o-mini",  # 使用更強的模型以提升參數提取準確度
                reasoning_effort=None,  # gpt-4o-mini 不支援 reasoning_effort
                tool_choice="auto",
            )
            
            # 解析回應
            tool_calls = response.get("tool_calls", [])
            
            if tool_calls:
                # GPT 選擇了工具
                tool_call = tool_calls[0]
                function = tool_call.get("function", {})
                tool_name = function.get("name", "")
                arguments_str = function.get("arguments", "{}")
                
                try:
                    arguments = json.loads(arguments_str)
                except json.JSONDecodeError:
                    arguments = {}
                
                # 正規化工具名稱
                normalized_name = self._normalize_tool_name(tool_name)
                if not normalized_name:
                    logger.warning(f"⚠️ 工具 {tool_name} 無法對應到註冊名稱，降級為聊天")
                    return False, {"emotion": "neutral"}
                
                logger.info(f"✅ GPT 選擇工具: {normalized_name}")
                logger.debug(f"工具參數: {_safe_json(arguments)}")
                
                # 提取情緒（從 content 或預設）
                emotion = self._extract_emotion_from_content(response.get("content", ""))
                
                intent_result = (True, {
                    "type": "mcp_tool",
                    "tool_name": normalized_name,
                    "arguments": arguments,
                    "emotion": emotion,
                })
                
                # 寫入快取
                self._intent_cache[cache_key] = (*intent_result, time_module.time())
                return intent_result
            
            else:
                # GPT 未選擇工具，視為一般聊天
                logger.info("💬 GPT 判斷為一般聊天")
                emotion = self._extract_emotion_from_content(response.get("content", ""))
                
                intent_result = (False, {"emotion": emotion})
                self._intent_cache[cache_key] = (*intent_result, time_module.time())
                return intent_result
                
        except Exception as e:
            logger.error(f"❌ Function Calling 意圖檢測失敗: {e}")
            # 降級：使用關鍵詞匹配
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
        return False, {"emotion": "neutral"}

    def _build_function_calling_prompt(self) -> str:
        """
        建構精簡的 Function Calling system prompt
        
        注意：不再描述每個工具，工具定義由 tools 參數傳遞
        只處理特殊規則和情緒判斷
        """
        return """你是一個智能助手，根據用戶需求選擇合適的工具。

規則：
1. 如果用戶需求可以用工具解決，選擇最適合的工具
2. 如果是一般聊天或問候，不要選擇任何工具
3. 工具參數盡量從用戶消息中提取，無法確定的使用合理預設值

【重要】語言使用規範：
- 調用工具時：所有參數必須使用英文（城市名、國家名、貨幣代碼等）
- 回覆用戶時：必須使用繁體中文
- 範例：用戶說「台北天氣」→ 參數 {"city": "Taipei"}，回覆「台北目前...」

參數語言轉換規則：
- 城市名稱：台北→Taipei, 新北→NewTaipei, 桃園→Taoyuan, 台中→Taichung, 台南→Tainan, 高雄→Kaohsiung, 新竹→Hsinchu
- 國家名稱：台灣→Taiwan, 美國→USA, 日本→Japan, 英國→UK
- 貨幣代碼：美元→USD, 台幣→TWD, 日圓→JPY, 歐元→EUR, 英鎊→GBP

【重要】城市參數提取原則：
- 只有在用戶明確提到城市名稱時才填 city 參數
- 「附近」「這裡」「我這邊」等詞 → 不填 city 參數，系統會自動從 GPS 判斷
- 「台北的XX」「桃園XX」→ 填對應的英文城市名
- 範例：「附近的 YouBike」→ {}，「桃園的 YouBike」→ {"city": "Taoyuan"}

匯率查詢（重要！參數提取規則）：
當用戶詢問匯率資訊時，你必須從消息中提取貨幣代碼並填入參數。

參數提取規則：
1. 句型「[貨幣A]轉[貨幣B]」「[貨幣A]換[貨幣B]」「[貨幣A]兌[貨幣B]」→ {"from_currency": "代碼A", "to_currency": "代碼B"}
2. 句型「[數字][貨幣A]是多少[貨幣B]」→ {"from_currency": "代碼A", "to_currency": "代碼B", "amount": 數字}
3. 句型「匯率」「美金」「日幣」→ 提取提到的貨幣
4. 貨幣代碼必須用 ISO 4217 標準（3個大寫字母）

常見貨幣代碼對照：
- 美元/美金 → USD
- 台幣/新台幣 → TWD
- 日圓/日幣 → JPY
- 歐元 → EUR
- 英鎊 → GBP
- 人民幣 → CNY
- 港幣 → HKD
- 韓元 → KRW

實際範例：
- 「美元轉日幣的匯率」→ {"from_currency": "USD", "to_currency": "JPY"}
- 「台幣換美金」→ {"from_currency": "TWD", "to_currency": "USD"}
- 「100美元是多少台幣」→ {"from_currency": "USD", "to_currency": "TWD", "amount": 100}
- 「歐元兌日圓」→ {"from_currency": "EUR", "to_currency": "JPY"}
- 「匯率」→ {"from_currency": "USD", "to_currency": "TWD"}（預設）

重要：必須提取貨幣代碼！不要返回空參數！

公車查詢（重要！參數提取規則）：
當用戶詢問公車資訊時，你必須從消息中提取路線號碼並填入參數。

tdx_bus_arrival 適用場景：
- 查詢「已知路線號碼」的到站時間
- 查詢附近公車站點（不需 route_name）

參數提取規則：
1. 句型「[數字]公車」「[數字]號公車」→ {"route_name": "數字"}
2. 句型「[顏色][數字]」（如「紅30」）→ {"route_name": "顏色數字"}
3. 句型「[數字]還要多久」「[數字]什麼時候到」→ {"route_name": "數字"}
4. 句型「[路線名]公車到站」→ {"route_name": "路線名"}
5. 「附近公車」「公車站」「有什麼公車」→ {}（系統自動從 GPS 判斷城市）
6. 城市參數：只在用戶明確提到城市時才填，否則留空讓系統自動判斷

實際範例：
- 「261公車什麼時候到」→ {"route_name": "261"}（不填 city）
- 「307還要多久」→ {"route_name": "307"}（不填 city）
- 「台北261公車」→ {"route_name": "261", "city": "Taipei"}（明確提到台北）
- 「桃園紅30公車」→ {"route_name": "紅30", "city": "Taoyuan"}（明確提到桃園）
- 「附近有什麼公車」→ {}（完全空參數，系統自動判斷）

不適用場景（應使用 directions）：
- 「從A到B的公車」「往XX的公車」→ 這是路線規劃，不是查詢特定路線
- 「去台北的公車」→ 台北是目的地，不是路線號碼

重要：如果提到路線號碼，必須提取！城市參數必須用英文！

火車查詢（重要！參數提取規則）：
當用戶詢問火車資訊時，你必須從消息中提取站名並填入參數。

參數提取規則（適用於任何地名）：
1. 句型「從 [地名A] 往/到 [地名B]」→ {"origin_station": "地名A", "destination_station": "地名B"}
2. 句型「[地名A] 到/往 [地名B]」→ {"origin_station": "地名A", "destination_station": "地名B"}
3. 句型「往/去 [地名]」→ {"destination_station": "地名"}
4. 句型「[車種][數字]次」→ {"train_no": "數字"}
5. 包含時間 → 提取為 departure_time（HH:MM 格式）

實際範例：
- 「從彰化往台北的火車」→ {"origin_station": "彰化", "destination_station": "台北"}
- 「台中到高雄」→ {"origin_station": "台中", "destination_station": "高雄"}
- 「往新竹的火車」→ {"destination_station": "新竹"}
- 「自強號123次」→ {"train_no": "123"}
- 「早上8點台南到台北」→ {"origin_station": "台南", "destination_station": "台北", "departure_time": "08:00"}

重要：絕對不要返回空的 {} 參數！必須從用戶消息中提取站名！

位置查詢：
- 「我在哪」使用 reverse_geocode，不需要參數
- 「怎麼去XX」使用 forward_geocode 或 directions

YouBike 查詢（重要！參數提取規則）：
當用戶詢問 YouBike/Ubike/微笑單車時，你必須調用 tdx_youbike 工具。

參數提取規則：
1. 「附近的 YouBike」「Ubike 在哪」→ {}（不填 city，系統自動從 GPS 判斷）
2. 「市政府 YouBike」「台北車站 Ubike」→ {"station_name": "市政府"}（不填 city）
3. 「XX站還有車嗎」→ {"station_name": "XX站"}（不填 city）
4. 「台北的 YouBike」「桃園 YouBike」→ 填對應英文城市名
5. 站名可用中文，城市必須用英文

實際範例：
- 「附近的 YouBike」→ {}（完全空參數，系統自動判斷城市）
- 「市政府 YouBike 還有車嗎」→ {"station_name": "市政府"}（不填 city）
- 「台北車站 Ubike」→ {"station_name": "台北車站"}（不填 city）
- 「台北的 YouBike」→ {"city": "Taipei"}（明確提到台北）
- 「桃園 YouBike」→ {"city": "Taoyuan"}（明確提到桃園）

重要：只在用戶明確提到城市時才填 city 參數！站名可保持中文！

【情緒偵測】（重要！）：
- 分析用戶的情緒狀態（根據用詞、語氣、標點符號、表情符號）
- 在回應的最後一行加上情緒標籤：[EMOTION:情緒]
- 情緒類型：neutral（平靜）、happy（開心）、sad（難過）、angry（生氣）、fear（害怕）、surprise（驚訝）
- 範例：
  * 用戶說「我現在覺得很生氣」→ 回應最後加上 [EMOTION:angry]
  * 用戶說「好開心啊！」→ 回應最後加上 [EMOTION:happy]
  * 用戶說「我好難過...」→ 回應最後加上 [EMOTION:sad]
  * 用戶說「好可怕」→ 回應最後加上 [EMOTION:fear]
  * 用戶說「哇！」→ 回應最後加上 [EMOTION:surprise]
  * 一般對話 → 回應最後加上 [EMOTION:neutral]
"""

    def _extract_emotion_from_content(self, content: str) -> str:
        """從回應內容中提取情緒標籤 [EMOTION:xxx]"""
        if not content:
            return "neutral"
        
        # 優先從標籤提取
        import re
        emotion_match = re.search(r'\[EMOTION:(neutral|happy|sad|angry|fear|surprise)\]', content, re.IGNORECASE)
        if emotion_match:
            emotion = emotion_match.group(1).lower()
            logger.info(f"😊 從標籤提取情緒: {emotion}")
            return emotion
        
        # 降級：從內容搜尋英文關鍵字
        content_lower = content.lower()
        emotions = ["happy", "sad", "angry", "fear", "surprise"]
        
        for emotion in emotions:
            if emotion in content_lower:
                logger.debug(f"從內容搜尋到情緒關鍵字: {emotion}")
                return emotion
        
        return "neutral"

    # 舊版 _detect_intent_legacy 已移除，改用 _detect_intent_with_function_calling

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
        """獲取分類整理的工具摘要（使用輕量級摘要，減少 token 消耗 60-70%）"""
        # 使用 MCPServer 的 get_tools_summary() 獲取輕量級摘要
        try:
            tools_summary = self.mcp_server.get_tools_summary()
        except Exception as e:
            logger.error(f"獲取工具摘要失敗: {e}")
            # 降級：使用舊邏輯
            tools_summary = []
            for tool_name, tool in self.mcp_server.tools.items():
                tools_summary.append({
                    "name": tool_name,
                    "description": tool.description if hasattr(tool, 'description') else "",
                    "category": "其他",
                    "keywords": [],
                    "is_complex": False
                })
        
        # 按類別組織工具
        categorized_tools = {
            "地理定位": [],
            "軌道運輸": [],
            "道路運輸": [],
            "微型運具": [],
            "停車與充電": [],
            "生活資訊": [],
            "健康數據": [],
            "其他": []
        }
        
        for summary in tools_summary:
            category = summary.get("category", "其他")
            name = summary.get("name", "unknown")
            desc = summary.get("description", "")
            keywords = summary.get("keywords", [])
            is_complex = summary.get("is_complex", False)
            
            # 格式化：工具名 - 描述 | 關鍵字
            keywords_str = ", ".join(keywords[:5]) if keywords else ""  # 最多顯示 5 個關鍵字
            if keywords_str:
                line = f"- {name}: {desc} | 關鍵字: {keywords_str}"
            else:
                line = f"- {name}: {desc}"
            
            # 標記複雜工具
            if is_complex:
                line += " [複雜]"
            
            # 將工具加入對應類別
            if category in categorized_tools:
                categorized_tools[category].append(line)
            else:
                categorized_tools["其他"].append(line)
        
        # 構建分類描述
        result = []
        
        # 定義類別順序和說明
        category_order = [
            ("地理定位", "【地理定位與導航】地點查詢、路線規劃"),
            ("軌道運輸", "【軌道運輸】捷運、台鐵、高鐵"),
            ("道路運輸", "【道路運輸】公車、客運"),
            ("微型運具", "【微型運具】YouBike 共享單車"),
            ("停車與充電", "【停車與充電】停車場、充電站"),
            ("生活資訊", "【生活資訊】天氣、新聞、匯率"),
            ("健康數據", "【健康數據】心率、步數、血氧、睡眠"),
            ("其他", "【其他功能】")
        ]
        
        for category, header in category_order:
            tools = categorized_tools.get(category, [])
            if tools:
                result.append(f"\n{header}")
                result.extend(tools)
        
        # 添加工具選擇指引
        result.append("\n【工具選擇指引】")
        result.append("1. 導航問題（「怎麼去」「路線」「導航」） → directions")
        result.append("2. 地點查詢（「XXX在哪」「地址」） → forward_geocode")
        result.append("3. 公共運輸查詢 → TDX 相關工具暫時停用（待取得替代 API）")
        result.append("4. 健康數據查詢 → healthkit_query（心率、步數、血氧等）")
        result.append("5. 生活資訊 → weather_query（天氣）、news_query（新聞）、exchange_query（匯率）")
        result.append("6. 標記 [複雜] 的工具只需返回工具名稱，參數稍後填充")
        
        logger.debug(f"工具描述已生成，總長度: {len(''.join(result))} 字元")
        return "\n".join(result)

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

            try:
                result = await self._tool_coordinator.invoke(
                    tool_name,
                    arguments or {},
                    user_id=user_id,
                    original_message=original_message,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("工具 %s 執行失敗: %s", tool_name, exc)
                return self._generate_tool_error_message(tool_name, exc, original_message)

            if isinstance(result, ToolResult):
                if result.name == 'directions' and isinstance(result.data, dict):
                    message, sanitized = self._build_directions_message(result.data, {})
                    result.message = message
                    result.data = sanitized
                return result.to_dict()
            return result

        else:
            logger.warning(f"未知意圖類型: {intent_type}")
            return f"抱歉，無法理解您的請求。"

    async def _call_mcp_tool(self, tool_name: str, arguments: Dict[str, Any],
                           user_id: str = None, original_message: str = '') -> str:
        raise RuntimeError('legacy tool invocation path已移除，請改用 ToolCoordinator.invoke')

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

    def _generate_tool_error_message(self, tool_name: str, error: Exception, original_message: str) -> str:
        try:
            return self._generate_helpful_error(tool_name, str(error), original_message)
        except Exception as fallback_err:
            logger.error('生成工具錯誤訊息失敗: %s', fallback_err)
            return f'抱歉，{tool_name} 執行失敗：{error}'

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
        # 包含 TDX 交通工具，確保返回對話式回覆而非 JSON
        always_format_for_conversation = [
            'exchange_query', 'weather_query', 'healthkit_query', 'news_query',
            'tdx_youbike', 'tdx_train', 'tdx_thsr', 'tdx_bus_arrival', 'tdx_metro', 'tdx_parking'
        ]
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
                "【核心原則】\n"
                "⭐ 只回答使用者問的問題，不要把所有數據都說出來\n"
                "⭐ 分析使用者的核心意圖（問溫度？天氣？時間？地點？數量？）\n"
                "⭐ 從工具數據中只提取相關資訊，無關資訊一律省略\n\n"
                "【回應要求】\n"
                "1. 使用口語化、親切的語氣（可以用「喔」「呢」「哦」等語氣詞）\n"
                "2. 不要列表式的羅列數據，而是用對話方式描述\n"
                "3. 只說使用者問的內容（2-3句話）\n"
                "4. 適當使用 emoji 增加親和力\n"
                "5. 如有額外有用資訊，可簡短補充（不超過一句話）\n"
                "6. 保持簡短（50字以內最好）\n\n"
                "【範例】\n"
                "用戶問：「台北現在幾度？」\n"
                "工具返回：溫度23.88°C、濕度65%、風速3m/s、氣壓1013hPa...\n"
                "❌ 錯誤：「台北現在23度，濕度65%，風速3m/s...」（說太多）\n"
                "✅ 正確：「台北現在23度左右喔！」（只回答溫度）\n"
                "✅ 可接受：「台北現在23度，體感蠻舒服的～」（簡短補充）\n\n"
                "記住：精準回答使用者的問題，不要喧賓奪主！"
            )

            user_prompt = (
                f"【使用者的核心問題】\n"
                f"「{original_message}」\n\n"
                f"【工具 {tool_name} 返回的數據】\n"
                f"{content}\n\n"
                f"【任務】\n"
                f"請只回答使用者問的問題（簡短、親切、口語化）："
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
