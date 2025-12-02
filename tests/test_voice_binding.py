"""
測試 services/voice_binding.py 語音綁定狀態機
"""

import pytest
from services.voice_binding import VoiceBindingStateMachine


class TestVoiceBindingStateMachine:
    """測試 VoiceBindingStateMachine 類別"""

    def test_init(self):
        """測試初始化"""
        fsm = VoiceBindingStateMachine()
        assert fsm.user_states == {}

    def test_trigger_keywords(self):
        """測試觸發關鍵字"""
        fsm = VoiceBindingStateMachine()

        # 測試各種觸發關鍵字
        assert fsm.check_binding_trigger("user1", "我要綁定語音登入") == "TRIGGER"
        assert fsm.check_binding_trigger("user2", "語音登入綁定") == "TRIGGER"
        assert fsm.check_binding_trigger("user3", "綁定語音") == "TRIGGER"
        assert fsm.check_binding_trigger("user4", "設定語音登入") == "TRIGGER"

    def test_no_trigger(self):
        """測試非觸發訊息"""
        fsm = VoiceBindingStateMachine()

        assert fsm.check_binding_trigger("user1", "你好") is None
        assert fsm.check_binding_trigger("user1", "今天天氣如何") is None
        assert fsm.check_binding_trigger("user1", "語音") is None

    def test_clear_state(self):
        """測試清理狀態"""
        fsm = VoiceBindingStateMachine()

        # 觸發後清理
        fsm.check_binding_trigger("user1", "綁定語音登入")
        assert "user1" in fsm.user_states

        fsm.clear_state("user1")
        assert "user1" not in fsm.user_states

    def test_is_awaiting_voice(self):
        """測試等待語音狀態"""
        fsm = VoiceBindingStateMachine()

        # 初始狀態
        assert fsm.is_awaiting_voice("user1") is False

        # 觸發後
        fsm.check_binding_trigger("user1", "綁定語音登入")
        assert fsm.is_awaiting_voice("user1") is True

        # 清理後
        fsm.clear_state("user1")
        assert fsm.is_awaiting_voice("user1") is False
