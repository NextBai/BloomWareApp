import asyncio
from pathlib import Path
import sys
import types

ROOT_DIR = Path(__file__).resolve().parents[4]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from features.mcp.agent_bridge import MCPAgentBridge  # noqa: E402
from features.mcp.tools.base_tool import ExecutionError  # noqa: E402


def test_prepare_route_arguments_injects_labels():
    bridge = MCPAgentBridge.__new__(MCPAgentBridge)

    async def fake_resolve(_self, _lat, _lon):
        return "測試地點"

    bridge._resolve_coordinate_label = fake_resolve.__get__(bridge, MCPAgentBridge)  # type: ignore[attr-defined]

    prepared, labels = asyncio.run(
        bridge._prepare_route_arguments(
            {
                "origin_lat": "24.9915",
                "origin_lon": "121.3423",
                "dest_lat": "24.9891",
                "dest_lon": "121.3134",
                # 未提供 label，應自動補上
            }
        )
    )

    assert prepared["origin_label"] == "測試地點"
    assert prepared["dest_label"] == "測試地點"
    assert isinstance(prepared["origin_lat"], float)
    assert isinstance(prepared["dest_lon"], float)
    assert labels["origin_label"] == "測試地點"
    assert labels["dest_label"] == "測試地點"


def test_build_directions_message_returns_human_friendly_text():
    bridge = MCPAgentBridge.__new__(MCPAgentBridge)

    message, tool_data = bridge._build_directions_message(
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

    result = bridge._build_directions_failure_response(
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


def test_call_mcp_tool_returns_fallback_when_directions_fails():
    bridge = MCPAgentBridge.__new__(MCPAgentBridge)

    async def fake_enrich(tool_name, arguments, user_id):
        return arguments

    async def fake_handler(_arguments):
        raise ExecutionError("OpenRouteService 無法提供路線")

    async def fake_resolve(_self, _lat, _lon):
        return "測試地點"

    bridge._enrich_arguments_with_env = fake_enrich  # type: ignore[attr-defined]
    bridge._resolve_coordinate_label = fake_resolve.__get__(bridge, MCPAgentBridge)  # type: ignore[attr-defined]

    bridge.mcp_server = types.SimpleNamespace(
        tools={
            "directions": types.SimpleNamespace(
                handler=fake_handler,
                description="Route",
                metadata={"category": "地理"},
                inputSchema={"properties": {}, "required": []},
            )
        }
    )

    result = asyncio.run(
        bridge._call_mcp_tool(
            "directions",
            {"origin_lat": 25.045, "origin_lon": 121.516, "dest_lat": 24.993, "dest_lon": 121.324},
            user_id="u123",
            original_message="測試路線",
        )
    )

    assert isinstance(result, dict)
    assert result["tool_name"] == "directions"
    assert result["tool_data"]["fallback"] is True
    assert "目前無法向路線服務取得詳細路線" in result["message"]
