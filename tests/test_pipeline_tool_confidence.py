import pytest

from core.pipeline import ChatPipeline


async def noop_ai_generator(*args, **kwargs):
    return "chat"


async def forbidden_feature_processor(*args, **kwargs):
    raise AssertionError("feature processor must not be called when confidence is below threshold")


async def low_confidence_intent(_message):
    return True, {
        "type": "mcp_tool",
        "tool_name": "weather_query",
        "arguments": {"city": "Taipei"},
        "emotion": "neutral",
        "confidence": 0.89,
    }


async def high_confidence_intent(_message):
    return True, {
        "type": "mcp_tool",
        "tool_name": "weather_query",
        "arguments": {"city": "Taipei"},
        "emotion": "neutral",
        "confidence": 0.90,
    }


async def feature_processor(intent_data, user_id, original_message, chat_id):
    return {
        "message": "ok",
        "tool_name": intent_data["tool_name"],
        "tool_data": {"city": "Taipei"},
    }


def build_pipeline(intent_detector, processor):
    return ChatPipeline(
        intent_detector=intent_detector,
        feature_processor=processor,
        ai_generator=noop_ai_generator,
    )


@pytest.mark.asyncio
async def test_low_confidence_tool_call_is_blocked():
    pipeline = build_pipeline(low_confidence_intent, forbidden_feature_processor)

    result = await pipeline.process("天氣", "user1")

    assert result.reason == "tool-low-confidence"
    assert result.meta["tool_blocked"] is True
    assert result.meta["tool_confidence"] == 0.89
    assert "沒有可用工具" in result.text
    assert "地點" in result.text


@pytest.mark.asyncio
async def test_low_confidence_tool_message_matches_user_language():
    pipeline = build_pipeline(low_confidence_intent, forbidden_feature_processor)

    result = await pipeline.process("weather", "user1")

    assert result.reason == "tool-low-confidence"
    assert "No tool is available" in result.text
    assert "location" in result.text


@pytest.mark.asyncio
async def test_threshold_confidence_allows_tool_call():
    pipeline = build_pipeline(high_confidence_intent, feature_processor)

    result = await pipeline.process("台北天氣", "user1")

    assert result.text == "ok"
    assert result.meta["tool_name"] == "weather_query"
