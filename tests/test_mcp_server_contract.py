import pytest

from features.mcp.server import FeaturesMCPServer
from features.mcp.types import Tool, ToolCallResult


@pytest.mark.asyncio
async def test_tools_list_includes_output_schema():
    server = FeaturesMCPServer()
    server.tools.clear()
    server.register_tool(
        Tool(
            name="example",
            description="Example tool",
            inputSchema={"type": "object", "properties": {}},
            outputSchema={
                "type": "object",
                "properties": {"success": {"type": "boolean"}},
                "required": ["success"],
            },
        )
    )

    result = await server._handle_tools_list({})

    assert result["tools"][0]["outputSchema"]["properties"]["success"]["type"] == "boolean"


@pytest.mark.asyncio
async def test_tools_call_preserves_structured_content():
    async def handler(arguments):
        return {
            "success": True,
            "content": "ok",
            "value": arguments["value"],
        }

    server = FeaturesMCPServer()
    server.tools.clear()
    server.register_tool(
        Tool(
            name="example",
            description="Example tool",
            inputSchema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
            handler=handler,
            outputSchema={
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "content": {"type": "string"},
                    "value": {"type": "string"},
                },
                "required": ["success", "content", "value"],
            },
        )
    )

    result = await server._handle_tools_call({"name": "example", "arguments": {"value": "42"}})

    assert result["content"] == [{"type": "text", "text": "ok"}]
    assert result["structuredContent"]["value"] == "42"
    assert result["isError"] is False


@pytest.mark.asyncio
async def test_tools_call_error_uses_safe_error_contract():
    async def handler(arguments):
        raise RuntimeError("secret internal detail")

    server = FeaturesMCPServer()
    server.tools.clear()
    server.register_tool(
        Tool(
            name="bad_tool",
            description="Bad tool",
            inputSchema={"type": "object", "properties": {}},
            handler=handler,
        )
    )

    result = await server._handle_tools_call({"name": "bad_tool", "arguments": {}})

    assert result["content"] == [{"type": "text", "text": "工具執行失敗"}]
    assert result["structuredContent"]["error_code"] == "TOOL_EXECUTION_ERROR"
    assert result["structuredContent"]["tool_name"] == "bad_tool"
    assert result["isError"] is True


@pytest.mark.asyncio
async def test_tools_call_rejects_output_schema_violation():
    async def handler(arguments):
        return {
            "success": True,
            "content": "ok",
        }

    server = FeaturesMCPServer()
    server.tools.clear()
    server.register_tool(
        Tool(
            name="bad_output",
            description="Bad output",
            inputSchema={"type": "object", "properties": {}},
            handler=handler,
            outputSchema={
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "content": {"type": "string"},
                    "value": {"type": "string"},
                },
                "required": ["success", "content", "value"],
            },
        )
    )

    result = await server._handle_tools_call({"name": "bad_output", "arguments": {}})

    assert result["content"] == [{"type": "text", "text": "工具輸出格式不符合契約"}]
    assert result["structuredContent"]["error_code"] == "TOOL_OUTPUT_VALIDATION"
    assert result["structuredContent"]["tool_name"] == "bad_output"
    assert result["isError"] is True


def test_tool_call_result_serializes_mcp_fields():
    result = ToolCallResult(
        content=[{"type": "text", "text": "ok"}],
        structuredContent={"success": True},
    )

    assert result.to_dict() == {
        "content": [{"type": "text", "text": "ok"}],
        "structuredContent": {"success": True},
        "isError": False,
    }
