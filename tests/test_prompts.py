"""
測試 core/prompts 模組
"""

import pytest
from core.prompts.intent_detection import get_intent_prompt, TOOL_RULES
from core.prompts.care_mode import get_care_prompt, CARE_MODE_PROMPT


class TestIntentPrompt:
    """測試意圖檢測 Prompt"""

    def test_get_intent_prompt_basic(self):
        """測試基本 Prompt 生成"""
        prompt = get_intent_prompt("工具列表")
        assert "意圖解析" in prompt
        assert "工具列表" in prompt
        assert "is_tool_call" in prompt

    def test_get_intent_prompt_with_rules(self):
        """測試帶規則的 Prompt"""
        prompt = get_intent_prompt("工具", include_rules=["weather", "bus"])
        assert "天氣" in prompt or "Taipei" in prompt
        assert "公車" in prompt or "route_name" in prompt

    def test_get_intent_prompt_empty_rules(self):
        """測試空規則"""
        prompt = get_intent_prompt("工具", include_rules=[])
        assert "意圖解析" in prompt
        assert "emotion" in prompt

    def test_tool_rules_defined(self):
        """測試工具規則已定義"""
        assert "weather" in TOOL_RULES
        assert "bus" in TOOL_RULES
        assert "train" in TOOL_RULES
        assert "youbike" in TOOL_RULES
        assert "location" in TOOL_RULES

    def test_prompt_length_reduced(self):
        """測試 Prompt 長度合理"""
        prompt = get_intent_prompt("工具列表")
        # 精簡後應少於 2000 字元
        assert len(prompt) < 2000


class TestCarePrompt:
    """測試關懷模式 Prompt"""

    def test_care_mode_prompt_exists(self):
        """測試關懷 Prompt 存在"""
        assert CARE_MODE_PROMPT is not None
        assert "小花" in CARE_MODE_PROMPT
        assert "傾聽" in CARE_MODE_PROMPT

    def test_get_care_prompt_basic(self):
        """測試基本關懷 Prompt"""
        prompt = get_care_prompt()
        assert "小花" in prompt
        assert "60 字" in prompt

    def test_get_care_prompt_with_emotion(self):
        """測試帶情緒的關懷 Prompt"""
        prompt = get_care_prompt(emotion="sad")
        assert "sad" in prompt
        assert "用戶情緒" in prompt

    def test_get_care_prompt_with_name(self):
        """測試帶名稱的關懷 Prompt"""
        prompt = get_care_prompt(user_name="小明")
        assert "小明" in prompt
        assert "用戶名稱" in prompt

    def test_get_care_prompt_full(self):
        """測試完整關懷 Prompt"""
        prompt = get_care_prompt(emotion="angry", user_name="小華")
        assert "angry" in prompt
        assert "小華" in prompt
