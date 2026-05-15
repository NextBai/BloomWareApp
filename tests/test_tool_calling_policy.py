import inspect

from core.intent_detector import IntentDetector
from core.prompts.tool_calling_policy import get_tool_calling_policy
from features.mcp.agent_bridge import MCPAgentBridge


def test_shared_tool_policy_contains_required_guards():
    policy = get_tool_calling_policy()

    assert "反幻覺" in policy
    assert "環境優先" in policy
    assert "參數紀律" in policy
    assert "工具失敗" in policy
    assert "不得憑印象補答案" in policy
    assert "不要編造 city/lat/lon" in policy
    assert "至少 90%" in policy
    assert "語言一致" in policy


def test_agent_bridge_prompt_embeds_tool_policy():
    bridge = MCPAgentBridge()

    prompt = bridge._build_function_calling_prompt()

    assert get_tool_calling_policy() in prompt
    assert "Weather/News/Exchange" in prompt
    assert "附近" in prompt
    assert "不要編造 city/lat/lon" in prompt


def test_tool_response_formatter_forbids_guessing():
    source = inspect.getsource(MCPAgentBridge._format_tool_response)

    assert "嚴禁推測" in source
    assert "資料缺漏" in source
    assert "不得把工具錯誤包裝成成功結果" in source


def test_intent_detector_prompt_embeds_tool_policy():
    detector = IntentDetector()

    prompt = detector._build_system_prompt()

    assert get_tool_calling_policy() in prompt
    assert "無法確定的可選參數留空" in prompt
    assert "不得憑印象補答案" in prompt
