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
    ) -> PipelineResult:
        if not user_message or not user_message.strip():
            return PipelineResult(text="我沒有收到您的消息，請重新輸入。", is_fallback=True, reason="empty")

        # 0) 檢查是否在關懷模式（新增）
        if user_id and EmotionCareManager.is_in_care_mode(user_id, chat_id):
            # 檢查是否解除關懷模式
            if EmotionCareManager.check_release(user_id, user_message, chat_id):
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

        # 1) 意圖偵測（限時）
        detect_res = await self._with_timeout(
            self._intent_detector(user_message), self._detect_timeout, reason="detect"
        )
        if isinstance(detect_res, PipelineResult):
            return detect_res
        has_feature, intent_data = detect_res

        # 提取情緒（新增）
        emotion = intent_data.get("emotion", "neutral") if intent_data else "neutral"
        emotion_value = emotion or "neutral"
        logger.info(f"😊 用戶情緒: {emotion}")

        # 檢查是否需要進入關懷模式（新增）
        if user_id and EmotionCareManager.check_and_enter_care_mode(user_id, emotion, chat_id):
            logger.warning(f"⚠️ 偵測到極端情緒 [{emotion}]，進入關懷模式")
            # 立即使用關懷模式 AI 回應
            ai_res = await self._with_timeout(
                self._ai_generator(
                    user_message,
                    user_id,
                    self._model,
                    request_id,
                    chat_id,
                    use_care_mode=True,
                    care_emotion=emotion,
                    emotion_label=emotion,
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
            return PipelineResult(text=text + exit_hint, is_fallback=False, meta={"care_mode": True, "emotion": emotion})

        # 2) 有功能 → 功能處理(限時)
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
                    return PipelineResult(
                        text=text,
                        is_fallback=False,
                        meta={"emotion": emotion_value},
                    )

        # 3) 無功能 → 一般聊天（限時）
        # 注意：不傳 messages，改傳 user_message，讓 ai_generator 自動載入歷史對話和記憶
        ai_res = await self._with_timeout(
            self._ai_generator(
                user_message,
                user_id or "default",
                self._model,
                request_id,
                chat_id,
                emotion_label=emotion_value,
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
