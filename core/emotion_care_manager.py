"""
情緒關懷模式管理器
當偵測到用戶極端情緒時（sad, angry, fear），自動進入關懷模式
關懷模式下禁用所有工具調用，專注於情感支持
用戶說「我沒事了」等關鍵字後才解除
"""

import logging
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class EmotionCareManager:
    """情緒關懷模式管理器（單例模式）"""

    # 極端情緒定義（需要進入關懷模式的情緒）
    EXTREME_EMOTIONS = {"sad", "angry", "fear"}

    # 解除關懷模式的關鍵字
    RELEASE_KEYWORDS = [
        "我沒事了", "我好了", "沒事了", "好多了", "好一點了",
        "我好些了", "沒關係了", "我ok了", "我可以了",
        "不用擔心", "別擔心我"
    ]

    # 用戶關懷狀態
    # 結構: {user_id: {chat_key: {"in_care_mode": bool, "emotion": str, "start_time": float}}}
    _user_states: Dict[str, Dict[str, Dict]] = {}
    _DEFAULT_CHAT_KEY = "__default__"

    @classmethod
    def _resolve_chat_key(cls, chat_id: Optional[str]) -> str:
        return chat_id or cls._DEFAULT_CHAT_KEY

    @classmethod
    def _get_state(cls, user_id: str, chat_id: Optional[str]) -> Optional[Dict]:
        user_states = cls._user_states.get(user_id)
        if not user_states:
            return None
        return user_states.get(cls._resolve_chat_key(chat_id))

    @classmethod
    def _set_state(cls, user_id: str, chat_id: Optional[str], state: Dict) -> None:
        key = cls._resolve_chat_key(chat_id)
        user_states = cls._user_states.setdefault(user_id, {})
        user_states[key] = state

    @classmethod
    def check_and_enter_care_mode(cls, user_id: str, emotion: str, chat_id: Optional[str] = None) -> bool:
        """
        檢查情緒是否為極端情緒，若是則進入關懷模式

        參數:
            user_id: 用戶 ID
            emotion: 偵測到的情緒（neutral, happy, sad, angry, fear, surprise）

        返回:
            bool: 是否進入關懷模式（True=進入，False=不需要）
        """
        if not emotion or emotion not in cls.EXTREME_EMOTIONS:
            return False

        # 進入關懷模式
        cls._set_state(user_id, chat_id, {
            "in_care_mode": True,
            "emotion": emotion,
            "start_time": time.time()
        })

        logger.warning(f"⚠️ 用戶 {user_id}（chat={chat_id or 'default'}）偵測到極端情緒 [{emotion}]，進入關懷模式")
        return True

    @classmethod
    def check_release(cls, user_id: str, message: str, chat_id: Optional[str] = None) -> bool:
        """
        檢查用戶訊息是否包含解除關鍵字

        參數:
            user_id: 用戶 ID
            message: 用戶訊息

        返回:
            bool: 是否解除關懷模式（True=解除，False=繼續關懷）
        """
        state = cls._get_state(user_id, chat_id)
        if not state or not state.get("in_care_mode", False):
            return False

        # 檢查是否包含解除關鍵字
        message_lower = message.lower().strip()
        for keyword in cls.RELEASE_KEYWORDS:
            if keyword in message_lower:
                # 解除關懷模式
                emotion = state.get("emotion", "unknown")
                duration = time.time() - state.get("start_time", 0)

                state["in_care_mode"] = False

                logger.info(f"✅ 用戶 {user_id}（chat={chat_id or 'default'}）情緒恢復（{emotion} → 正常），解除關懷模式（持續 {duration:.1f}秒）")
                return True

        return False

    @classmethod
    def is_in_care_mode(cls, user_id: str, chat_id: Optional[str] = None) -> bool:
        """
        查詢用戶是否在關懷模式中

        參數:
            user_id: 用戶 ID

        返回:
            bool: 是否在關懷模式
        """
        state = cls._get_state(user_id, chat_id)
        if not state:
            return False
        return state.get("in_care_mode", False)

    @classmethod
    def get_care_emotion(cls, user_id: str, chat_id: Optional[str] = None) -> Optional[str]:
        """
        取得用戶當前關懷模式的情緒

        參數:
            user_id: 用戶 ID

        返回:
            Optional[str]: 情緒標籤（若不在關懷模式則返回 None）
        """
        state = cls._get_state(user_id, chat_id)
        if not state or not state.get("in_care_mode", False):
            return None

        return state.get("emotion")

    @classmethod
    def force_exit_care_mode(cls, user_id: str, chat_id: Optional[str] = None) -> None:
        """
        強制退出關懷模式（用於測試或特殊情況）

        參數:
            user_id: 用戶 ID
            chat_id: 對話 ID（可選；若為 None 則關閉預設對話）
        """
        if user_id not in cls._user_states:
            return
        key = cls._resolve_chat_key(chat_id)
        if key in cls._user_states[user_id]:
            cls._user_states[user_id][key]["in_care_mode"] = False
            logger.info(f"🔧 強制解除用戶 {user_id}（chat={chat_id or 'default'}）的關懷模式")

    @classmethod
    def get_all_care_users(cls) -> Dict[str, Dict]:
        """
        取得所有在關懷模式中的用戶（用於監控）

        返回:
            Dict: {user_id: state_info}
        """
        result: Dict[str, Dict] = {}
        for uid, chat_states in cls._user_states.items():
            active = {
                chat: state
                for chat, state in chat_states.items()
                if state.get("in_care_mode", False)
            }
            if active:
                result[uid] = active
        return result
