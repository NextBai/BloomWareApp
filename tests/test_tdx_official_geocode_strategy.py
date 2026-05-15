from features.mcp.tools.location.geocode_tool import ReverseGeocodeTool


def test_reverse_geocode_output_schema_exposes_precision_fields():
    schema = ReverseGeocodeTool.get_output_schema()
    props = schema["properties"]
    assert "address_display" in props
    assert "precision" in props
    assert "poi_label" in props
