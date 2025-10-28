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

                    # 解析 tool_name:params 格式
                    if ":" in tool_name_with_params:
                        tool_name, params_str = tool_name_with_params.split(":", 1)
                        # 解析參數
                        arguments = {}
                        if params_str.strip():
                            for param_pair in params_str.split(","):
                                if "=" in param_pair:
                                    key, value = param_pair.split("=", 1)
                                    key = key.strip()
                                    value = value.strip()

                                    # 跳過空值（避免傳入空字串導致驗證失敗）
                                    if not value:
                                        continue

                                    # 嘗試類型轉換
                                    if value.isdigit():
                                        arguments[key] = int(value)
                                    elif value.lower() in ('true', 'false'):
                                        arguments[key] = value.lower() == 'true'
                                    elif value.replace('.', '', 1).isdigit():
                                        arguments[key] = float(value)
                                    else:
                                        arguments[key] = value
                    else:
                        tool_name = tool_name_with_params
                        arguments = {}

                    logger.info(f"✅ GPT 檢測到工具調用: {tool_name}")
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
        調用 MCP 工具（帶智慧重試機制 + 統一格式化）
        2025年最佳實踐：指數退避重試 + 錯誤分類 + AI 格式化
        """
        if tool_name not in self.mcp_server.tools:
            return self._generate_tool_not_found_error(tool_name)

        tool = self.mcp_server.tools[tool_name]
        if not tool.handler:
            return f"⚠️ 工具 {tool_name} 尚未實作，請稍後再試"

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