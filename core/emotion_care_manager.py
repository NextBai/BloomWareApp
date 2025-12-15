"""
情緒關懷模式管理器
當偵測到用戶極端情緒時（sad, angry, fear），自動進入關懷模式
關懷模式下禁用所有工具調用，專注於情感支持
用戶說「我沒事了」等關鍵字後才解除

【2025 優化版】
- 加入連續性檢查：需要連續 N 次偵測到極端情緒才觸發（避免誤判）
- 支援情緒強度權重：音頻情緒 + 文字情緒雙軌融合
- 調整 TTL 和冷卻時間，更精準的觸發機制
"""

import logging
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class EmotionCareManager:
    """情緒關懷模式管理器（單例模式）"""

    # 極端情緒定義（需要進入關懷模式的情緒）
    EXTREME_EMOTIONS = {"sad", "angry", "fear"}

    # 正面情緒定義（可以解除關懷模式的情緒）
    POSITIVE_EMOTIONS = {"neutral", "happy", "surprise"}

    # 模式存活與冷卻（避免反覆觸發）
    CARE_TTL_SECONDS = 8 * 60   # 8 分鐘自動失效（縮短以更快恢復正常）
    COOLDOWN_SECONDS = 2 * 60   # 2 分鐘內不重入（縮短以提高響應性）

    # 【新增】連續性觸發設定
    # 【優化】降低門檻：第一次明確的極端情緒就觸發，避免「太遲鈍」
    CONSECUTIVE_THRESHOLD = 1   # 需要 1 次極端情緒即可觸發（原本 2 次太嚴格）
    EMOTION_WINDOW_SECONDS = 90 # 情緒計數窗口：90秒內的情緒才計入

    # 解除關懷模式的關鍵字
    RELEASE_KEYWORDS = [
        # 繁體中文
        "我沒事了", "我好了", "沒事了", "好多了", "好一點了",
        "我好些了", "沒關係了", "我ok了", "我可以了",
        "不用擔心", "別擔心我", "謝謝關心", "感謝你",
        "我很好", "心情好多了", "開心", "快樂", "高興",
        "沒問題", "放心", "安心了", "舒服多了",
        # 簡體中文
        "我没事了", "没事了", "好一点了", "没关系了",
        "不用担心", "别担心我", "谢谢关心", "感谢你",
        "我很好", "心情好多了", "开心", "快乐", "高兴",
        "没问题", "放心", "安心了", "舒服多了",
        # 英文
        "i'm fine", "i am fine", "i'm ok", "i am ok", "i'm okay", "i am okay",
        "i feel better", "feeling better", "much better", "all good",
        "don't worry", "no worries", "thank you", "thanks",
        # 日文
        "大丈夫", "元気", "ありがとう", "心配しないで",
        # 印尼文
        "saya baik", "tidak apa-apa", "terima kasih",
        # 越南文
        "tôi ổn", "không sao", "cảm ơn",
    ]

    # 用戶關懷狀態
    # 結構: {user_id: {chat_key: {
    #   "in_care_mode": bool,
    #   "emotion": str,
    #   "start_time": float,
    #   "last_exit_time": float,
    #   "emotion_history": [(timestamp, emotion), ...]  # 【新增】情緒歷史
    # }}}
    _user_states: Dict[str, Dict[str, Dict]] = {}
    _DEFAULT_CHAT_KEY = "__default__"

    @classmethod
    def _count_recent_extreme_emotions(cls, emotion_history: list) -> int:
        """計算窗口內的極端情緒次數"""
        now = time.time()
        count = 0
        for ts, emo in emotion_history:
            if now - ts <= cls.EMOTION_WINDOW_SECONDS and emo in cls.EXTREME_EMOTIONS:
                count += 1
        return count

    @classmethod
    def _clean_old_emotions(cls, emotion_history: list) -> list:
        """清理過期的情緒記錄"""
        now = time.time()
        return [(ts, emo) for ts, emo in emotion_history if now - ts <= cls.EMOTION_WINDOW_SECONDS * 2]

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
    def check_and_enter_care_mode(
        cls,
        user_id: str,
        emotion: str,
        chat_id: Optional[str] = None,
        confidence: float = 1.0,
        force: bool = False
    ) -> bool:
        """
        檢查情緒是否為極端情緒，若是則進入關懷模式

        【2025 優化版】加入連續性檢查，避免誤判

        參數:
            user_id: 用戶 ID
            emotion: 偵測到的情緒（neutral, happy, sad, angry, fear, surprise）
            chat_id: 對話 ID（可選）
            confidence: 情緒置信度（0.0-1.0），高置信度可降低連續性要求
            force: 強制進入（跳過連續性檢查，用於明確極端情況）

        返回:
            bool: 是否進入關懷模式（True=進入，False=不需要）
        """
        key = cls._resolve_chat_key(chat_id)
        user_states = cls._user_states.get(user_id) or {}
        prev_state = user_states.get(key) or {}

        # 取得或初始化情緒歷史
        emotion_history = prev_state.get("emotion_history", [])
        emotion_history = cls._clean_old_emotions(emotion_history)

        # 記錄當前情緒（不管是不是極端情緒都記錄）
        emotion_history.append((time.time(), emotion))

        # 更新狀態（保存情緒歷史）
        prev_state["emotion_history"] = emotion_history
        cls._set_state(user_id, chat_id, prev_state)

        # 如果不是極端情緒，直接返回
        if not emotion or emotion not in cls.EXTREME_EMOTIONS:
            return False

        # 冷卻期防抖：若剛退出不久，避免馬上重入
        last_exit = prev_state.get("last_exit_time", 0.0)
        if last_exit and (time.time() - last_exit) < cls.COOLDOWN_SECONDS:
            logger.debug(f"⏸️ 用戶 {user_id} 在冷卻期內，不進入關懷模式")
            return False

        # 【連續性檢查】計算窗口內的極端情緒次數
        extreme_count = cls._count_recent_extreme_emotions(emotion_history)

        # 高置信度（>0.7）可降低門檻為 1 次
        # 強制模式（force=True）直接進入
        threshold = 1 if (confidence > 0.7 or force) else cls.CONSECUTIVE_THRESHOLD

        logger.info(f"🎭 情緒檢查: emotion={emotion}, confidence={confidence:.2f}, "
                   f"extreme_count={extreme_count}/{threshold}, force={force}")

        if extreme_count < threshold:
            logger.debug(f"⏸️ 用戶 {user_id} 極端情緒次數不足 ({extreme_count}/{threshold})，不進入關懷模式")
            return False

        # 進入關懷模式
        cls._set_state(user_id, chat_id, {
            "in_care_mode": True,
            "emotion": emotion,
            "start_time": time.time(),
            "last_exit_time": prev_state.get("last_exit_time", 0.0),
            "emotion_history": emotion_history,
        })

        logger.warning(f"⚠️ 用戶 {user_id}（chat={chat_id or 'default'}）偵測到連續極端情緒 [{emotion}]（{extreme_count}次），進入關懷模式")
        return True

    @classmethod
    def check_release(cls, user_id: str, message: str, chat_id: Optional[str] = None, emotion: Optional[str] = None) -> bool:
        """
        檢查用戶訊息是否包含解除關鍵字或情緒恢復為 neutral

        參數:
            user_id: 用戶 ID
            message: 用戶訊息
            chat_id: 對話 ID（可選）
            emotion: 當前偵測到的情緒（可選）

        返回:
            bool: 是否解除關懷模式（True=解除，False=繼續關懷）
        """
        state = cls._get_state(user_id, chat_id)
        if not state or not state.get("in_care_mode", False):
            return False

        # 優先檢查情緒：如果偵測到正面情緒（neutral, happy, surprise），立即解除關懷模式
        if emotion and emotion.lower() in cls.POSITIVE_EMOTIONS:
            original_emotion = state.get("emotion", "unknown")
            duration = time.time() - state.get("start_time", 0)

            state["in_care_mode"] = False
            state["last_exit_time"] = time.time()

            logger.info(f"✅ 用戶 {user_id}（chat={chat_id or 'default'}）情緒恢復為 {emotion}（{original_emotion} → {emotion}），解除關懷模式（持續 {duration:.1f}秒）")
            return True

        # 檢查是否包含解除關鍵字
        message_lower = message.lower().strip()
        for keyword in cls.RELEASE_KEYWORDS:
            if keyword in message_lower:
                # 解除關懷模式
                original_emotion = state.get("emotion", "unknown")
                duration = time.time() - state.get("start_time", 0)

                state["in_care_mode"] = False
                state["last_exit_time"] = time.time()

                logger.info(f"✅ 用戶 {user_id}（chat={chat_id or 'default'}）情緒恢復（{original_emotion} → 正常），解除關懷模式（持續 {duration:.1f}秒）")
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
        if not state.get("in_care_mode", False):
            return False
        # TTL：超時自動解除
        start = state.get("start_time", 0.0)
        if start and (time.time() - start) > cls.CARE_TTL_SECONDS:
            state["in_care_mode"] = False
            state["last_exit_time"] = time.time()
            logger.info(f"⏳ 用戶 {user_id}（chat={chat_id or 'default'}）關懷模式逾時自動解除")
            return False
        return True

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
