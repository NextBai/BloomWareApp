"""
測試 websocket/manager.py 連線管理器
"""

import pytest
from datetime import datetime, timedelta
from websocket.manager import ConnectionManager


class TestConnectionManager:
    """測試 ConnectionManager 類別"""

    def test_init(self):
        """測試初始化"""
        manager = ConnectionManager()
        assert manager.active_connections == {}
        assert manager.client_info == {}
        assert manager.user_sessions == {}

    def test_is_connected_false(self):
        """測試未連線狀態"""
        manager = ConnectionManager()
        assert manager.is_connected("user123") is False

    def test_get_active_user_count_empty(self):
        """測試空連線數"""
        manager = ConnectionManager()
        assert manager.get_active_user_count() == 0

    def test_client_info(self):
        """測試客戶端資訊存取"""
        manager = ConnectionManager()
        manager.set_client_info("user123", {"device": "iPhone"})
        info = manager.get_client_info("user123")
        assert info == {"device": "iPhone"}

    def test_get_client_info_not_found(self):
        """測試取得不存在的客戶端資訊"""
        manager = ConnectionManager()
        info = manager.get_client_info("nonexistent")
        assert info == {}

    def test_get_user_session_not_found(self):
        """測試取得不存在的會話"""
        manager = ConnectionManager()
        session = manager.get_user_session("nonexistent")
        assert session is None
