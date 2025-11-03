import asyncio
from pathlib import Path
import sys
import types

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from features.mcp.agent_bridge import MCPAgentBridge  # noqa: E402
from features.mcp.tools.base_tool import ExecutionError  # noqa: E402
from features.mcp.tool_models import ToolMetadata  # noqa: E402


def test_build_directions_message_returns_human_friendly_text():
    bridge = MCPAgentBridge.__new__(MCPAgentBridge)

    message, tool_data = bridge._build_directions_message(  # type: ignore[attr-defined]
        {"distance_m": 1450.0, "duration_s": 840.0, "polyline": "[]"},
        {"origin_label": "測試起點 A", "dest_label": "測試目的地 B"},
    )

    assert "測試起點 A" in message
    assert "測試目的地 B" in message
    assert "公里" in tool_data["distance_readable"] or "公尺" in tool_data["distance_readable"]
    assert tool_data["duration_readable"].endswith("分") or tool_data["duration_readable"].endswith("分鐘")
    assert "origin_lat" not in tool_data
    assert "dest_lon" not in tool_data


def test_build_directions_failure_response_generates_fallback_message():
    bridge = MCPAgentBridge.__new__(MCPAgentBridge)

    result = bridge._build_directions_failure_response(  # type: ignore[attr-defined]
        {
            "origin_lat": 25.045,
            "origin_lon": 121.516,
            "dest_lat": 24.993,
            "dest_lon": 121.324,
        },
        {"origin_label": "測試起點 A", "dest_label": "測試目的地 B"},
        "OpenRouteService 無法提供路線",
    )

    message = result["message"]
    tool_data = result["tool_data"]

    assert "測試起點 A" in message
    assert "測試目的地 B" in message
    assert tool_data["fallback"] is True
    assert tool_data["distance_estimated_m"] is not None
    assert "地圖" in message


def test_tool_coordinator_navigation_flow_uses_env_context():
    async def _run():
        async def env_provider(user_id):
            return {"lat": 25.0, "lon": 121.5, "label": "目前位置"}

        bridge = MCPAgentBridge(env_provider=env_provider)
        bridge._tool_coordinator.register(ToolMetadata(name='directions', enable_reformat=False))  # type: ignore[attr-defined]

        async def forward_handler(arguments):
            return {
                "success": True,
                "content": "定位完成",
                "data": {"best_match": {"lat": 24.9, "lon": 121.3, "label": arguments.get("query")}},
            }

        async def directions_handler(arguments):
            assert arguments["origin_label"] == "目前位置"
            assert arguments["dest_label"] == "桃園火車站"
            return {"success": True, "content": "沿著高速公路前進", "distance_m": 1000.0}

        bridge.mcp_server.tools = {
            "forward_geocode": types.SimpleNamespace(handler=forward_handler),
            "directions": types.SimpleNamespace(handler=directions_handler),
        }

        intent = {
            "type": "mcp_tool",
            "tool_name": "forward_geocode",
            "arguments": {"query": "桃園火車站"},
        }

        result = await bridge.process_intent(intent, user_id="u1", original_message="怎麼去桃園火車站")
        assert result["tool_name"] == "directions"
        assert '距離約' in result['message']

    asyncio.run(_run())


def test_directions_failure_produces_fallback_tool_result():
    async def _run():
        async def env_provider(user_id):
            return {"lat": 25.0, "lon": 121.5, "label": "目前位置"}

        bridge = MCPAgentBridge(env_provider=env_provider)
        bridge._tool_coordinator.register(ToolMetadata(name='directions', enable_reformat=False))  # type: ignore[attr-defined]

        async def forward_handler(arguments):
            return {
                "success": True,
                "content": "定位完成",
                "data": {"best_match": {"lat": 24.9, "lon": 121.3, "label": arguments.get("query")}},
            }

        async def directions_handler(arguments):
            raise ExecutionError("OpenRouteService 無法提供路線")

        bridge.mcp_server.tools = {
            "forward_geocode": types.SimpleNamespace(handler=forward_handler),
            "directions": types.SimpleNamespace(handler=directions_handler),
        }

        intent = {
            "type": "mcp_tool",
            "tool_name": "forward_geocode",
            "arguments": {"query": "桃園火車站"},
        }

        result = await bridge.process_intent(intent, user_id="u1", original_message="怎麼去桃園火車站")
        assert isinstance(result, dict)
        assert result["tool_name"] == "directions"
        assert result['tool_data']['fallback'] is True

    asyncio.run(_run())
