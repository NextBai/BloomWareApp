from pathlib import Path
import sys
import pytest

ROOT_DIR = Path(__file__).resolve().parents[4]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from features.mcp.tools.base_tool import ValidationError  # noqa: E402
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
