from datetime import datetime

from core.environment.context_builder import EnvironmentContextBuilder
from services.ai_service import _build_environment_context_text


def test_environment_context_builder_marks_missing_context():
    builder = EnvironmentContextBuilder()

    result = builder.build({}, now=datetime(2026, 5, 13, 12, 0, 0))

    assert result.metadata["freshness"] == "missing"
    assert "has_location: False" in result.summary_text


def test_environment_context_builder_includes_latest_location_fields():
    builder = EnvironmentContextBuilder()

    result = builder.build(
        {
            "lat": 25.033964,
            "lon": 121.564468,
            "detailed_address": "台北市信義區市府路45號",
            "address_display": "110台北市信義區市府路45號",
            "precision": "address",
            "poi_label": "台北101",
            "road": "市府路",
            "house_number": "45",
            "tz": "Asia/Taipei",
            "locale": "zh-TW",
            "heading_cardinal": "NE",
            "accuracy_m": 12,
        },
        now=datetime(2026, 5, 13, 12, 0, 0),
    )

    assert result.metadata["freshness"] == "latest_available"
    assert "detailed_address: 台北市信義區市府路45號" in result.summary_text
    assert "precision: address" in result.summary_text
    assert "poi_label: 台北101" in result.summary_text
    assert "road: 市府路" in result.summary_text
    assert "house_number: 45" in result.summary_text
    assert "timezone: Asia/Taipei" in result.summary_text
    assert "coordinates: 25.033964,121.564468" in result.summary_text


def test_ai_service_environment_context_text_uses_fixed_builder():
    text = _build_environment_context_text(
        {
            "lat": 25.033964,
            "lon": 121.564468,
            "detailed_address": "台北市信義區市府路45號",
            "address_display": "110台北市信義區市府路45號",
            "precision": "address",
            "poi_label": "台北101",
            "road": "市府路",
            "house_number": "45",
            "tz": "Asia/Taipei",
            "locale": "zh-TW",
        }
    )

    assert "snapshot_time_utc:" in text
    assert "has_location: True" in text
    assert "detailed_address: 台北市信義區市府路45號" in text
    assert "precision: address" in text
    assert "poi_label: 台北101" in text
    assert "readable_context:" in text
