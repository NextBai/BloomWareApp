"""
意圖檢測器
2025 最佳實踐：使用 OpenAI 原生 Function Calling 進行意圖檢測

核心改進：
1. 不再使用巨大的 system_prompt 描述每個工具
2. 直接使用 OpenAI tools 參數傳遞工具定義
3. GPT 原生選擇工具並生成結構化參數
4. 新增工具只需註冊到 Registry，不需更新任何 prompt
"""

import json
import hashlib
import time
import logging
from typing import Dict, Any, Optional, Tuple, List

from core.tool_registry import tool_registry
from core.logging import get_logger
from core.config import settings
from core.prompts.tool_calling_policy import get_tool_calling_policy

logger = get_logger("core.intent_detector")

MIN_TOOL_CONFIDENCE = 0.90


class IntentDetector:
    """
    意圖檢測器
    
    使用 OpenAI 原生 Function Calling 進行意圖檢測，
    不需要自定義 prompt 描述每個工具。
    """
    
    # 情緒列表
    EMOTIONS = ["neutral", "happy", "sad", "angry", "fear", "surprise"]
    
    # 快取 TTL（秒）
    CACHE_TTL = 300.0
    
    def __init__(self):
        self._cache: Dict[str, Tuple[bool, Optional[Dict[str, Any]], float]] = {}

    @staticmethod
    def _estimate_tool_confidence(tool_name: str, arguments: Dict[str, Any]) -> float:
        if not tool_name:
            return 0.0
        if not isinstance(arguments, dict):
            return 0.0
        return 0.95 if arguments else 0.92
    
    async def detect(
        self,
        message: str,
        user_id: Optional[str] = None,
        include_location_tools: bool = True,
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        檢測用戶消息中的意圖
        
        Args:
            message: 用戶消息
            user_id: 用戶 ID（用於日誌）
            include_location_tools: 是否包含需要位置的工具
        
        Returns:
            (是否檢測到工具調用, 意圖數據)
        """
        # 檢查快取
        cache_key = hashlib.md5(message.encode()).hexdigest()
        if cache_key in self._cache:
            has_intent, intent_data, cached_time = self._cache[cache_key]
            if time.time() - cached_time < self.CACHE_TTL:
                logger.debug(f"💾 意圖快取命中: {message[:50]}...")
                return has_intent, intent_data
            else:
                del self._cache[cache_key]
        
        logger.info(f"🔍 檢測意圖: \"{message[:100]}...\"")
        
        # 檢查特殊命令
        special_result = self._check_special_commands(message)
        if special_result:
            return special_result
        
        # 使用 OpenAI Function Calling 進行意圖檢測
        try:
            result = await self._detect_with_function_calling(
                message,
                include_location_tools=include_location_tools,
            )
            
            # 寫入快取
            self._cache[cache_key] = (*result, time.time())
            
            return result
            
        except Exception as e:
            logger.error(f"❌ 意圖檢測失敗: {e}")
            # 降級：使用關鍵字匹配
            return self._keyword_fallback(message)
    
    def _check_special_commands(self, message: str) -> Optional[Tuple[bool, Dict[str, Any]]]:
        """檢查特殊命令"""
        for command in ["功能列表", "有什麼功能", "能做什麼"]:
            if command in message:
                logger.info(f"檢測到特殊命令: {command}")
                return True, {
                    "type": "special_command",
                    "command": "feature_list"
                }
        return None
    
    async def _detect_with_function_calling(
        self,
        message: str,
        include_location_tools: bool = True,
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        使用 OpenAI Function Calling 進行意圖檢測
        
        核心邏輯：
        1. 將所有工具以 OpenAI tools 格式傳遞
        2. GPT 自動選擇最適合的工具
        3. 如果 GPT 不選擇任何工具，視為一般聊天
        """
        import services.ai_service as ai_service
        from core.reasoning_strategy import get_optimal_reasoning_effort
        
        # 取得所有工具定義（OpenAI 格式）
        tools = tool_registry.get_openai_tools(
            include_location_tools=include_location_tools,
            strict=True,
        )
        
        if not tools:
            logger.warning("⚠️ 沒有可用的工具")
            return False, {"emotion": "neutral"}
        
        # 建構精簡的 system prompt（只處理情緒和特殊規則）
        system_prompt = self._build_system_prompt()
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message}
        ]
        
        # 使用 OpenAI Function Calling
        optimal_effort = get_optimal_reasoning_effort("intent_detection")
        logger.info(f"🧠 意圖檢測推理強度: {optimal_effort}")
        
        try:
            response = await ai_service.generate_response_with_tools(
                messages=messages,
                tools=tools,
                user_id="intent_detection",
                model=settings.GPT_INTENT_MODEL,
                reasoning_effort=optimal_effort,
            )
            
            return self._parse_function_calling_response(response)
            
        except Exception as e:
            logger.error(f"❌ Function Calling 失敗: {e}")
            raise
    
    def _build_system_prompt(self) -> str:
        """
        建構精簡的 system prompt
        
        注意：不再描述每個工具，工具定義由 tools 參數傳遞
        """
        return f"""你是一個多語言智能助手，根據用戶需求選擇合適的工具。支援中文、英文、日文、印尼文、越南文。

{get_tool_calling_policy()}

【核心規則】
1. 用戶詢問任何可用工具能解決的需求時，必須選擇對應工具
2. 只有純粹的閒聊、問候、情感表達才不選擇工具
3. 工具參數從用戶消息中提取；無法確定的可選參數留空，不自行編造預設值

【多語言意圖識別】
無論用戶使用什麼語言，都要識別以下意圖並選擇對應工具：

天氣查詢（weather_query）：
- 中文：天氣、氣溫、會下雨嗎、今天熱嗎
- 英文：weather, temperature, rain, hot today, forecast
- 日文：天気、気温、雨、暑い
- 印尼文：cuaca, suhu, hujan
- 越南文：thời tiết, nhiệt độ, mưa

匯率查詢（exchange_rate）：
- 中文：匯率、換算、多少錢
- 英文：exchange rate, convert, currency
- 日文：為替、両替
- 印尼文：kurs, tukar
- 越南文：tỷ giá, đổi tiền

新聞查詢（news_search）：
- 中文：新聞、頭條、最新消息
- 英文：news, headlines, latest
- 日文：ニュース、最新
- 印尼文：berita, terbaru
- 越南文：tin tức, mới nhất

【參數處理】
- 天氣查詢：城市名稱使用英文（台北→Taipei, 東京→Tokyo, Jakarta, Hanoi）
- 匯率查詢：貨幣使用 ISO 4217 代碼（USD, TWD, JPY, IDR, VND）
- 公車查詢：route_name 必須是路線號碼（如 307、紅30）
- 火車查詢：「往XX」表示 destination_station
- 位置查詢：「我在哪」「where am I」使用 reverse_geocode
- YouBike 查詢：YouBike/Ubike/微笑單車 使用 tdx_youbike

【情緒判斷 - 重要】
根據用戶消息的語氣判斷情緒，並在回應開頭以 [EMOTION:xxx] 格式輸出：
- [EMOTION:neutral] - 平靜、中性、一般詢問
- [EMOTION:happy] - 開心、興奮、正面情緒（如：我很快樂、太棒了、好開心）
- [EMOTION:sad] - 難過、沮喪、失落
- [EMOTION:angry] - 生氣、煩躁、憤怒
- [EMOTION:fear] - 恐懼、擔心、焦慮
- [EMOTION:surprise] - 驚訝、意外

範例：
- 用戶說「我很快樂」→ 回應開頭必須是 [EMOTION:happy]
- 用戶說「今天天氣如何」→ 回應開頭必須是 [EMOTION:neutral]
- 用戶說「我好難過」→ 回應開頭必須是 [EMOTION:sad]"""
    
    def _parse_function_calling_response(
        self,
        response: Dict[str, Any],
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        解析 Function Calling 回應
        
        Args:
            response: OpenAI API 回應
        
        Returns:
            (是否檢測到工具調用, 意圖數據)
        """
        # 檢查是否有 tool_calls
        tool_calls = response.get("tool_calls", [])
        
        if tool_calls:
            # 取第一個工具調用
            tool_call = tool_calls[0]
            function = tool_call.get("function", {})
            tool_name = function.get("name", "")
            arguments_str = function.get("arguments", "{}")
            
            try:
                arguments = json.loads(arguments_str)
            except json.JSONDecodeError:
                arguments = {}
            
            logger.info(f"✅ GPT 選擇工具: {tool_name}")
            logger.debug(f"工具參數: {arguments}")
            
            # 提取情緒（從 content 或預設）
            emotion = self._extract_emotion_from_response(response)
            
            return True, {
                "type": "mcp_tool",
                "tool_name": tool_name,
                "arguments": arguments,
                "emotion": emotion,
                "confidence": self._estimate_tool_confidence(tool_name, arguments),
            }
        
        # 沒有工具調用，視為一般聊天
        logger.info("💬 GPT 判斷為一般聊天")
        emotion = self._extract_emotion_from_response(response)
        
        return False, {"emotion": emotion}
    
    def _extract_emotion_from_response(self, response: Dict[str, Any]) -> str:
        """從回應中提取情緒
        
        優先使用 [EMOTION:xxx] 格式提取，降級使用關鍵字匹配
        """
        import re
        
        content = response.get("content", "")
        if not content:
            return "neutral"
        
        # 優先：使用正則表達式提取 [EMOTION:xxx] 格式
        emotion_match = re.search(r'\[EMOTION:(\w+)\]', content, re.IGNORECASE)
        if emotion_match:
            extracted = emotion_match.group(1).lower()
            if extracted in self.EMOTIONS:
                logger.info(f"🎭 從格式化標籤提取情緒: {extracted}")
                return extracted
        
        # 降級：使用關鍵字匹配（但需要更精確的匹配）
        content_lower = content.lower()
        for emotion in self.EMOTIONS:
            # 使用單詞邊界匹配，避免誤判（如 "not angry" 被判為 angry）
            pattern = rf'\b{emotion}\b'
            if re.search(pattern, content_lower):
                # 檢查是否有否定詞在前面
                negation_pattern = rf'(not|no|isn\'t|aren\'t|wasn\'t|weren\'t|don\'t|doesn\'t|didn\'t|never|neither)\s+{emotion}'
                if re.search(negation_pattern, content_lower):
                    continue  # 跳過被否定的情緒
                logger.info(f"🎭 從關鍵字提取情緒: {emotion}")
                return emotion
        
        return "neutral"
    
    def _keyword_fallback(self, message: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """關鍵字匹配降級方案"""
        message_lower = message.lower()
        
        # 取得所有工具摘要
        summaries = tool_registry.get_summaries()
        
        for summary in summaries:
            keywords = summary.get("keywords", [])
            for keyword in keywords:
                if keyword.lower() in message_lower:
                    logger.info(f"🔑 關鍵字匹配: {keyword} → {summary['name']}")
                    return True, {
                        "type": "mcp_tool",
                        "tool_name": summary["name"],
                        "arguments": {},
                        "emotion": "neutral",
                    }
        
        return False, {"emotion": "neutral"}
    
    def clear_cache(self) -> None:
        """清除快取"""
        self._cache.clear()
        logger.info("🗑️ 意圖快取已清除")


# 全域單例
intent_detector = IntentDetector()
