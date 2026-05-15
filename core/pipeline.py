import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, Dict, Tuple, List

from core.emotion_care_manager import EmotionCareManager
from core.config import settings
from core.voice_care_gate import decide_voice_care, is_voice_context

logger = logging.getLogger(__name__)

MIN_TOOL_CONFIDENCE = 0.90


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
        model: Optional[str] = None,
        detect_timeout: float = 20.0,   # 考量到 Function Calling 可能較慢
        feature_timeout: float = 30.0,  # MCP 工具內部超時
        ai_timeout: float = 25.0,       # 配合 Streaming
    ) -> None:
        self._intent_detector = intent_detector
        self._feature_processor = feature_processor
        self._ai_generator = ai_generator
        self._detect_timeout = detect_timeout
        self._feature_timeout = feature_timeout
        self._ai_timeout = ai_timeout
        self._model = model or settings.OPENAI_MODEL

    def _is_chinese_message(self, text: str) -> bool:
        """
        簡化語言判斷：檢測訊息是否為中文

        Args:
            text: 用戶訊息

        Returns:
            True 如果訊息主要是中文，False 如果是其他語言
        """
        if not text:
            return True  # 預設為中文

        # 計算中文字符比例
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        total_chars = len(text.replace(' ', '').replace('\n', ''))

        if total_chars == 0:
            return True

        # 如果中文字符超過 30%，視為中文訊息
        return chinese_chars > total_chars * 0.3

    async def _translate_tool_data(self, tool_data: Dict[str, Any], user_message: str) -> Dict[str, Any]:
        """
        簡化版工具卡片翻譯：讓 GPT 自動判斷目標語言

        Args:
            tool_data: 工具資料字典
            user_message: 用戶原始訊息（用於推斷目標語言）

        Returns:
            翻譯後的工具資料
        """
        if not tool_data:
            return tool_data

        try:
            import copy
            translated_data = copy.deepcopy(tool_data)

            # 需要翻譯的欄位（天氣、新聞等工具的顯示欄位）
            translatable_keys = {
                "description", "main", "name", "title", "summary",
                "content", "message", "text", "label", "status"
            }

            # 收集需要翻譯的文字
            texts_to_translate = []
            text_paths = []

            def collect_texts(obj, path="", parent_key=""):
                """遞迴收集需要翻譯的文字"""
                if isinstance(obj, dict):
                    for key, value in obj.items():
                        new_path = f"{path}.{key}" if path else key
                        # 跳過技術欄位
                        if key in ("id", "url", "link", "lat", "lon", "timestamp", "code", "icon"):
                            continue
                        collect_texts(value, new_path, key)
                elif isinstance(obj, list):
                    for i, item in enumerate(obj):
                        collect_texts(item, f"{path}[{i}]", parent_key)
                elif isinstance(obj, str) and len(obj) > 1:
                    # 需要翻譯的條件
                    should_translate = (
                        parent_key.lower() in translatable_keys or
                        any('\u4e00' <= c <= '\u9fff' for c in obj)  # 包含中文
                    )
                    if should_translate:
                        texts_to_translate.append(obj)
                        text_paths.append(path)

            collect_texts(translated_data)

            if not texts_to_translate:
                logger.info(f"🌐 無需翻譯的文字，直接返回原始資料")
                return tool_data

            # 批量翻譯（讓 GPT 自動判斷目標語言）
            import services.ai_service as ai_service

            logger.info(f"🌐 收集到 {len(texts_to_translate)} 個需要翻譯的文字")
            logger.debug(f"🌐 待翻譯文字: {texts_to_translate[:3]}...")  # 只顯示前3個

            combined_text = "\n---\n".join(texts_to_translate)
            messages = [
                {
                    "role": "system",
                    "content": f"將以下內容翻譯成與用戶訊息「{user_message}」相同的語言。保持格式和表情符號。每段用 '---' 分隔，輸出也用 '---' 分隔。只輸出翻譯結果，不要加解釋。"
                },
                {"role": "user", "content": combined_text}
            ]

            logger.info(f"🌐 呼叫 GPT 翻譯")
            # 格式化回應使用環境變數設定的模型
            model = settings.GPT_INTENT_MODEL or settings.OPENAI_MODEL
            logger.info(f"🎨 使用配置模型進行格式化: {model}")
            
            translated = await ai_service.generate_response_async(
                messages=messages,
                model=model,
                reasoning_effort=None,
                max_tokens=800,
            )
            logger.info(f"🌐 GPT 翻譯完成，結果長度: {len(translated) if translated else 0}")

            if translated:
                translated_parts = translated.strip().split("---")
                translated_parts = [p.strip() for p in translated_parts if p.strip()]

                # 回填翻譯結果
                def set_value(obj, path, value):
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
            logger.warning(f"⚠️ 工具卡片翻譯失敗，使用原始數據: {e}")
            return tool_data

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
        emotion_callback = None,
    ) -> PipelineResult:
        if not user_message or not user_message.strip():
            return PipelineResult(
                text="我沒有收到您的消息，請重新輸入。",
                is_fallback=True,
                reason="empty",
                meta={"emotion": "neutral", "care_mode": False}
            )

        # language 參數保留以向後兼容，但不使用（GPT 自動判斷語言）

        has_feature = False
        intent_data = None
        tool_context = ""
        tool_results_list = []
        emotion_value = "neutral"
        care_emotion = None
        use_care_mode = False
        max_loops = 3
        current_loop = 0
        ai_res_text = ""

        while current_loop < max_loops:
            # 0) 先進行意圖偵測與可回答性評估 (Confidence-driven check)
            detect_res = await self._with_timeout(
                self._intent_detector(user_message, tool_context, language=language), self._detect_timeout, reason="detect"
            )
            if isinstance(detect_res, PipelineResult):
                return detect_res
            has_feature, intent_data = detect_res
            
            if current_loop == 0:
                # 只在第一輪提取情緒與進行關懷模式判斷
                if intent_data and "emotion" in intent_data:
                    emotion_value = intent_data["emotion"]
                else:
                    emotion_value = "neutral"

                voice_context = is_voice_context(audio_emotion)
                voice_care_decision = None
                if voice_context:
                    try:
                        voice_care_decision = decide_voice_care(text_emotion=emotion_value, audio_emotion=audio_emotion)
                        if voice_care_decision.emotion:
                            emotion_value = voice_care_decision.emotion
                    except Exception as e:
                        logger.warning(f"Voice care decision failed: {e}")

                emotion_confidence = float(audio_emotion.get("confidence", 0.0)) if isinstance(audio_emotion, dict) else 0.0

                if EmotionCareManager.is_in_care_mode(user_id):
                    exit_match = False
                    if "沒事了" in user_message or "謝謝" in user_message or "好多了" in user_message:
                        if emotion_value not in ["sad", "angry", "fear"]:
                            exit_match = True
                        if voice_context and voice_care_decision and not voice_care_decision.allow:
                            exit_match = True

                    if exit_match:
                        logger.info(f"💙 使用者情緒平穩 [{emotion_value}]，退出關懷模式")
                        EmotionCareManager.exit_care_mode(user_id)
                        use_care_mode = False
                        if emotion_callback:
                            try:
                                await emotion_callback(emotion_value, False)
                            except Exception as e:
                                logger.warning(f"emotion_callback 錯誤: {e}")
                    else:
                        logger.info(f"💙 維持關懷模式，情緒=[{emotion_value}]")
                        use_care_mode = True
                        care_emotion = EmotionCareManager._active_care_users.get(user_id, {}).get("emotion") or emotion_value
                        if emotion_callback:
                            try:
                                await emotion_callback(emotion_value, True)
                            except Exception as e:
                                logger.warning(f"emotion_callback 錯誤: {e}")

                        ai_res = await self._with_timeout(
                            self._ai_generator(
                                user_message,
                                user_id,
                                self._model,
                                request_id,
                                chat_id,
                                use_care_mode=use_care_mode,
                                care_emotion=care_emotion,
                                emotion_label=emotion_value,
                                is_first_care=False,
                            ),
                            self._ai_timeout,
                            reason="ai-care",
                        )
                        if isinstance(ai_res, PipelineResult):
                            return ai_res
                        text = str(ai_res or "").strip()
                        if not text:
                            text = "我在這裡陪你，隨時可以聊聊。"
                        return PipelineResult(text=text, is_fallback=False, meta={"care_mode": True, "emotion": care_emotion})

                # 檢查是否需要進入關懷模式
                can_enter_care = True
                if voice_context and voice_care_decision is not None:
                    can_enter_care = voice_care_decision.allow

                if can_enter_care and user_id and EmotionCareManager.check_and_enter_care_mode(
                    user_id, emotion_value, chat_id, confidence=emotion_confidence
                ):
                    logger.warning(f"⚠️ 偵測到極端情緒 [{emotion_value}]（置信度: {emotion_confidence:.2f}），進入關懷模式")
                    
                    if emotion_callback:
                        try:
                            await emotion_callback(emotion_value, True)
                        except Exception as e:
                            logger.warning(f"emotion_callback 錯誤: {e}")

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
                            is_first_care=True,  # 告知 Agent 這是第一次進入，需引導退出
                        ),
                        self._ai_timeout,
                        reason="ai-care",
                    )
                    if isinstance(ai_res, PipelineResult):
                        return ai_res
                    text = str(ai_res or "").strip()
                    if not text:
                        text = "我聽到了，我在這裡陪你。"

                    return PipelineResult(text=text, is_fallback=False, meta={"care_mode": True, "emotion": emotion_value})

                if emotion_callback:
                    try:
                        await emotion_callback(emotion_value, False)
                    except Exception as e:
                        logger.warning(f"emotion_callback 錯誤: {e}")

            if has_feature and intent_data and intent_data.get("type") == "mcp_tool":
                confidence = float(intent_data.get("confidence", 0.0) or 0.0)
                if confidence < MIN_TOOL_CONFIDENCE:
                    logger.info("🔒 工具信心度不足 %.2f，禁止調用工具", confidence)
                    return PipelineResult(
                        text=self._build_low_confidence_tool_message(user_message, confidence),
                        is_fallback=True,
                        reason="low_confidence",
                        meta={"confidence": confidence}
                    )

            if has_feature and intent_data:
                feat_res = await self._with_timeout(
                    self._feature_processor(intent_data, user_id, user_message, chat_id),
                    self._feature_timeout,
                    reason="feature",
                )
                if isinstance(feat_res, PipelineResult):
                    tool_context += f"\n[工具執行結果]:\n{feat_res.text}\n"
                    tool_results_list.append({"text": feat_res.text, "meta": feat_res.meta})
                elif isinstance(feat_res, dict):
                    t_name = feat_res.get('tool_name', 'unknown')
                    t_msg = feat_res.get('message', '')
                    t_data = feat_res.get('tool_data', {})
                    tool_context += f"\n[工具 {t_name} 執行結果]:\n{t_msg}\n(Data: {str(t_data)[:2000]})\n"
                    tool_results_list.append(feat_res)
                else:
                    text = str(feat_res or "").strip()
                    tool_context += f"\n[工具執行結果]:\n{text}\n"
                    tool_results_list.append({"text": text})
                # 【效能優化】短路機制：如果工具調用信心度為 100%，且是簡單工具，則不進入下一輪驗證
                if confidence >= 1.0:
                    logger.info("⚡ 工具執行信心度高且結果明確，跳過冗餘驗證")
                    break

                current_loop += 1
                continue
            else:
                # 如果沒有調用工具，表示 Agent 對目前答案已有 100% 信心，退出循環
                break

        # 4) 最後 AI 生成回應（結合了所有 tool_context）
        ai_res_text = await self._with_timeout(
            self._ai_generator(
                user_message,
                user_id or "default",
                self._model,
                request_id,
                chat_id,
                emotion_label=emotion_value,
                language=language,
                tool_context=tool_context,
            ),
            self._ai_timeout,
            reason="ai_gen",
        )
        if isinstance(ai_res_text, PipelineResult):
            return ai_res_text

        meta = {"emotion": emotion_value, "care_mode": use_care_mode}
        if tool_results_list:
            executed_tools = []
            for t in tool_results_list:
                if isinstance(t, dict) and t.get("tool_name"):
                    executed_tools.append({
                        "tool_name": t.get("tool_name"),
                        "tool_data": t.get("tool_data")
                    })
                elif hasattr(t, 'meta') and t.meta and t.meta.get("tool_name"):
                    executed_tools.append({
                        "tool_name": t.meta.get("tool_name"),
                        "tool_data": t.meta.get("tool_data")
                    })
            if executed_tools:
                meta["executed_tools"] = executed_tools
                # 兼容原有邏輯，將最後一個工具設為主卡片
                last_tool = executed_tools[-1]
                meta["tool_name"] = last_tool["tool_name"]
                meta["tool_data"] = last_tool["tool_data"]
            else:
                last_tool = tool_results_list[-1]
                if isinstance(last_tool, dict):
                    meta["tool_name"] = last_tool.get("tool_name")
                    meta["tool_data"] = last_tool.get("tool_data")
                elif hasattr(last_tool, 'meta') and last_tool.meta:
                    meta.update(last_tool.meta)

        return PipelineResult(
            text=str(ai_res_text or "").strip(),
            is_fallback=False,
            meta=meta
        )

    def _build_low_confidence_tool_message(self, user_message: str, confidence: float) -> str:
        """建立低信心度工具調用的提示訊息"""
        return "抱歉，我不太確定您的意思。您能說得更具體一點嗎？"
