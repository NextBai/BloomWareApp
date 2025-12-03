import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, Dict, Tuple, List

from core.emotion_care_manager import EmotionCareManager

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    text: str
    is_fallback: bool = False
    reason: Optional[str] = None  # e.g., "timeout", "error", "no_intent"
    meta: Optional[Dict[str, Any]] = None


class ChatPipeline:
    """
    非阻塞聊天處理管線，透過依賴注入以便測試與替換實作。

    依賴（皆為可 await 的 callables）：
    - intent_detector(message) -> tuple[bool, intent_data]
    - feature_processor(intent_data, user_id, original_message, chat_id) -> str
    - ai_generator(messages:list[dict], client_id:str, model:str|None, request_id:str|None, chat_id:str|None) -> str
    
    已移除未使用的依賴：
    - memory_manager: 短期記憶管理（未使用，已改用 memory_system）
    - summary_gate: 摘要決策（過度簡化，已移除）
    """

    def __init__(
        self,
        intent_detector: Callable[[str], Awaitable[Tuple[bool, dict]]],
        feature_processor: Callable[[dict, str, str, Optional[str]], Awaitable[Any]],
        ai_generator: Callable[..., Awaitable[str]],
        model: str = "gpt-5-nano",
        detect_timeout: float = 5.0,    # 2025 最佳實踐：Structured Outputs 通常 2-3秒
        feature_timeout: float = 10.0,  # MCP 工具已有內部超時（30秒）
        ai_timeout: float = 12.0,       # 配合 Streaming（首次回應 0.5-1秒）
    ) -> None:
        self._intent_detector = intent_detector
        self._feature_processor = feature_processor
        self._ai_generator = ai_generator
        self._detect_timeout = detect_timeout
        self._feature_timeout = feature_timeout
        self._ai_timeout = ai_timeout
        self._model = model
        
        # 語言名稱映射
        self._language_names = {
            "zh": "繁體中文",
            "en": "English",
            "ja": "日本語",
            "ko": "한국어",
            "id": "Bahasa Indonesia",
            "vi": "Tiếng Việt",
        }

    def _detect_language(self, text: str) -> str:
        """
        簡單的語言檢測（基於字符範圍）
        
        Args:
            text: 輸入文字
        
        Returns:
            語言代碼（zh, en, ja, ko, id, vi）
        """
        if not text:
            return "zh"
        
        # 統計各語言字符數量
        korean_count = 0
        japanese_count = 0
        chinese_count = 0
        latin_count = 0
        vietnamese_count = 0
        
        vietnamese_chars = set("àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ")
        
        for char in text:
            code = ord(char)
            # 韓文
            if 0xAC00 <= code <= 0xD7AF or 0x1100 <= code <= 0x11FF:
                korean_count += 1
            # 日文假名
            elif 0x3040 <= code <= 0x309F or 0x30A0 <= code <= 0x30FF:
                japanese_count += 1
            # 中文
            elif 0x4E00 <= code <= 0x9FFF:
                chinese_count += 1
            # 拉丁字母
            elif 0x0041 <= code <= 0x007A:
                latin_count += 1
            # 越南文特殊字符
            if char.lower() in vietnamese_chars:
                vietnamese_count += 1
        
        # 判斷主要語言
        if korean_count > 0:
            return "ko"
        if japanese_count > chinese_count and japanese_count > 0:
            return "ja"
        if vietnamese_count > 0:
            return "vi"
        if chinese_count > latin_count and chinese_count > 0:
            return "zh"
        if latin_count > 0:
            # 可能是英文或印尼文，預設英文
            return "en"
        
        return "zh"

    async def _translate_tool_data(self, tool_data: Dict[str, Any], target_language: str) -> Dict[str, Any]:
        """
        翻譯工具卡片中的文字欄位
        
        Args:
            tool_data: 工具資料字典
            target_language: 目標語言代碼
        
        Returns:
            翻譯後的工具資料
        """
        if not tool_data or target_language == "zh":
            return tool_data
        
        try:
            import copy
            translated_data = copy.deepcopy(tool_data)
            
            # 需要翻譯的欄位名稱（天氣、新聞等工具的顯示欄位）
            translatable_keys = {
                "description", "main", "name", "title", "summary", 
                "content", "message", "text", "label", "status"
            }
            
            # 收集需要翻譯的文字欄位
            texts_to_translate = []
            text_paths = []  # 記錄路徑以便回填
            
            def collect_texts(obj, path="", parent_key=""):
                """遞迴收集需要翻譯的文字"""
                if isinstance(obj, dict):
                    for key, value in obj.items():
                        new_path = f"{path}.{key}" if path else key
                        # 跳過純技術欄位
                        if key in ("id", "url", "link", "lat", "lon", "timestamp", "code", "icon", "base", "cod"):
                            continue
                        collect_texts(value, new_path, key)
                elif isinstance(obj, list):
                    for i, item in enumerate(obj):
                        collect_texts(item, f"{path}[{i}]", parent_key)
                elif isinstance(obj, str) and len(obj) > 1:
                    # 翻譯條件：
                    # 1. 欄位名稱在可翻譯列表中
                    # 2. 或字串包含中文
                    # 3. 或字串是純英文描述（非數字、非代碼）
                    should_translate = (
                        parent_key.lower() in translatable_keys or
                        any('\u4e00' <= c <= '\u9fff' for c in obj) or
                        (obj.isalpha() or ' ' in obj) and len(obj) > 2
                    )
                    if should_translate:
                        texts_to_translate.append(obj)
                        text_paths.append(path)
            
            collect_texts(translated_data)
            
            if not texts_to_translate:
                return tool_data
            
            # 批量翻譯
            import services.ai_service as ai_service
            lang_name = self._language_names.get(target_language, target_language)
            
            combined_text = "\n---\n".join(texts_to_translate)
            messages = [
                {
                    "role": "system",
                    "content": f"將以下內容翻譯成 {lang_name}，保持格式和表情符號。每段用 '---' 分隔，輸出也用 '---' 分隔。只輸出翻譯結果。"
                },
                {"role": "user", "content": combined_text}
            ]
            
            translated = await ai_service.generate_response_async(
                messages=messages,
                model="gpt-5-nano",
                reasoning_effort="minimal",
                max_tokens=800,  # 工具卡片翻譯：實際輸出限制 800 tokens
            )
            
            if translated:
                translated_parts = translated.strip().split("---")
                translated_parts = [p.strip() for p in translated_parts if p.strip()]
                
                # 回填翻譯結果
                def set_value(obj, path, value):
                    """根據路徑設置值"""
                    parts = path.replace("]", "").replace("[", ".").split(".")
                    for part in parts[:-1]:
                        if part.isdigit():
                            obj = obj[int(part)]
                        else:
                            obj = obj[part]
                    last = parts[-1]
                    if last.isdigit():
                        obj[int(last)] = value
                    else:
                        obj[last] = value
                
                for i, path in enumerate(text_paths):
                    if i < len(translated_parts):
                        try:
                            set_value(translated_data, path, translated_parts[i])
                        except Exception:
                            pass
            
            logger.info(f"🌐 工具卡片已翻譯: {len(texts_to_translate)} 個欄位")
            return translated_data
            
        except Exception as e:
            logger.warning(f"⚠️ 工具卡片翻譯失敗: {e}")
            return tool_data

    async def _translate_tool_response(self, text: str, target_language: str) -> str:
        """
        翻譯工具回應到目標語言
        
        Args:
            text: 原始文字（中文）
            target_language: 目標語言代碼（en, ja, ko, id, vi）
        
        Returns:
            翻譯後的文字
        """
        if not text or target_language == "zh":
            return text
        
        try:
            import services.ai_service as ai_service
            
            lang_name = self._language_names.get(target_language, target_language)
            
            messages = [
                {
                    "role": "system",
                    "content": f"你是一個翻譯助手。將以下內容翻譯成 {lang_name}，保持格式、表情符號和數字不變。只輸出翻譯結果，不要加任何解釋。"
                },
                {
                    "role": "user",
                    "content": text
                }
            ]
            
            translated = await ai_service.generate_response_async(
                messages=messages,
                model="gpt-5-nano",
                reasoning_effort="minimal",
                max_tokens=500,  # 工具回應翻譯：實際輸出限制 500 tokens
            )
            
            if translated and translated.strip():
                logger.info(f"🌐 工具回應已翻譯: {target_language}")
                return translated.strip()
            
            return text
            
        except Exception as e:
            logger.warning(f"⚠️ 翻譯失敗，使用原文: {e}")
            return text

    async def _with_timeout(self, coro: Awaitable[Any], timeout: float, reason: str) -> Any:
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError:
            return PipelineResult(
                text="抱歉，我這邊有點忙碌，稍後再試可以嗎？",
                is_fallback=True,
                reason=reason,
                meta={"timeout": timeout},
            )
        except Exception as e:
            return PipelineResult(
                text=f"抱歉，處理時碰到狀況：{e}",
                is_fallback=True,
                reason=reason,
                meta={"error": str(e)},
            )

    async def process(
        self,
        user_message: str,
        user_id: Optional[str] = None,
        chat_id: Optional[str] = None,
        request_id: Optional[str] = None,
        audio_emotion: Optional[Dict[str, Any]] = None,
        language: Optional[str] = None,
    ) -> PipelineResult:
        if not user_message or not user_message.strip():
            return PipelineResult(text="我沒有收到您的消息，請重新輸入。", is_fallback=True, reason="empty")

        # 自動檢測語言（如果沒有傳入）
        if not language:
            language = self._detect_language(user_message)
            logger.info(f"🌐 自動檢測語言: {language}")

        # 0) 先進行意圖偵測以提取情緒（需要在關懷模式檢查前執行）
        detect_res = await self._with_timeout(
            self._intent_detector(user_message), self._detect_timeout, reason="detect"
        )
        if isinstance(detect_res, PipelineResult):
            return detect_res
        has_feature, intent_data = detect_res

        # 提取情緒（雙軌制：音頻情緒優先，文字情緒輔助）
        text_emotion = intent_data.get("emotion", "neutral") if intent_data else "neutral"
        
        # 情緒融合邏輯
        if audio_emotion and audio_emotion.get("success"):
            audio_emotion_label = audio_emotion.get("emotion", "neutral")
            audio_confidence = audio_emotion.get("confidence", 0.0)
            
            # 優先使用音頻情緒（置信度 >= 0.5）
            if audio_confidence >= 0.5:
                emotion_value = audio_emotion_label
                logger.info(f"🎭 使用音頻情緒: {emotion_value} (置信度: {audio_confidence:.4f})")
                logger.info(f"📝 文字情緒: {text_emotion} (輔助)")
            else:
                emotion_value = text_emotion
                logger.info(f"📝 使用文字情緒: {emotion_value} (音頻置信度過低: {audio_confidence:.4f})")
        else:
            emotion_value = text_emotion
            logger.info(f"📝 使用文字情緒: {emotion_value} (無音頻情緒)")

        # 1) 檢查是否在關懷模式
        if user_id and EmotionCareManager.is_in_care_mode(user_id, chat_id):
            # 檢查是否解除關懷模式（傳入情緒資訊）
            if EmotionCareManager.check_release(user_id, user_message, chat_id, emotion=emotion_value):
                logger.info(f"✅ 用戶 {user_id} 情緒恢復，解除關懷模式，繼續正常流程")
                # 解除後繼續正常流程
            else:
                logger.info(f"💙 用戶 {user_id} 在關懷模式中，跳過工具調用，使用關懷 AI")
                # 直接用關懷模式 AI 回應（不檢測意圖，不調用工具）
                care_emotion = EmotionCareManager.get_care_emotion(user_id, chat_id)
                ai_res = await self._with_timeout(
                    self._ai_generator(
                        user_message,
                        user_id,
                        self._model,
                        request_id,
                        chat_id,
                        use_care_mode=True,
                        care_emotion=care_emotion,
                        emotion_label=care_emotion,
                    ),
                    self._ai_timeout,
                    reason="ai-care",
                )
                if isinstance(ai_res, PipelineResult):
                    return ai_res
                text = str(ai_res or "").strip()
                if not text:
                    return PipelineResult(text="我在這裡陪你，隨時可以聊聊。", is_fallback=True, reason="ai-care-empty")
                return PipelineResult(text=text, is_fallback=False, meta={"care_mode": True, "emotion": care_emotion})

        # 2) 檢查是否需要進入關懷模式
        if user_id and EmotionCareManager.check_and_enter_care_mode(user_id, emotion_value, chat_id):
            logger.warning(f"⚠️ 偵測到極端情緒 [{emotion_value}]，進入關懷模式")
            # 立即使用關懷模式 AI 回應
            ai_res = await self._with_timeout(
                self._ai_generator(
                    user_message,
                    user_id,
                    self._model,
                    request_id,
                    chat_id,
                    use_care_mode=True,
                    care_emotion=emotion_value,
                    emotion_label=emotion_value,
                ),
                self._ai_timeout,
                reason="ai-care",
            )
            if isinstance(ai_res, PipelineResult):
                return ai_res
            text = str(ai_res or "").strip()
            if not text:
                text = "我聽到了，我在這裡陪你。"

            # 第一次進入關懷模式時，附加退出提示（新增）
            exit_hint = "\n\n💙 關懷模式已啟動。說「我沒事了」可以退出。"
            return PipelineResult(text=text + exit_hint, is_fallback=False, meta={"care_mode": True, "emotion": emotion_value})

        # 3) 有功能 → 功能處理(限時)
        if has_feature and intent_data:
            feat_res = await self._with_timeout(
                self._feature_processor(intent_data, user_id, user_message, chat_id),
                self._feature_timeout,
                reason="feature",
            )
            if isinstance(feat_res, PipelineResult):
                return feat_res
            # 如果返回 None，表示這是聊天，不應該被當作功能處理
            if feat_res is None:
                has_feature = False
                intent_data = None
            else:
                # 檢查是否為字典（包含工具信息）
                if isinstance(feat_res, dict):
                    text = feat_res.get('message', feat_res.get('content', '')).strip()
                    tool_name = feat_res.get('tool_name')
                    tool_data = feat_res.get('tool_data')
                    if not text:
                        return PipelineResult(text="抱歉，功能處理沒有產出結果。", is_fallback=True, reason="feature-empty")
                    
                    # 如果語言不是中文，翻譯工具回應和工具卡片
                    if language and language != "zh":
                        text = await self._translate_tool_response(text, language)
                        # 翻譯工具卡片中的文字欄位
                        if tool_data:
                            tool_data = await self._translate_tool_data(tool_data, language)
                    
                    # 返回帶有工具元數據的結果（包含情緒）
                    meta_dict = {}
                    if tool_name:
                        meta_dict['tool_name'] = tool_name
                    if tool_data:
                        meta_dict['tool_data'] = tool_data
                    meta_dict['emotion'] = emotion_value

                    return PipelineResult(
                        text=text,
                        is_fallback=False,
                        meta=meta_dict if meta_dict else None
                    )
                else:
                    # 正常字串
                    text = str(feat_res or "").strip()
                    if not text:
                        return PipelineResult(text="抱歉，功能處理沒有產出結果。", is_fallback=True, reason="feature-empty")
                    
                    # 如果語言不是中文，翻譯工具回應
                    if language and language != "zh":
                        text = await self._translate_tool_response(text, language)
                    
                    return PipelineResult(
                        text=text,
                        is_fallback=False,
                        meta={"emotion": emotion_value},
                    )

        # 4) 無功能 → 一般聊天（限時）
        # 注意：不傳 messages，改傳 user_message，讓 ai_generator 自動載入歷史對話和記憶
        ai_res = await self._with_timeout(
            self._ai_generator(
                user_message,
                user_id or "default",
                self._model,
                request_id,
                chat_id,
                emotion_label=emotion_value,
                language=language,
            ),
            self._ai_timeout,
            reason="ai",
        )
        if isinstance(ai_res, PipelineResult):
            return ai_res
        text = str(ai_res or "").strip()
        if not text:
            return PipelineResult(text="抱歉，我暫時沒有合適的回應。可以換個說法再試試嗎？", is_fallback=True, reason="ai-empty")

        # 一般聊天也包含情緒資訊（新增）
        meta_dict = {}
        meta_dict['emotion'] = emotion_value

        return PipelineResult(text=text, is_fallback=False, meta=meta_dict if meta_dict else None)
