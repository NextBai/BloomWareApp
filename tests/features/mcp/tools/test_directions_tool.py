import asyncio
from pathlib import Path
import sys

import pytest

ROOT_DIR = Path(__file__).resolve().parents[4]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from features.mcp.tools.base_tool import ValidationError  # noqa: E402
from features.mcp.tools import directions_tool  # noqa: E402
from features.mcp.tools.directions_tool import DirectionsTool  # noqa: E402


def test_validate_input_coerces_coordinates_with_noise():
    raw_args = {
        "origin_lat": "25.0478",
        "origin_lon": "121.5319",
        "dest_lat": "25.005 · placeholder",
        "dest_lon": "121.5001 附近",
    }

    validated = DirectionsTool.validate_input(raw_args)

    assert validated["origin_lat"] == pytest.approx(25.0478)
    assert validated["origin_lon"] == pytest.approx(121.5319)
    assert validated["dest_lat"] == pytest.approx(25.005)
    assert validated["dest_lon"] == pytest.approx(121.5001)
    assert validated["mode"] == "foot-walking"


def test_validate_input_missing_dest_lon_gives_clear_error():
    raw_args = {
        "origin_lat": 25.0478,
        "origin_lon": 121.5319,
        "dest_lat": 25.005,
    }

    with pytest.raises(ValidationError) as excinfo:
        DirectionsTool.validate_input(raw_args)

    message = str(excinfo.value)
    assert "dest_lon" in message
    assert "經度" in message


def test_execute_returns_labels_when_cache_hit(monkeypatch):
    monkeypatch.setattr(directions_tool, "ORS_API_KEY", "dummy-key", raising=False)

    async def fake_get_route_cached(_key: str):
        return {"distance_m": 1325.5, "duration_s": 780.0, "polyline": "[]"}

    async def fake_get_route_cache(_key: str):
        return None

    async def noop_set_route_cache(*_args, **_kwargs):
        return None

    monkeypatch.setattr(directions_tool.db_cache, "get_route_cached", fake_get_route_cached)
    monkeypatch.setattr(directions_tool, "get_route_cache", fake_get_route_cache)
    monkeypatch.setattr(directions_tool.db_cache, "set_route_cache", noop_set_route_cache)
    monkeypatch.setattr(directions_tool, "set_route_cache", noop_set_route_cache)

    args = {
        "origin_lat": 24.9915,
        "origin_lon": 121.3423,
        "dest_lat": 24.9891,
        "dest_lon": 121.3134,
        "origin_label": "測試起點 A",
        "dest_label": "測試目的地 B",
    }

    result = asyncio.run(DirectionsTool.execute(args))

    assert result["success"] is True
    assert "距離" in result["content"]
    assert result["origin_label"] == "測試起點 A"
    assert result["dest_label"] == "測試目的地 B"
    assert "distance_m" in result and "duration_s" in result
    # 確保沒有把 label 寫入快取的原始資料
    cached = asyncio.run(directions_tool.db_cache.get_route_cached("ignored"))  # type: ignore[arg-type]
    assert cached["distance_m"] == pytest.approx(1325.5)
    assert "origin_label" not in cached
