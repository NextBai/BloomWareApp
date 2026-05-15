import logging
import json

import pytest

from core import memory_system


@pytest.mark.asyncio
async def test_memory_manager_skips_ai_analysis_for_transient_market_query(monkeypatch):
    class FailingAnalyzer:
        async def analyze_conversation(self, *args, **kwargs):
            raise AssertionError("AI memory analysis should be skipped for transient queries")

    manager = memory_system.MemoryManager()
    manager.analyzer = FailingAnalyzer()

    monkeypatch.setattr(memory_system, "_get_memory_client", lambda: object())
    monkeypatch.setattr(memory_system, "db_available", False)

    result = await manager.process_conversation(
        user_id="u1",
        user_message="今天台積電股價收盤價多少？",
        assistant_response="查詢中。",
        conversation_history=[],
    )

    assert result["extracted_memories"] == 0
    assert result["saved_memories"] == 0
    assert result["errors"] == []


@pytest.mark.asyncio
async def test_memory_analyzer_quietly_degrades_on_transient_upstream_error(monkeypatch, caplog):
    class Responses:
        def create(self, **kwargs):
            raise Exception("Error code: 502 - {'error': {'message': 'Upstream request failed'}}")

    class Client:
        responses = Responses()

    class Settings:
        OPENAI_USE_RESPONSES = True
        GPT_INTENT_MODEL = "gpt-5.4"
        OPENAI_MODEL = "gpt-5.4"
        OPENAI_TIMEOUT = 30

    monkeypatch.setattr(memory_system, "_get_memory_client", lambda: Client())
    monkeypatch.setattr(memory_system, "settings", Settings)

    analyzer = memory_system.MemoryAnalyzer()

    with caplog.at_level(logging.ERROR):
        memories = await analyzer.analyze_conversation(
            user_message="我喜歡安靜的咖啡店",
            assistant_response="我記住了。",
            conversation_history=[],
        )

    assert memories == []
    assert "AI記憶分析時發生錯誤" not in caplog.text


def test_memory_analyzer_uses_structured_responses_payload(monkeypatch):
    captured = {}

    class Responses:
        def create(self, **kwargs):
            captured.update(kwargs)

            class Response:
                output_text = '{"memories":[]}'

                output = []

            return Response()

    class Client:
        responses = Responses()

    class Settings:
        OPENAI_USE_RESPONSES = True
        GPT_INTENT_MODEL = "gpt-5.4-mini"
        OPENAI_MODEL = "gpt-5.4-mini"

    monkeypatch.setattr(memory_system, "settings", Settings)

    analyzer = memory_system.MemoryAnalyzer()
    response = analyzer._create_analysis_response(
        Client(),
        [{"role": "system", "content": "JSON"}, {"role": "user", "content": "JSON"}],
        500,
    )

    assert response.output_text == '{"memories":[]}'
    assert captured["model"] == "gpt-5.4-mini"
    assert captured["max_output_tokens"] == 500
    assert captured["store"] is False
    assert captured["text"]["format"]["type"] == "json_schema"
    assert captured["text"]["format"]["strict"] is True
    assert captured["text"]["format"]["schema"]["required"] == ["memories"]
    assert "reasoning" not in captured


@pytest.mark.asyncio
async def test_memory_analyzer_retries_transient_upstream_error_then_succeeds(monkeypatch):
    calls = {"count": 0}

    class Responses:
        def create(self, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise Exception("502 upstream request failed")

            class Response:
                output_text = json.dumps(
                    {
                        "memories": [
                            {
                                "type": "preferences",
                                "content": "使用者喜歡安靜的咖啡店",
                                "importance": 0.8,
                            }
                        ]
                    },
                    ensure_ascii=False,
                )

                output = []

            return Response()

    class Client:
        responses = Responses()

    class Settings:
        OPENAI_USE_RESPONSES = True
        GPT_INTENT_MODEL = "gpt-5.4-mini"
        OPENAI_MODEL = "gpt-5.4-mini"
        OPENAI_TIMEOUT = 30

    monkeypatch.setattr(memory_system, "_get_memory_client", lambda: Client())
    monkeypatch.setattr(memory_system, "settings", Settings)
    monkeypatch.setattr(memory_system.MemoryAnalyzer, "_transient_backoff", staticmethod(lambda attempt: _noop()))

    analyzer = memory_system.MemoryAnalyzer()
    memories = await analyzer.analyze_conversation("我喜歡安靜的咖啡店", "我記住了。", [])

    assert calls["count"] == 2
    assert memories[0]["type"] == "preferences"
    assert memories[0]["source"] == "ai_analysis"


async def _noop():
    return None
