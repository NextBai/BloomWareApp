"""
語音綁定狀態機
管理語音帳號綁定流程（關鍵字匹配，無 GPT）
"""

import logging
import time
from datetime import datetime
from typing import Dict, Any, Optional
from fastapi import WebSocket

logger = logging.getLogger("websocket.voice_binding")


class VoiceBindingStateMachine:
    """
    語音帳號綁定狀態機（硬編碼關鍵字匹配）

    流程：
    1. 用戶說「我要綁定語音登入」
    2. Agent 回應「好的，你現在要綁定誰？」
    3. 用戶提供名稱
    4. 系統綁定 speaker_label 到用戶帳號
    5. Agent 回應「綁定成功！」
    """

    def __init__(self):
        # 用戶狀態：{user_id: {state: str, speaker_label: str}}
        self.user_states: Dict[str, Dict[str, Any]] = {}

    def check_binding_trigger(self, user_id: str, message: str) -> Optional[str]:
        """
        檢查是否觸發綁定流程

        Returns:
            - "TRIGGER": 觸發綁定流程
            - "AWAITING_NAME": 等待用戶提供名稱
            - None: 不是綁定相關訊息
        """
        message_lower = message.lower().replace(" ", "")

        # 檢測觸發關鍵字
        trigger_keywords = ["綁定語音登入", "語音登入綁定", "綁定語音", "設定語音登入"]
        for keyword in trigger_keywords:
            if keyword.replace(" ", "") in message_lower:
                # 進入等待狀態
                self.user_states[user_id] = {
                    "state": "AWAITING_NAME",
                    "timestamp": datetime.now()
                }
                return "TRIGGER"

        # 檢查是否在等待名稱狀態
        if user_id in self.user_states:
            state_info = self.user_states[user_id]
            if state_info.get("state") == "AWAITING_NAME":
                # 檢查是否超時（5分鐘）
                if (datetime.now() - state_info.get("timestamp")).total_seconds() > 300:
                    del self.user_states[user_id]
                    return None
                return "AWAITING_NAME"

        return None

    async def handle_binding_flow(
        self,
        user_id: str,
        message: str,
        websocket: WebSocket,
        voice_service: Optional[Any] = None,
        manager: Optional[Any] = None,
    ) -> bool:
        """
        處理綁定流程

        Returns:
            True: 已處理（不要繼續到 Agent）
            False: 未處理（繼續到 Agent）
        """
        state = self.check_binding_trigger(user_id, message)

        if state == "TRIGGER":
            # 用戶觸發綁定 - 先檢查是否已經綁定過
            logger.info(f"🎙️ 用戶 {user_id} 觸發語音綁定流程")

            # 檢查使用者是否已經綁定過 speaker_label
            from core.database import get_user_by_id
            try:
                user_data = await get_user_by_id(user_id)
                if user_data and user_data.get("speaker_label"):
                    # 已經綁定過了
                    existing_label = user_data.get("speaker_label")
                    logger.info(f"⚠️ 用戶 {user_id} 已綁定 speaker_label: {existing_label}")

                    await websocket.send_json({
                        "type": "bot_message",
                        "message": f"你已經綁定過語音了！目前的聲紋標籤是：{existing_label}。如果需要重新綁定，請聯繫管理員。",
                        "timestamp": time.time()
                    })

                    # 清理 FSM 狀態
                    self.clear_state(user_id)
                    return True
            except Exception as e:
                logger.error(f"❌ 檢查使用者綁定狀態失敗: {e}")
                await websocket.send_json({
                    "type": "error",
                    "message": "系統錯誤，無法檢查綁定狀態"
                })
                return True

            # 未綁定，繼續綁定流程
            logger.info(f"✅ 用戶 {user_id} 尚未綁定，啟動綁定流程")

            # 標記用戶進入語音綁定等待狀態
            if manager:
                user_session = manager.get_client_info(user_id) or {}
                user_session["voice_binding_pending"] = True
                user_session["voice_binding_started_at"] = datetime.now()
                manager.set_client_info(user_id, user_session)

            await websocket.send_json({
                "type": "bot_message",
                "message": "好的，請錄製一段語音（約3-5秒），用於建立你的聲紋特徵。系統會自動識別並綁定到你的帳號。",
                "timestamp": time.time()
            })
            await websocket.send_json({
                "type": "voice_binding_ready",
                "message": "請點擊錄音按鈕開始錄製"
            })
            return True

        elif state == "AWAITING_NAME":
            # 這個狀態已不再使用，因為我們改為直接錄音綁定
            pass

        return False

    def clear_state(self, user_id: str):
        """清理用戶狀態"""
        self.user_states.pop(user_id, None)

    def is_in_binding_flow(self, user_id: str) -> bool:
        """檢查用戶是否在綁定流程中"""
        return user_id in self.user_states


# 全局語音綁定狀態機實例
voice_binding_fsm = VoiceBindingStateMachine()
