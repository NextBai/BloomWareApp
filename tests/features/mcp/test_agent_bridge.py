import asyncio
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from features.mcp.agent_bridge import MCPAgentBridge
from features.mcp.types import Tool


def test_detect_intent_normalizes_tool_name(monkeypatch):
    async def _run():
        bridge = MCPAgentBridge()
        bridge.mcp_server.tools = {
            "weather_query": Tool(
                name="weather_query",
                description="查詢天氣",
                inputSchema={"type": "object", "properties": {"city": {"type": "string"}}},
            )
        }

        async def fake_generate_response_for_user(*args, **kwargs):
            return json.dumps(
                {
                    "is_tool_call": True,
                    "tool_name": " Weather_Query : city=Taipei , country = tw ",
                    "emotion": "happy",
                }
            )

        monkeypatch.setattr(
            "features.mcp.agent_bridge.ai_service.generate_response_for_user",
            fake_generate_response_for_user,
        )
        monkeypatch.setattr(
            "features.mcp.agent_bridge.get_optimal_reasoning_effort",
            lambda *args, **kwargs: "minimal",
        )

        has_feature, intent = await bridge.detect_intent("查一下今天天氣")

        assert has_feature is True
        assert intent["tool_name"] == "weather_query"
        assert intent["arguments"] == {"city": "Taipei", "country": "tw"}
        assert intent["emotion"] == "happy"

    asyncio.run(_run())
