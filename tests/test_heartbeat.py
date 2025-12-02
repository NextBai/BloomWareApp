"""
測試 websocket/heartbeat.py 心跳機制
"""

import pytest
import time
from websocket.heartbeat import HeartbeatManager, HEARTBEAT_INTERVAL, HEARTBEAT_TIMEOUT


class TestHeartbeatManager:
    """測試心跳管理器"""

    def test_init(self):
        """測試初始化"""
        manager = HeartbeatManager()
        assert manager._last_heartbeat == {}
        assert manager._heartbeat_tasks == {}

    def test_record_heartbeat(self):
        """測試記錄心跳"""
        manager = HeartbeatManager()
        manager.record_heartbeat("user123")
        
        assert "user123" in manager._last_heartbeat
        assert manager._last_heartbeat["user123"] <= time.time()

    def test_get_last_heartbeat(self):
        """測試取得最後心跳時間"""
        manager = HeartbeatManager()
        
        # 未記錄時返回 None
        assert manager.get_last_heartbeat("user123") is None
        
        # 記錄後返回時間戳
        manager.record_heartbeat("user123")
        last = manager.get_last_heartbeat("user123")
        assert last is not None
        assert last <= time.time()

    def test_is_alive_true(self):
        """測試連線存活（剛記錄心跳）"""
        manager = HeartbeatManager()
        manager.record_heartbeat("user123")
        
        assert manager.is_alive("user123") is True

    def test_is_alive_false_no_heartbeat(self):
        """測試連線不存活（無心跳記錄）"""
        manager = HeartbeatManager()
        assert manager.is_alive("user123") is False

    def test_is_alive_false_timeout(self):
        """測試連線不存活（超時）"""
        manager = HeartbeatManager()
        # 模擬很久以前的心跳
        manager._last_heartbeat["user123"] = time.time() - 1000
        
        assert manager.is_alive("user123", timeout=60) is False

    def test_get_stats(self):
        """測試取得統計"""
        manager = HeartbeatManager()
        manager.record_heartbeat("user1")
        manager.record_heartbeat("user2")
        
        stats = manager.get_stats()
        assert stats["tracked_users"] == 2
        assert stats["active_heartbeats"] == 0  # 沒有啟動任務

    def test_set_disconnect_callback(self):
        """測試設定斷線回調"""
        manager = HeartbeatManager()
        
        async def callback(user_id: str):
            pass
        
        manager.set_disconnect_callback(callback)
        assert manager._disconnect_callback is not None


class TestHeartbeatConstants:
    """測試心跳常數"""

    def test_heartbeat_interval(self):
        """測試心跳間隔"""
        assert HEARTBEAT_INTERVAL > 0
        assert HEARTBEAT_INTERVAL <= 60  # 不應超過 1 分鐘

    def test_heartbeat_timeout(self):
        """測試心跳超時"""
        assert HEARTBEAT_TIMEOUT > 0
        assert HEARTBEAT_TIMEOUT < HEARTBEAT_INTERVAL  # 超時應小於間隔
