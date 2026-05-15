import pytest

from core.emotion_care_manager import EmotionCareManager
from core.pipeline import ChatPipeline


async def noop_feature_processor(*args, **kwargs):
    return None


async def sad_text_intent(_message):
    return False, {"emotion": "sad"}


async def neutral_text_intent(_message):
    return False, {"emotion": "neutral"}


async def angry_text_intent(_message):
    return False, {"emotion": "angry"}


async def noop_ai_generator(*args, **kwargs):
    if kwargs.get("use_care_mode"):
        return "care"
    return "chat"


def build_pipeline(intent_detector):
    return ChatPipeline(
        intent_detector=intent_detector,
        feature_processor=noop_feature_processor,
        ai_generator=noop_ai_generator,
    )


@pytest.fixture(autouse=True)
def clear_care_state():
    EmotionCareManager._user_states.clear()
    yield
    EmotionCareManager._user_states.clear()


@pytest.mark.asyncio
async def test_voice_audio_extreme_does_not_enter_care_when_text_is_neutral():
    pipeline = build_pipeline(neutral_text_intent)

    result = await pipeline.process(
        "幫我查明天天氣",
        user_id="voice-user",
        chat_id="chat-1",
        audio_emotion={
            "success": True,
            "source": "realtime_voice",
            "emotion": "sad",
            "confidence": 0.93,
        },
    )

    assert result.text == "chat"
    assert result.meta["care_mode"] is False
    assert result.meta["emotion"] == "neutral"
    assert EmotionCareManager.is_in_care_mode("voice-user", "chat-1") is False


@pytest.mark.asyncio
async def test_voice_audio_extreme_enters_care_when_text_extreme_family_matches():
    pipeline = build_pipeline(sad_text_intent)

    result = await pipeline.process(
        "我真的撐不下去了",
        user_id="voice-user",
        chat_id="chat-1",
        audio_emotion={
            "success": True,
            "source": "realtime_voice",
            "emotion": "fear",
            "confidence": 0.93,
        },
    )

    assert result.meta["care_mode"] is True
    assert result.meta["emotion"] in {"sad", "fear"}
    assert EmotionCareManager.is_in_care_mode("voice-user", "chat-1") is True


@pytest.mark.asyncio
async def test_voice_audio_low_confidence_does_not_override_text_emotion():
    pipeline = build_pipeline(sad_text_intent)

    result = await pipeline.process(
        "我真的很難過",
        user_id="voice-user",
        chat_id="chat-1",
        audio_emotion={
            "success": True,
            "source": "realtime_voice",
            "emotion": "angry",
            "confidence": 0.42,
        },
    )

    assert result.meta["care_mode"] is True
    assert result.meta["emotion"] == "sad"


@pytest.mark.asyncio
async def test_text_only_extreme_emotion_still_enters_care():
    pipeline = build_pipeline(angry_text_intent)

    result = await pipeline.process(
        "我現在真的很生氣",
        user_id="text-user",
        chat_id="chat-1",
    )

    assert result.meta["care_mode"] is True
    assert result.meta["emotion"] == "angry"


@pytest.mark.asyncio
async def test_voice_low_speech_confidence_blocks_care_even_when_emotions_match():
    pipeline = build_pipeline(sad_text_intent)

    result = await pipeline.process(
        "我真的撐不下去了",
        user_id="voice-user",
        chat_id="chat-1",
        audio_emotion={
            "success": True,
            "source": "realtime_voice",
            "emotion": "sad",
            "confidence": 0.94,
            "speech_confidence": 0.41,
        },
    )

    assert result.text == "chat"
    assert result.meta["care_mode"] is False
    assert EmotionCareManager.is_in_care_mode("voice-user", "chat-1") is False


@pytest.mark.asyncio
async def test_voice_context_without_usable_audio_emotion_blocks_text_only_care():
    pipeline = build_pipeline(sad_text_intent)

    result = await pipeline.process(
        "我真的撐不下去了",
        user_id="voice-user",
        chat_id="chat-1",
        audio_emotion={
            "success": False,
            "source": "realtime_voice",
            "error": "LOW_AUDIO_CONFIDENCE",
        },
    )

    assert result.text == "chat"
    assert result.meta["care_mode"] is False
    assert EmotionCareManager.is_in_care_mode("voice-user", "chat-1") is False
