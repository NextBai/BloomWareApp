"""
WebSocket 連線管理器
統一管理 WebSocket 連線、會話狀態和訊息發送
"""

import logging
import time
from datetime import datetime
from typing import Dict, Any, Optional

from fastapi import WebSocket

from core.logging import get_logger

logger = get_logger("websocket.manager")


class ConnectionManager:
    """WebSocket 連線管理器"""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.client_info: Dict[str, dict] = {}
        self.user_sessions: Dict[str, Dict[str, Any]] = {}
        self.last_env: Dict[str, Dict[str, Any]] = {}

    async def connect(
        self,
        websocket: WebSocket,
        user_id: str,
        user_info: Dict[str, Any]
    ) -> None:
        """建立 WebSocket 連線"""
        await websocket.accept()
        self.active_connections[user_id] = websocket
        self.user_sessions[user_id] = user_info
        logger.info(f"新的 WebSocket 連接: {user_id}")

    def disconnect(self, user_id: str) -> None:
        """關閉 WebSocket 連線"""
        if user_id in self.active_connections:
            del self.active_connections[user_id]
        if user_id in self.user_sessions:
            del self.user_sessions[user_id]
        if user_id in self.client_info:
            del self.client_info[user_id]
        logger.info(f"WebSocket 連接關閉: {user_id}")

    async def send_message(
        self,
        message: str,
        user_id: str,
        message_type: str = "bot_message"
    ) -> bool:
        """發送訊息給指定用戶"""
        if user_id not in self.active_connections:
            logger.warning(f"用戶 {user_id} 不在線，無法發送訊息")
            return False

        try:
            payload = {
                "type": message_type,
                "message": message,
                "timestamp": time.time()
            }
            await self.active_connections[user_id].send_json(payload)

            # 日誌記錄（截斷過長訊息）
            preview = (str(message) or "").strip().replace("\n", " ")
            if len(preview) > 120:
                preview = preview[:120] + "..."
            logger.debug(
                f"WebSocket 已發送 → client={user_id} "
                f"type={message_type} preview=\"{preview}\""
            )
            return True

        except Exception as e:
            logger.error(f"發送訊息到客戶端 {user_id} 時出錯: {e}")
            return False

    async def send_json(
        self,
        data: Dict[str, Any],
        user_id: str
    ) -> bool:
        """發送 JSON 資料給指定用戶"""
        if user_id not in self.active_connections:
            return False

        try:
            await self.active_connections[user_id].send_json(data)
            return True
        except Exception as e:
            logger.error(f"發送 JSON 到客戶端 {user_id} 時出錯: {e}")
            return False

    def set_client_info(self, user_id: str, info: dict) -> None:
        """設定客戶端資訊"""
        self.client_info[user_id] = info

    def get_client_info(self, user_id: str) -> dict:
        """取得客戶端資訊"""
        return self.client_info.get(user_id, {})

    def get_user_session(self, user_id: str) -> Optional[Dict[str, Any]]:
        """取得用戶會話資訊"""
        return self.user_sessions.get(user_id)

    def update_last_activity(self, user_id: str) -> None:
        """更新用戶最後活動時間"""
        if user_id in self.user_sessions:
            self.user_sessions[user_id]["last_activity"] = datetime.now()

    def is_connected(self, user_id: str) -> bool:
        """檢查用戶是否在線"""
        return user_id in self.active_connections

    def get_active_user_count(self) -> int:
        """取得在線用戶數量"""
        return len(self.active_connections)

    async def cleanup_expired_sessions(self, timeout_seconds: int = None) -> int:
        """
        清理過期的用戶會話

        Args:
            timeout_seconds: 超時時間（秒），預設使用配置值

        Returns:
            清理的會話數量
        """
        if timeout_seconds is None:
            from core.config import settings
            timeout_seconds = settings.WEBSOCKET_SESSION_TIMEOUT
        current_time = datetime.now()
        expired_users = []

        for user_id, session_info in self.user_sessions.items():
            last_activity = session_info.get("last_activity", current_time)
            if (current_time - last_activity).total_seconds() > timeout_seconds:
                expired_users.append(user_id)

        for user_id in expired_users:
            logger.info(f"清理過期會話: {user_id}")
            self.disconnect(user_id)

        return len(expired_users)

    async def broadcast(
        self,
        message: str,
        message_type: str = "system",
        exclude_users: Optional[list] = None
    ) -> int:
        """
        廣播訊息給所有在線用戶

        Args:
            message: 訊息內容
            message_type: 訊息類型
            exclude_users: 排除的用戶列表

        Returns:
            成功發送的數量
        """
        exclude_users = exclude_users or []
        success_count = 0

        for user_id in list(self.active_connections.keys()):
            if user_id not in exclude_users:
                if await self.send_message(message, user_id, message_type):
                    success_count += 1

        return success_count


# 全域單例
manager = ConnectionManager()
