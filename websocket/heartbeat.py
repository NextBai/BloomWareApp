"""
WebSocket 心跳機制
保持連線穩定，自動檢測斷線
"""

import asyncio
import time
from typing import Dict, Optional, Callable, Awaitable

from core.logging import get_logger
from core.config import settings

logger = get_logger("websocket.heartbeat")

# 心跳間隔（秒）
HEARTBEAT_INTERVAL = 30

# 心跳超時（秒）
HEARTBEAT_TIMEOUT = 10

# 最大重連次數
MAX_RECONNECT_ATTEMPTS = 5


class HeartbeatManager:
    """
    WebSocket 心跳管理器

    功能：
    1. 定期發送心跳包
    2. 檢測連線狀態
    3. 觸發斷線回調
    """

    def __init__(self):
        # 用戶最後心跳時間
        self._last_heartbeat: Dict[str, float] = {}
        # 心跳任務
        self._heartbeat_tasks: Dict[str, asyncio.Task] = {}
        # 斷線回調
        self._disconnect_callback: Optional[Callable[[str], Awaitable[None]]] = None

    def set_disconnect_callback(
        self, callback: Callable[[str], Awaitable[None]]
    ) -> None:
        """設定斷線回調函數"""
        self._disconnect_callback = callback

    def record_heartbeat(self, user_id: str) -> None:
        """記錄用戶心跳"""
        self._last_heartbeat[user_id] = time.time()
        logger.debug(f"💓 收到心跳: {user_id}")

    def get_last_heartbeat(self, user_id: str) -> Optional[float]:
        """取得用戶最後心跳時間"""
        return self._last_heartbeat.get(user_id)

    def is_alive(self, user_id: str, timeout: float = HEARTBEAT_TIMEOUT * 3) -> bool:
        """檢查用戶連線是否存活"""
        last = self._last_heartbeat.get(user_id)
        if last is None:
            return False
        return (time.time() - last) < timeout

    async def start_heartbeat(
        self,
        user_id: str,
        send_func: Callable[[dict], Awaitable[bool]],
    ) -> None:
        """
        啟動心跳任務

        Args:
            user_id: 用戶 ID
            send_func: 發送訊息的函數
        """
        # 取消舊任務
        if user_id in self._heartbeat_tasks:
            self._heartbeat_tasks[user_id].cancel()

        # 記錄初始心跳
        self.record_heartbeat(user_id)

        # 建立新任務
        task = asyncio.create_task(
            self._heartbeat_loop(user_id, send_func)
        )
        self._heartbeat_tasks[user_id] = task
        logger.info(f"💓 啟動心跳任務: {user_id}")

    async def stop_heartbeat(self, user_id: str) -> None:
        """停止心跳任務"""
        if user_id in self._heartbeat_tasks:
            self._heartbeat_tasks[user_id].cancel()
            del self._heartbeat_tasks[user_id]
            logger.info(f"💔 停止心跳任務: {user_id}")

        if user_id in self._last_heartbeat:
            del self._last_heartbeat[user_id]

    async def _heartbeat_loop(
        self,
        user_id: str,
        send_func: Callable[[dict], Awaitable[bool]],
    ) -> None:
        """心跳循環"""
        missed_count = 0

        while True:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)

                # 發送心跳
                success = await send_func({
                    "type": "heartbeat",
                    "timestamp": time.time(),
                })

                if success:
                    missed_count = 0
                else:
                    missed_count += 1
                    logger.warning(f"⚠️ 心跳發送失敗: {user_id} (連續 {missed_count} 次)")

                # 檢查是否超時
                if not self.is_alive(user_id):
                    missed_count += 1
                    logger.warning(f"⚠️ 心跳超時: {user_id}")

                # 連續失敗超過閾值，觸發斷線
                if missed_count >= 3:
                    logger.error(f"❌ 連線失效: {user_id}")
                    if self._disconnect_callback:
                        await self._disconnect_callback(user_id)
                    break

            except asyncio.CancelledError:
                logger.debug(f"心跳任務被取消: {user_id}")
                break
            except Exception as e:
                logger.error(f"心跳任務錯誤: {user_id} - {e}")
                await asyncio.sleep(5)

    def get_stats(self) -> Dict[str, int]:
        """取得心跳統計"""
        return {
            "active_heartbeats": len(self._heartbeat_tasks),
            "tracked_users": len(self._last_heartbeat),
        }


# 全域單例
heartbeat_manager = HeartbeatManager()
