"""
測試 core/prompts 模組
"""

import pytest
from core.prompts.intent_detection import get_intent_prompt, TOOL_RULES
from core.prompts.care_mode import get_care_prompt, CARE_MODE_PROMPT
from services.ai_service import _build_base_system_prompt, _compose_messages_with_context


class TestIntentPrompt:
    """測試意圖檢測 Prompt"""

    def test_get_intent_prompt_basic(self):
        """測試基本 Prompt 生成"""
        prompt = get_intent_prompt("工具列表")
        assert "意圖解析" in prompt
        assert "工具列表" in prompt
        assert "is_tool_call" in prompt
        assert "反幻覺" in prompt
        assert "環境優先" in prompt
        assert "不得憑印象補答案" in prompt

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


class TestVoiceOutputPrompt:
    def test_base_system_prompt_prefers_spoken_concise_answers(self):
        prompt = _build_base_system_prompt(
            use_care_mode=False,
            care_emotion=None,
            user_name="小明",
            language="zh-TW",
        )

        assert "語音輸出風格" in prompt
        assert "自然口語" in prompt
        assert "不要輸出「資料來源」" in prompt
        assert "不要輸出「資料來源」「來源如下」「參考連結」「URL」" in prompt

    def test_tool_context_is_grounding_not_mandatory_source_dump(self):
        messages = _compose_messages_with_context(
            base_prompt="base",
            history_entries=[],
            memory_context="",
            env_context="",
            time_context="",
            emotion_context="",
            current_request="今天台積電多少",
            user_id="u1",
            chat_id="c1",
            use_care_mode=False,
            care_emotion=None,
            tool_context="Yahoo: 417.72 USD",
        )

        system_prompt = messages[0]["content"]
        assert "這些資料主要用於查證與內部 grounding" in system_prompt
        assert "不要在最終答案中列出來源、連結、URL" in system_prompt
        assert "預設輸出是給人直接聽的口語答案" in system_prompt
