import pytest

from features.mcp.tools.location.geocoding_tool import ForwardGeocodeTool


@pytest.mark.asyncio
async def test_forward_geocode_prefers_poi_match_for_station_queries(monkeypatch):
    async def fake_tdx(query):
        return [
            {
                "lat": 25.0487,
                "lon": 121.5143,
                "display_name": "市民大道台北地下街出口Y12西面",
                "label": "桃園機場捷運台北車站_A1",
                "importance": 1.0,
                "name": "桃園機場捷運台北車站_A1",
                "road": "",
                "house_number": "",
                "suburb": "",
                "city_district": "",
                "city": "",
                "admin": "",
                "postcode": "",
                "amenity": "",
                "shop": "",
                "building": "",
                "detailed_address": "市民大道台北地下街出口Y12西面",
                "_kind": "markname",
            },
            {
                "lat": 25.1424,
                "lon": 121.5066,
                "display_name": "台北市北投區開明里珠海路臨125之2號",
                "label": "台北市北投區開明里珠海路臨125之2號",
                "importance": 1.0,
                "name": "",
                "road": "",
                "house_number": "",
                "suburb": "",
                "city_district": "",
                "city": "",
                "admin": "",
                "postcode": "",
                "amenity": "",
                "shop": "",
                "building": "",
                "detailed_address": "台北市北投區開明里珠海路臨125之2號",
                "_kind": "address",
            },
        ]

    monkeypatch.setattr(ForwardGeocodeTool, "_forward_geocode_tdx", fake_tdx)

    result = await ForwardGeocodeTool.execute({"query": "台北車站", "limit": 1})

    assert "台北車站" in result["best_match"]["label"]
    assert result["best_match"]["lat"] == 25.0487
