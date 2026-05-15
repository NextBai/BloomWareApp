import base64

import pytest
from fastapi import WebSocketDisconnect

import app
from services.tts_service import TTSService, get_emotion_rate


def test_google_tts_voice_aliases_are_multilingual():
    service = TTSService()

    assert service._voice_config("coral") == {"languageCode": "cmn-TW", "name": "cmn-TW-Wavenet-A"}
    assert service._voice_config("ja-jp") == {"languageCode": "ja-JP", "name": "ja-JP-Neural2-B"}
    assert service._voice_config("vi-vn") == {"languageCode": "vi-VN", "name": "vi-VN-Wavenet-A"}


def test_google_tts_emotion_rate_is_conservative_for_care():
    assert get_emotion_rate("happy") > 1.0
    assert get_emotion_rate("sad") < 1.0
    assert get_emotion_rate("neutral", care_mode=True) < 1.0


@pytest.mark.asyncio
async def test_google_tts_requires_api_key():
    service = TTSService()
    service.api_key = ""

    result = await service.synthesize("你好")

    assert result["success"] is False
    assert "GOOGLE_TTS_API_KEY" in result["error"]


@pytest.mark.asyncio
async def test_google_tts_decodes_audio_content(monkeypatch):
    service = TTSService()
    service.api_key = "test-key"
    captured = {}

    class FakeResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def json(self, content_type=None):
            return {"audioContent": base64.b64encode(b"mp3").decode("ascii")}

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def post(self, url, params=None, json=None, timeout=None):
            captured["url"] = url
            captured["params"] = params
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr("services.tts_service.aiohttp.ClientSession", FakeSession)

    result = await service.synthesize("你好", voice="coral", emotion="happy")

    assert result["success"] is True
    assert result["audio_data"] == b"mp3"
    assert captured["params"] == {"key": "test-key"}
    assert captured["json"]["voice"]["languageCode"] == "cmn-TW"
    assert captured["json"]["audioConfig"]["speakingRate"] > 1.0


@pytest.mark.asyncio
async def test_tts_websocket_client_disconnect_is_not_treated_as_server_error(monkeypatch):
    events = []

    class FakeWebSocket:
        def __init__(self):
            self.closed = False
            self.send_count = 0

        async def accept(self):
            return None

        async def receive_json(self):
            return {
                "text": "你好",
                "voice": "nova",
                "language": "zh-TW",
                "persona": "xiaohua",
                "speaking_rate": 0.94,
            }

        async def send_json(self, payload):
            self.send_count += 1
            events.append(payload["type"])
            if payload["type"] == "tts_audio_chunk":
                raise WebSocketDisconnect()

        async def close(self):
            self.closed = True

    class FakeTTSService:
        async def streaming_synthesize(self, **kwargs):
            yield b"\x00\x01"

    monkeypatch.setattr(app, "logger", type("Logger", (), {
        "info": lambda *args, **kwargs: events.append("log:info"),
        "debug": lambda *args, **kwargs: events.append("log:debug"),
        "error": lambda *args, **kwargs: events.append("log:error"),
        "exception": lambda *args, **kwargs: events.append("log:exception"),
    })())

    import services.tts_service as tts_module
    monkeypatch.setattr(tts_module, "tts_service", FakeTTSService())

    websocket = FakeWebSocket()
    await app.tts_stream_websocket(websocket)

    assert events[:2] == ["tts_stream_start", "tts_audio_chunk"]
    assert "log:debug" in events
    assert "log:error" not in events
    assert "log:exception" not in events
    assert websocket.closed is True


@pytest.mark.asyncio
async def test_tts_websocket_logs_chunk_stats_before_client_disconnect(monkeypatch):
    events = []

    class FakeWebSocket:
        def __init__(self):
            self.closed = False

        async def accept(self):
            return None

        async def receive_json(self):
            return {
                "text": "你好",
                "voice": "nova",
                "language": "zh-TW",
                "persona": "xiaohua",
                "speaking_rate": 0.94,
            }

        async def send_json(self, payload):
            if payload["type"] == "tts_audio_chunk":
                raise WebSocketDisconnect()

        async def close(self):
            self.closed = True

    class FakeTTSService:
        async def streaming_synthesize(self, **kwargs):
            yield b"\x00\x01"

    monkeypatch.setattr(app, "logger", type("Logger", (), {
        "info": lambda self, message, *args, **kwargs: events.append(message % args if args else message),
        "debug": lambda self, message, *args, **kwargs: events.append(message % args if args else message),
        "error": lambda self, *args, **kwargs: None,
        "exception": lambda self, *args, **kwargs: None,
    })())

    import services.tts_service as tts_module
    monkeypatch.setattr(tts_module, "tts_service", FakeTTSService())

    websocket = FakeWebSocket()
    await app.tts_stream_websocket(websocket)

    assert any("chunks=1" in event for event in events)
    assert any("bytes=2" in event for event in events)
    assert websocket.closed is True
