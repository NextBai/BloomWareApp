import pytest

from features.mcp.tools.transportation.tdx_youbike import TDXBikeTool


@pytest.mark.asyncio
async def test_youbike_nearby_supports_location_query(monkeypatch):
    async def fake_location_context(**kwargs):
        assert kwargs["location_query"] == "桃園火車站"
        return {
            "lat": 24.989,
            "lon": 121.314,
            "city_code": "Taoyuan",
            "geo": {"city": "桃園市", "label": "桃園火車站"},
            "geocode_match": {"label": "桃園火車站"},
        }

    async def fake_nearby(lat, lon, cities, radius_m, limit):
        assert lat == 24.989
        assert lon == 121.314
        assert cities[0] == "Taoyuan"
        assert "Taipei" in cities
        return {
            "success": True,
            "content": "ok",
            "stations": [],
        }

    monkeypatch.setattr(
        "features.mcp.tools.transportation.tdx_youbike.resolve_location_context",
        fake_location_context,
    )
    monkeypatch.setattr(TDXBikeTool, "_query_nearby_stations", fake_nearby)

    result = await TDXBikeTool.execute(
        {
            "location_query": "桃園火車站",
            "radius_m": 300,
            "limit": 3,
        }
    )

    assert result["success"] is True
    assert result["stations"] == []
