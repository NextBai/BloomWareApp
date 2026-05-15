import pytest

from features.mcp.mcp_client import MCPClient


def test_create_tool_from_data_preserves_output_schema():
    client = MCPClient("server", {"command": "noop"})

    tool = client._create_tool_from_data(
        {
            "name": "remote_tool",
            "description": "Remote tool",
            "inputSchema": {"type": "object", "properties": {}},
            "outputSchema": {
                "type": "object",
                "properties": {"success": {"type": "boolean"}},
                "required": ["success"],
            },
        }
    )

    assert tool is not None
    assert tool.outputSchema["properties"]["success"]["type"] == "boolean"


@pytest.mark.asyncio
async def test_call_tool_returns_structured_content(monkeypatch):
    client = MCPClient("server", {"command": "noop"})

    async def fake_send_request(method, params):
        return {
            "result": {
                "content": [{"type": "text", "text": "fallback text"}],
                "structuredContent": {
                    "success": True,
                    "value": "structured",
                },
            }
        }

    monkeypatch.setattr(client, "_send_request", fake_send_request)

    result = await client._call_tool("remote_tool", {})

    assert result == {
        "success": True,
        "value": "structured",
    }


@pytest.mark.asyncio
async def test_call_tool_preserves_error_semantics_with_structured_content(monkeypatch):
    client = MCPClient("server", {"command": "noop"})

    async def fake_send_request(method, params):
        return {
            "result": {
                "content": [{"type": "text", "text": "failed"}],
                "structuredContent": {
                    "error_code": "REMOTE_ERROR",
                },
                "isError": True,
            }
        }

    monkeypatch.setattr(client, "_send_request", fake_send_request)

    result = await client._call_tool("remote_tool", {})

    assert result == {
        "error_code": "REMOTE_ERROR",
        "success": False,
        "error": "failed",
    }
