import pytest

from features.mcp.coordinator import ToolCoordinator, ToolOutputValidationError
from features.mcp.tool_models import ToolMetadata


async def empty_env(user_id):
    return {}


async def passthrough_formatter(tool_name, message, payload, original_message):
    return message


@pytest.mark.asyncio
async def test_coordinator_validates_output_schema_on_main_path():
    async def bad_handler(arguments):
        return {
            "success": True,
            "content": "ok",
        }

    coordinator = ToolCoordinator(
        env_provider=empty_env,
        tool_lookup=lambda name: bad_handler,
        formatter=passthrough_formatter,
        output_schema_provider=lambda name: {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "content": {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["success", "content", "value"],
        },
    )

    with pytest.raises(ToolOutputValidationError, match="輸出格式不符合契約"):
        await coordinator.invoke(
            "bad_tool",
            {},
            user_id="user1",
            original_message="test",
        )


@pytest.mark.asyncio
async def test_coordinator_accepts_valid_output_schema_on_main_path():
    async def good_handler(arguments):
        return {
            "success": True,
            "content": "ok",
            "value": "42",
        }

    coordinator = ToolCoordinator(
        env_provider=empty_env,
        tool_lookup=lambda name: good_handler,
        formatter=passthrough_formatter,
        output_schema_provider=lambda name: {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "content": {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["success", "content", "value"],
        },
    )

    result = await coordinator.invoke(
        "good_tool",
        {},
        user_id="user1",
        original_message="test",
    )

    assert result.message == "ok"
    assert result.data == {"value": "42"}


@pytest.mark.asyncio
async def test_coordinator_does_not_retry_output_schema_violation():
    calls = 0

    async def bad_handler(arguments):
        nonlocal calls
        calls += 1
        return {
            "success": True,
            "content": "ok",
        }

    coordinator = ToolCoordinator(
        env_provider=empty_env,
        tool_lookup=lambda name: bad_handler,
        formatter=passthrough_formatter,
        output_schema_provider=lambda name: {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "content": {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["success", "content", "value"],
        },
    )

    with pytest.raises(ToolOutputValidationError):
        await coordinator.invoke(
            "bad_tool",
            {},
            user_id="user1",
            original_message="test",
        )

    assert calls == 1


@pytest.mark.asyncio
async def test_coordinator_normalizes_city_from_env_fallback():
    captured_arguments = {}

    async def handler(arguments):
        captured_arguments.update(arguments)
        return {
            "success": True,
            "content": "ok",
            "value": "done",
        }

    async def env_provider(user_id):
        return {
            "detailed_address": "桃園市",
        }

    coordinator = ToolCoordinator(
        env_provider=env_provider,
        tool_lookup=lambda name: handler,
        formatter=passthrough_formatter,
        output_schema_provider=lambda name: {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "content": {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["success", "content", "value"],
        },
    )
    coordinator.register(
        ToolMetadata(
            name="tdx_youbike",
            requires_env={"city"},
            env_fallbacks={"city": ["detailed_address"]},
        )
    )

    await coordinator.invoke(
        "tdx_youbike",
        {},
        user_id="user1",
        original_message="最近的Ubike在哪裡",
    )

    assert captured_arguments["city"] == "桃園"


@pytest.mark.asyncio
async def test_coordinator_normalizes_city_from_label_fallback():
    captured_arguments = {}

    async def handler(arguments):
        captured_arguments.update(arguments)
        return {
            "success": True,
            "content": "ok",
            "value": "done",
        }

    async def env_provider(user_id):
        return {
            "label": "台中市",
        }

    coordinator = ToolCoordinator(
        env_provider=env_provider,
        tool_lookup=lambda name: handler,
        formatter=passthrough_formatter,
        output_schema_provider=lambda name: {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "content": {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["success", "content", "value"],
        },
    )
    coordinator.register(
        ToolMetadata(
            name="tdx_metro",
            requires_env={"city"},
            env_fallbacks={"city": ["label"]},
        )
    )

    await coordinator.invoke(
        "tdx_metro",
        {},
        user_id="user1",
        original_message="附近捷運在哪",
    )

    assert captured_arguments["city"] == "台中"
