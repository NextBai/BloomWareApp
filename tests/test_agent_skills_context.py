from services import ai_service
from features.mcp import agent_bridge


class _SkillsSettings:
    OPENAI_ENABLE_SKILLS = True


def test_chat_prompt_includes_mcp_skills_context(monkeypatch):
    class Settings:
        OPENAI_ENABLE_SKILLS = True

    monkeypatch.setattr(ai_service, "settings", Settings)

    messages = ai_service._compose_messages_with_context(
        base_prompt="base",
        history_entries=[],
        memory_context="",
        env_context="",
        time_context="",
        emotion_context="",
        current_request="台北天氣如何",
        user_id="u1",
        chat_id="c1",
        use_care_mode=False,
        care_emotion=None,
    )

    system_prompt = messages[0]["content"]
    assert "【MCP工具技能索引】" in system_prompt
    assert "weather_query" in system_prompt
    assert "call_via=local_function_calling_tool_schema" in system_prompt


def test_function_calling_prompt_reads_skills_before_tool_selection(monkeypatch):
    monkeypatch.setattr(agent_bridge, "settings", _SkillsSettings)

    bridge = agent_bridge.MCPAgentBridge.__new__(agent_bridge.MCPAgentBridge)
    prompt = bridge._build_function_calling_prompt()

    skills_index_position = prompt.index("【MCP工具技能索引】")
    rules_position = prompt.index("Rules:")

    assert skills_index_position < rules_position
    assert "weather_query" in prompt
    assert "call_via=local_function_calling_tool_schema" in prompt
