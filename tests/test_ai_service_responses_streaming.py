import pytest

from services import ai_service


class StreamEvent:
    def __init__(self, event_type, delta=None, text=None, item=None):
        self.type = event_type
        self.delta = delta
        self.text = text
        self.item = item


class StreamItem:
    def __init__(self, item_type):
        self.type = item_type


class Responses:
    def __init__(self):
        self.payload = None

    def create(self, **kwargs):
        self.payload = kwargs
        return [
            StreamEvent("response.output_item.added", item=StreamItem("web_search_call")),
            StreamEvent("response.output_text.delta", delta="你"),
            StreamEvent("response.output_text.delta", delta="好"),
            StreamEvent("response.output_text.done", text="你好"),
        ]


class Client:
    def __init__(self):
        self.responses = Responses()
        self.timeout = None

    def with_options(self, **kwargs):
        self.timeout = kwargs.get("timeout")
        return self


class FailingThenSafeResponses:
    def __init__(self):
        self.payloads = []

    def create(self, **kwargs):
        self.payloads.append(kwargs)
        if len(self.payloads) == 1:
            raise RuntimeError("503 Service Unavailable")

        class Response:
            output_text = "即時搜尋暫時不可用，無法可靠確認最新股價。請稍後再試。"

        return Response()


class FailingThenSafeClient(Client):
    def __init__(self):
        self.responses = FailingThenSafeResponses()
        self.timeout = None


class LanguageMismatchResponses:
    def __init__(self):
        self.payloads = []

    def create(self, **kwargs):
        self.payloads.append(kwargs)

        class Response:
            output_text = "我很好，謝謝你。"

        if len(self.payloads) == 1:
            return Response()

        class RetryResponse:
            output_text = "I am doing well, thank you."

        return RetryResponse()


class LanguageMismatchClient(Client):
    def __init__(self):
        self.responses = LanguageMismatchResponses()
        self.timeout = None


@pytest.mark.asyncio
async def test_generate_response_async_streams_responses_delta(monkeypatch):
    client = Client()
    chunks = []

    class Settings:
        OPENAI_MODEL = "gpt-5.4-mini"
        OPENAI_RESPONSES_TIMEOUT = 90
        OPENAI_USE_RESPONSES = True
        OPENAI_ENABLE_WEB_SEARCH = False
        OPENAI_ENABLE_REMOTE_MCP = False
        OPENAI_REMOTE_MCP_SERVERS_JSON = "[]"
        OPENAI_ENABLE_SKILLS = False

    async def on_chunk(delta):
        chunks.append(delta)

    monkeypatch.setattr(ai_service, "settings", Settings)
    monkeypatch.setattr(ai_service, "OPENAI_TIMEOUT", 30)
    monkeypatch.setattr(ai_service, "OPENAI_RESPONSES_TIMEOUT", 90)
    monkeypatch.setattr(ai_service, "_get_client", lambda: client)
    monkeypatch.setattr(ai_service, "_default_hosted_tools", lambda: [])

    result = await ai_service.generate_response_async(
        [{"role": "user", "content": "hi"}],
        model="gpt-5.4-mini",
        stream=True,
        on_chunk=on_chunk,
    )

    assert result == "你好"
    assert chunks == [
        {"type": "status", "status": "web_searching", "message": "正在搜尋最新資訊..."},
        "你",
        "好",
    ]
    assert client.responses.payload["stream"] is True
    assert client.timeout == 90


@pytest.mark.asyncio
async def test_generate_response_async_streaming_falls_back_without_hosted_tools(monkeypatch):
    client = FailingThenSafeClient()
    chunks = []

    class Settings:
        OPENAI_MODEL = "gpt-5.4-mini"
        OPENAI_RESPONSES_TIMEOUT = 90
        OPENAI_USE_RESPONSES = True
        OPENAI_ENABLE_WEB_SEARCH = True
        OPENAI_ENABLE_REMOTE_MCP = False
        OPENAI_REMOTE_MCP_SERVERS_JSON = "[]"
        OPENAI_ENABLE_SKILLS = False

    async def on_chunk(delta):
        chunks.append(delta)

    monkeypatch.setattr(ai_service, "settings", Settings)
    monkeypatch.setattr(ai_service, "OPENAI_TIMEOUT", 30)
    monkeypatch.setattr(ai_service, "OPENAI_RESPONSES_TIMEOUT", 90)
    monkeypatch.setattr(ai_service, "_get_client", lambda: client)
    monkeypatch.setattr(ai_service, "_default_hosted_tools", lambda: [{"type": "web_search"}])

    result = await ai_service.generate_response_async(
        [{"role": "user", "content": "今天台積電股價多少？"}],
        model="gpt-5.4-mini",
        stream=True,
        on_chunk=on_chunk,
    )

    assert "即時搜尋暫時不可用" in result
    assert len(client.responses.payloads) == 2
    assert client.responses.payloads[0]["tools"] == [{"type": "web_search"}]
    assert client.responses.payloads[0]["stream"] is True
    assert client.responses.payloads[1]["tools"] == []
    assert "stream" not in client.responses.payloads[1]
    assert "不得編造即時" in client.responses.payloads[1]["instructions"]
    assert chunks == [
        {
            "type": "status",
            "status": "hosted_tools_unavailable",
            "phase": "fallback",
            "message": "即時搜尋暫時不可用，正在改用安全降級回答...",
            "temporary": True,
        }
    ]


@pytest.mark.asyncio
async def test_consume_responses_stream_logs_delta_timing(monkeypatch):
    events = [
        StreamEvent("response.in_progress"),
        StreamEvent("response.output_text.delta", delta="你"),
        StreamEvent("response.output_text.delta", delta="好"),
    ]
    chunks = []
    log_messages = []

    async def on_chunk(delta):
        chunks.append(delta)

    class FakeLogger:
        def info(self, message, *args):
            log_messages.append(message % args if args else message)

    monkeypatch.setattr(ai_service, "logger", FakeLogger())

    result = await ai_service._consume_responses_stream(events, on_chunk)

    assert result == "你好"
    assert chunks == [
        {"type": "status", "status": "thinking", "message": "正在處理..."},
        "你",
        "好",
    ]
    assert any("Responses stream stats" in entry for entry in log_messages)


@pytest.mark.asyncio
async def test_generate_response_async_retries_when_response_language_mismatches(monkeypatch):
    client = LanguageMismatchClient()

    class Settings:
        OPENAI_MODEL = "gpt-5.4-mini"
        OPENAI_RESPONSES_TIMEOUT = 90
        OPENAI_USE_RESPONSES = True
        OPENAI_ENABLE_WEB_SEARCH = False
        OPENAI_ENABLE_REMOTE_MCP = False
        OPENAI_REMOTE_MCP_SERVERS_JSON = "[]"
        OPENAI_ENABLE_SKILLS = False

    monkeypatch.setattr(ai_service, "settings", Settings)
    monkeypatch.setattr(ai_service, "OPENAI_TIMEOUT", 30)
    monkeypatch.setattr(ai_service, "OPENAI_RESPONSES_TIMEOUT", 90)
    monkeypatch.setattr(ai_service, "_get_client", lambda: client)
    monkeypatch.setattr(ai_service, "_default_hosted_tools", lambda: [])

    result = await ai_service.generate_response_async(
        [
            {"role": "system", "content": "Reply in English."},
            {"role": "user", "content": "how are you"},
        ],
        model="gpt-5.4-mini",
        stream=False,
        expected_language="en-US",
    )

    assert result == "I am doing well, thank you."
    assert len(client.responses.payloads) == 2
    assert "Language correction" in client.responses.payloads[1]["instructions"]
