import pytest

from features.mcp.tools.transportation.tdx_bus_arrival import TDXBusArrivalTool
from features.mcp.tools.transportation.tdx_parking import TDXParkingTool
from features.mcp.tools.transportation.tdx_youbike import TDXBikeTool


@pytest.mark.asyncio
async def test_youbike_nearby_queries_multiple_cities(monkeypatch):
    calls = []

    async def fake_call_api(endpoint, params, cache_ttl=1800):
        calls.append(endpoint)
        if "Bike/Station/City/Taipei" in endpoint:
            return [{"StationUID": "T1", "StationName": {"Zh_tw": "台北站"}, "StationPosition": {"PositionLat": 25.04, "PositionLon": 121.52}}]
        if "Bike/Station/City/NewTaipei" in endpoint:
            return [{"StationUID": "N1", "StationName": {"Zh_tw": "新北站"}, "StationPosition": {"PositionLat": 25.03, "PositionLon": 121.49}}]
        if "Bike/Availability/City/Taipei" in endpoint or "Bike/Availability/City/NewTaipei" in endpoint:
            return []
        return []

    monkeypatch.setattr("features.mcp.tools.transportation.tdx_youbike.TDXBaseAPI.call_api", fake_call_api)

    result = await TDXBikeTool._query_nearby_stations(25.04, 121.50, ["Taipei", "NewTaipei"], 500, 3)

    assert result["success"] is True
    assert "Bike/Station/City/Taipei" in calls
    assert "Bike/Station/City/NewTaipei" in calls


@pytest.mark.asyncio
async def test_bus_nearby_queries_multiple_cities(monkeypatch):
    calls = []

    async def fake_call_api(endpoint, params, cache_ttl=1800):
        calls.append(endpoint)
        return []

    monkeypatch.setattr("features.mcp.tools.transportation.tdx_bus_arrival.TDXBaseAPI.call_api", fake_call_api)

    result = await TDXBusArrivalTool._query_nearby_stops(25.04, 121.50, ["Taipei", "NewTaipei"], 3)

    assert result["success"] is True
    assert "Bus/Stop/City/Taipei" in calls
    assert "Bus/Stop/City/NewTaipei" in calls


@pytest.mark.asyncio
async def test_parking_nearby_uses_advanced_nearby_endpoint(monkeypatch):
    calls = []

    async def fake_call_api(endpoint, params, cache_ttl=3600, api_version="v2", api_family="basic"):
        calls.append((endpoint, api_version, api_family))
        return []

    monkeypatch.setattr("features.mcp.tools.transportation.tdx_parking.TDXBaseAPI.call_api", fake_call_api)

    result = await TDXParkingTool._query_nearby_parkings(25.04, 121.50, None, 1000, 3)

    assert result["success"] is True
    assert ("Parking/OffStreet/CarPark/NearBy", "v1", "advanced") in calls


@pytest.mark.asyncio
async def test_named_parking_uses_nearby_filter_instead_of_city_lookup(monkeypatch):
    async def fake_nearby(lat, lon, parking_type, radius_m, limit):
        return {
            "success": True,
            "content": "ok",
            "parkings": [
                {
                    "parking_name": "台北車站停車場",
                    "available_spaces": 12,
                    "total_spaces": 100,
                    "fee_info": "每小時 60 元",
                    "charge_station": False,
                    "walking_time_min": 3,
                    "distance_m": 220,
                }
            ],
        }

    monkeypatch.setattr(TDXParkingTool, "_query_nearby_parkings", fake_nearby)

    result = await TDXParkingTool._query_named_parking_nearby("台北車站", 25.04, 121.51, 1000, 5)

    assert result["success"] is True
    assert result["parking"]["parking_name"] == "台北車站停車場"
