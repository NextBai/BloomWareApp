import pytest

from features.mcp.tools.transportation.tdx_metro import TDXMetroTool


@pytest.mark.asyncio
async def test_metro_nearest_station_queries_multiple_operators(monkeypatch):
    calls = []

    async def fake_call_api(endpoint, params, cache_ttl=3600):
        calls.append(endpoint)
        if endpoint.endswith("/TRTC"):
            return [
                {
                    "StationUID": "TRTC-1",
                    "StationName": {"Zh_tw": "台北車站"},
                    "StationPosition": {"PositionLat": 25.0478, "PositionLon": 121.5170},
                    "StationAddress": "台北市中正區",
                }
            ]
        if endpoint.endswith("/NTMC"):
            return [
                {
                    "StationUID": "NTMC-1",
                    "StationName": {"Zh_tw": "頭前庄"},
                    "StationPosition": {"PositionLat": 25.0390, "PositionLon": 121.4602},
                    "StationAddress": "新北市新莊區",
                }
            ]
        return []

    monkeypatch.setattr(
        "features.mcp.tools.transportation.tdx_metro.TDXBaseAPI.call_api",
        fake_call_api,
    )

    result = await TDXMetroTool._query_nearest_station(25.04, 121.50, ["TRTC", "NTMC"])

    assert result["success"] is True
    assert "Rail/Metro/Station/TRTC" in calls
    assert "Rail/Metro/Station/NTMC" in calls
    assert len(result["stations"]) >= 1
