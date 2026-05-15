from pathlib import Path

from features.mcp.skills import skills_prompt_block
from services.ai_service import _build_base_system_prompt, _compose_messages_with_context


def test_base_prompt_has_no_domain_specific_market_hardcoding():
    prompt = _build_base_system_prompt(
        use_care_mode=False,
        care_emotion=None,
        user_name=None,
    )

    forbidden = ["台積電", "2330", "台股", "ADR", "尚未開盤", "上一交易日"]
    assert not any(term in prompt for term in forbidden)


def test_compose_messages_uses_generic_time_sensitive_rule():
    messages = _compose_messages_with_context(
        base_prompt="base",
        history_entries=[],
        memory_context="",
        env_context="timezone: Asia/Taipei",
        time_context="當地時間: 2026-05-14 08:41（星期四，上午）\n時區: Asia/Taipei",
        emotion_context="",
        current_request="今天某公司股價多少？",
        user_id="u1",
        chat_id="c1",
        use_care_mode=False,
        care_emotion=None,
    )

    system_prompt = messages[0]["content"]
    assert "時間訊號" in system_prompt
    assert "環境訊號" in system_prompt
    assert "自行判斷" in system_prompt
    assert "來源時間早於用戶要求的時間範圍" in system_prompt
    assert "台積電" not in system_prompt
    assert "2330" not in system_prompt


def test_web_search_skill_is_generic_and_registered():
    skill_text = Path("features/mcp/skills/web_search/SKILL.md").read_text(encoding="utf-8")
    prompt = skills_prompt_block()

    assert "avoid_domain_specific_hardcoding: true" in skill_text
    assert "Do not hardcode domain-specific behavior" in skill_text
    assert "do not present it as today's/current result" in skill_text
    assert "web_search" in prompt
    assert "responses_hosted_tool_auto" in prompt
    assert "台積電" not in skill_text
    assert "2330" not in skill_text
