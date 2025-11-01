import asyncio
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[4]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from features.mcp.agent_bridge import MCPAgentBridge  # noqa: E402


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
