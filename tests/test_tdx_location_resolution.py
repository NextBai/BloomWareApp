import pytest

from features.mcp.tools.transportation import tdx_location


def test_resolve_city_code_normalizes_city_suffix():
    assert tdx_location.resolve_city_code("桃園市") == "Taoyuan"
    assert tdx_location.resolve_city_code("臺中市") == "Taichung"


def test_resolve_metro_operator_from_city():
    assert tdx_location.resolve_metro_operator("高雄市") == "KRTC"
    assert tdx_location.resolve_metro_operator("桃園") == "TYMC"


def test_resolve_city_candidates_include_neighbors():
    candidates = tdx_location.resolve_city_candidates(
        city_like="新北市",
        geo_city="新北市",
        geo_admin="新北市",
        allowed_city_codes={"Taipei", "NewTaipei", "Taoyuan", "Keelung"},
    )
    assert candidates[0] == "NewTaipei"
    assert "Taipei" in candidates


def test_resolve_metro_operator_candidates_cover_taipei_living_circle():
    candidates = tdx_location.resolve_metro_operator_candidates(
        city_like="新北市",
        geo_city="新北市",
        geo_admin="新北市",
    )
    assert candidates == ["TRTC", "NTMC"]


@pytest.mark.asyncio
async def test_resolve_location_context_uses_location_query_when_coordinates_missing(monkeypatch):
    async def fake_resolve_coordinates(*, lat, lon, location_query):
        assert location_query == "桃園火車站"
        return 24.989, 121.314, {"label": "桃園火車站"}

    async def fake_resolve_geo_context(*, lat, lon):
        assert lat == 24.989
        assert lon == 121.314
        return {
            "city": "桃園市",
            "admin": "桃園市",
            "label": "桃園火車站",
            "detailed_address": "桃園火車站",
            "city_code": "Taoyuan",
            "metro_operator": "TYMC",
        }

    monkeypatch.setattr(tdx_location, "resolve_coordinates", fake_resolve_coordinates)
    monkeypatch.setattr(tdx_location, "resolve_geo_context", fake_resolve_geo_context)

    ctx = await tdx_location.resolve_location_context(
        lat=None,
        lon=None,
        location_query="桃園火車站",
        city_like=None,
        allowed_city_codes={"Taoyuan", "Taipei"},
    )

    assert ctx["lat"] == 24.989
    assert ctx["lon"] == 121.314
    assert ctx["city_code"] == "Taoyuan"
    assert ctx["geo"]["label"] == "桃園火車站"
