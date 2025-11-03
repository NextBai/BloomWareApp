import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, Optional

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from features.mcp.coordinator import ToolCoordinator
from features.mcp.tool_models import ToolMetadata


def test_tool_coordinator_env_injection():
    async def _run():
        captured: Dict[str, Any] = {}

        async def env_provider(user_id: Optional[str]) -> Dict[str, Any]:
            return {"lat": 25.0, "lon": 121.5, "city": "Taipei"}

        async def weather_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
            nonlocal captured
            captured = dict(arguments)
            return {"success": True, "content": "晴時多雲", "temperature": 25}

        async def formatter(name: str, message: str, payload: Dict[str, Any], original: str) -> str:
            return message

        coordinator = ToolCoordinator(
            env_provider=env_provider,
            tool_lookup=lambda name: weather_handler if name == "weather_query" else None,
            formatter=formatter,
        )
        coordinator.register(
            ToolMetadata(
                name="weather_query",
                requires_env={"lat", "lon", "city"},
                enable_reformat=False,
            )
        )

        result = await coordinator.invoke(
            "weather_query",
            {},
            user_id="user-1",
            original_message="台北天氣",
        )

        assert captured["lat"] == 25.0
        assert captured["lon"] == 121.5
        assert captured["city"] == "Taipei"
        assert result.message == "晴時多雲"

    asyncio.run(_run())


def test_navigation_flow_auto_routes():
    async def _run():
        directions_calls = []

        async def env_provider(user_id: Optional[str]) -> Dict[str, Any]:
            return {"lat": 25.0, "lon": 121.5, "label": "現在位置"}

        async def geocode_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "success": True,
                "content": "找到目的地",
                "data": {"best_match": {"lat": 24.1, "lon": 120.9, "label": arguments.get("query")}},
            }

        async def directions_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
            directions_calls.append(arguments)
            return {"success": True, "content": "沿著高速公路前進"}

        async def formatter(name: str, message: str, payload: Dict[str, Any], original: str) -> str:
            return message

        def tool_lookup(name: str):
            if name == "forward_geocode":
                return geocode_handler
            if name == "directions":
                return directions_handler
            return None

        coordinator = ToolCoordinator(
            env_provider=env_provider,
            tool_lookup=tool_lookup,
            formatter=formatter,
        )
        coordinator.register(ToolMetadata(name="forward_geocode", flow="navigation"))
        coordinator.register(ToolMetadata(name="directions", enable_reformat=False))

        result = await coordinator.invoke(
            "forward_geocode",
            {"query": "桃園火車站"},
            user_id="tester",
            original_message="怎麼去桃園火車站",
        )

        assert result.name == "directions"
        assert directions_calls, "directions tool should be invoked"
        call_args = directions_calls[0]
        assert call_args["origin_label"] == "現在位置"
        assert call_args["dest_label"] == "桃園火車站"
        assert "沿著高速公路前進" in result.message

    asyncio.run(_run())
