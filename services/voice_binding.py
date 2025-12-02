"""
語音綁定狀態機
處理語音帳號綁定流程（關鍵字匹配，無 GPT）
"""

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

from fastapi import WebSocket

from core.logging import get_logger

logger = get_logger("services.voice_binding")


def get_available_speaker_labels() -> List[str]:
    """讀取可用的 speaker label 列表"""
    classes_file = Path("models/speaker_identification/models_cnn/classes.txt")
    if classes_file.exists():
        with open(classes_file, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    return []


class VoiceBindingStateMachine:
    """
    語音帳號綁定狀態機（硬編碼關鍵字匹配）

    流程：
    1. 用戶說「綁定語音登入」
    2. 系統詢問「你要綁定哪個帳號？」並顯示可用的 label 列表
    3. 用戶輸入帳號名稱（label）
    4. 系統綁定 speaker_label 到用戶帳號
    5. 系統回應「綁定成功囉！」
    """

    # 觸發關鍵字
    TRIGGER_KEYWORDS = [
        "綁定語音登入",
        "語音登入綁定",
        "綁定語音",
        "設定語音登入",
    ]

    # 狀態超時時間（秒）
    STATE_TIMEOUT = 300  # 5 分鐘

    def __init__(self):
        # 用戶狀態：{user_id: {state: str, timestamp: datetime}}
        self.user_states: Dict[str, Dict[str, Any]] = {}

    def check_binding_trigger(self, user_id: str, message: str) -> Optional[str]:
        """
        檢查是否觸發綁定流程

        Returns:
            - "TRIGGER": 觸發綁定流程
            - "AWAITING_LABEL": 等待用戶輸入帳號名稱
            - None: 不是綁定相關訊息
        """
        message_lower = message.lower().replace(" ", "")

        # 檢測觸發關鍵字
        for keyword in self.TRIGGER_KEYWORDS:
            if keyword.replace(" ", "") in message_lower:
                self.user_states[user_id] = {
                    "state": "AWAITING_LABEL",
                    "timestamp": datetime.now()
                }
                return "TRIGGER"

        # 檢查是否在等待輸入帳號名稱狀態
        if user_id in self.user_states:
            state_info = self.user_states[user_id]
            if state_info.get("state") == "AWAITING_LABEL":
                # 檢查是否超時
                elapsed = (datetime.now() - state_info.get("timestamp")).total_seconds()
                if elapsed > self.STATE_TIMEOUT:
                    del self.user_states[user_id]
                    return None
                return "AWAITING_LABEL"

        return None

    async def handle_binding_flow(
        self,
        user_id: str,
        message: str,
        websocket: WebSocket,
        voice_service: Optional[Any] = None,
        get_user_by_id: Optional[Any] = None,
    ) -> bool:
        """
        處理綁定流程

        Args:
            user_id: 用戶 ID
            message: 用戶訊息
            websocket: WebSocket 連線
            voice_service: 語音認證服務（可選）
            get_user_by_id: 取得用戶資料的函數（可選）

        Returns:
            True: 已處理（不要繼續到 Agent）
            False: 未處理（繼續到 Agent）
        """
        state = self.check_binding_trigger(user_id, message)

        if state == "TRIGGER":
            logger.info(f"🎙️ 用戶 {user_id} 觸發語音綁定流程")

            # 檢查使用者是否已經綁定過 speaker_label
            if get_user_by_id:
                try:
                    user_data = await get_user_by_id(user_id)
                    if user_data and user_data.get("speaker_label"):
                        existing_label = user_data.get("speaker_label")
                        logger.info(f"⚠️ 用戶 {user_id} 已綁定 speaker_label: {existing_label}")

                        await websocket.send_json({
                            "type": "bot_message",
                            "message": (
                                f"你已經綁定過語音了！目前的聲紋標籤是：{existing_label}。"
                                "如果需要重新綁定，請聯繫管理員。"
                            ),
                            "timestamp": time.time()
                        })

                        self.clear_state(user_id)
                        return True

                except Exception as e:
                    logger.error(f"❌ 檢查使用者綁定狀態失敗: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "message": "系統錯誤，無法檢查綁定狀態"
                    })
                    return True

            # 未綁定，顯示可用的 label 列表
            available_labels = get_available_speaker_labels()
            labels_str = "、".join(available_labels) if available_labels else "（無可用帳號）"
            
            logger.info(f"✅ 用戶 {user_id} 尚未綁定，詢問要綁定的帳號")

            await websocket.send_json({
                "type": "bot_message",
                "message": f"好的，你要綁定哪個帳號呢？\n可用的帳號有：{labels_str}\n請輸入帳號名稱：",
                "timestamp": time.time()
            })

            return True

        elif state == "AWAITING_LABEL":
            # 用戶輸入了帳號名稱
            label_input = message.strip().lower()
            available_labels = get_available_speaker_labels()
            
            logger.info(f"🎙️ 用戶 {user_id} 輸入帳號名稱: {label_input}")

            # 檢查輸入的 label 是否有效
            if label_input not in [l.lower() for l in available_labels]:
                labels_str = "、".join(available_labels)
                await websocket.send_json({
                    "type": "bot_message",
                    "message": f"找不到這個帳號喔！可用的帳號有：{labels_str}\n請重新輸入：",
                    "timestamp": time.time()
                })
                return True

            # 找到匹配的 label（保持原始大小寫）
            matched_label = next((l for l in available_labels if l.lower() == label_input), label_input)

            # 執行綁定
            try:
                from core.database import get_user_by_speaker_label, set_user_speaker_label

                # 檢查這個 label 是否已被其他用戶綁定
                existing_user = await get_user_by_speaker_label(matched_label)
                if existing_user and existing_user.get("id") != user_id:
                    await websocket.send_json({
                        "type": "bot_message",
                        "message": f"這個帳號（{matched_label}）已經被其他人綁定了，請選擇其他帳號。",
                        "timestamp": time.time()
                    })
                    return True

                # 綁定到當前用戶
                bind_result = await set_user_speaker_label(user_id, matched_label)

                if bind_result.get("success"):
                    logger.info(f"✅ 用戶 {user_id} 成功綁定 speaker_label: {matched_label}")
                    await websocket.send_json({
                        "type": "bot_message",
                        "message": f"綁定成功囉！🎉 你的語音帳號已設定為：{matched_label}",
                        "timestamp": time.time()
                    })
                    await websocket.send_json({
                        "type": "voice_binding_success",
                        "speaker_label": matched_label
                    })
                else:
                    error_msg = bind_result.get("error", "未知錯誤")
                    await websocket.send_json({
                        "type": "bot_message",
                        "message": f"綁定失敗：{error_msg}",
                        "timestamp": time.time()
                    })

            except Exception as e:
                logger.error(f"❌ 綁定 speaker_label 失敗: {e}")
                await websocket.send_json({
                    "type": "bot_message",
                    "message": "系統錯誤，綁定失敗，請稍後再試。",
                    "timestamp": time.time()
                })

            # 清理狀態，返回待機模式
            self.clear_state(user_id)
            return True

        return False

    def clear_state(self, user_id: str) -> None:
        """清理用戶狀態"""
        self.user_states.pop(user_id, None)

    def is_awaiting_label(self, user_id: str) -> bool:
        """檢查用戶是否在等待輸入帳號名稱狀態"""
        if user_id not in self.user_states:
            return False

        state_info = self.user_states[user_id]
        if state_info.get("state") != "AWAITING_LABEL":
            return False

        # 檢查是否超時
        elapsed = (datetime.now() - state_info.get("timestamp")).total_seconds()
        if elapsed > self.STATE_TIMEOUT:
            del self.user_states[user_id]
            return False

        return True

    # 保留舊方法名稱以保持相容性
    def is_awaiting_voice(self, user_id: str) -> bool:
        """檢查用戶是否在等待語音錄製狀態（已棄用，保留相容性）"""
        return self.is_awaiting_label(user_id)


# 全域單例
voice_binding_fsm = VoiceBindingStateMachine()
