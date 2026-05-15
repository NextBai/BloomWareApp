import pytest

from features.mcp.agent_bridge import MCPAgentBridge
from features.mcp.tool_models import ToolResult


class RecordingCoordinator:
    def __init__(self):
        self.calls = []

    async def invoke(self, tool_name, arguments, *, user_id, original_message):
        self.calls.append((tool_name, arguments, user_id, original_message))
        return ToolResult(
            name=tool_name,
            message=f"{tool_name} ok",
            data={"arguments": arguments},
        )


@pytest.mark.asyncio
async def test_process_intent_executes_multiple_tool_calls_in_order():
    bridge = MCPAgentBridge.__new__(MCPAgentBridge)
    coordinator = RecordingCoordinator()
    bridge._tool_coordinator = coordinator

    result = await bridge.process_intent(
        {
            "type": "mcp_tool",
            "tool_calls": [
                {"tool_name": "weather_query", "arguments": {"city": "Taipei"}},
                {"tool_name": "exchange_query", "arguments": {"from_currency": "USD", "to_currency": "TWD"}},
            ],
        },
        user_id="u1",
        original_message="台北天氣和美元匯率",
        chat_id="c1",
    )

    assert coordinator.calls == [
        ("weather_query", {"city": "Taipei"}, "u1", "台北天氣和美元匯率"),
        ("exchange_query", {"from_currency": "USD", "to_currency": "TWD"}, "u1", "台北天氣和美元匯率"),
    ]
    assert result["tool_name"] == "multi_tool"
    assert result["tool_data"]["tool_names"] == ["weather_query", "exchange_query"]
    assert "weather_query ok" in result["message"]
    assert "exchange_query ok" in result["message"]
