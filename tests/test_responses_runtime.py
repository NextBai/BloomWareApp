from core.environment.context_builder import EnvironmentInjection
from core.responses_runtime import ResponsesAgentRuntime, ResponsesRuntimeRequest


def test_responses_runtime_builds_payload_with_environment_block():
    runtime = ResponsesAgentRuntime()

    payload = runtime.build_request_payload(
        ResponsesRuntimeRequest(
            user_input="今天台北天氣如何？",
            model="gpt-5.4",
            instructions="Use hosted tools first.",
            environment=EnvironmentInjection(
                summary_text="timezone: Asia/Taipei\ncity: Taipei",
                raw_context={"city": "Taipei"},
                metadata={"freshness": "latest_available"},
            ),
            tools=[{"type": "web_search"}],
            previous_response_id="resp_123",
        )
    )

    assert payload["model"] == "gpt-5.4"
    assert payload["instructions"] == "Use hosted tools first."
    assert payload["previous_response_id"] == "resp_123"
    assert payload["tools"] == [{"type": "web_search"}]
    assert payload["input"][0]["role"] == "system"
    assert "Latest environment context" in payload["input"][0]["content"][0]["text"]
    assert payload["input"][1]["role"] == "user"


def test_responses_runtime_converts_chat_messages_to_responses_payload():
    runtime = ResponsesAgentRuntime()

    payload = runtime.build_payload_from_messages(
        messages=[
            {"role": "system", "content": "System policy"},
            {"role": "user", "content": "Hello"},
        ],
        model="gpt-5.4",
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather.",
                    "parameters": {"type": "object", "properties": {}},
                    "strict": True,
                },
            }
        ],
        reasoning_effort="high",
        max_output_tokens=100,
    )

    assert payload["instructions"] == "System policy"
    assert payload["input"][0]["role"] == "user"
    assert payload["input"][0]["content"][0]["type"] == "input_text"
    assert payload["reasoning"] == {"effort": "high"}
    assert payload["max_output_tokens"] == 100
    assert payload["tools"] == [
        {
            "type": "function",
            "name": "get_weather",
            "description": "Get weather.",
            "parameters": {"type": "object", "properties": {}},
            "strict": True,
        }
    ]


def test_responses_runtime_converts_image_url_content_to_responses_input():
    runtime = ResponsesAgentRuntime()

    payload = runtime.build_payload_from_messages(
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Analyze image"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                ],
            }
        ],
        model="gpt-5.4",
    )

    assert payload["input"][0]["content"] == [
        {"type": "input_text", "text": "Analyze image"},
        {"type": "input_image", "image_url": "data:image/png;base64,abc"},
    ]


def test_responses_runtime_extracts_function_calls_from_output_items():
    class Item:
        type = "function_call"
        call_id = "call_1"
        name = "get_weather"
        arguments = '{"city":"Taipei"}'

    class Response:
        output = [Item()]

    calls = ResponsesAgentRuntime.extract_function_calls(Response())

    assert calls == [
        {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "get_weather",
                "arguments": '{"city":"Taipei"}',
            },
        }
    ]


def test_responses_runtime_can_strip_hosted_tools_for_retry():
    payload = {
        "model": "gpt-5.4",
        "input": [],
        "tools": [
            {"type": "web_search"},
            {"type": "mcp", "server_label": "remote", "server_url": "https://example.com/mcp"},
            {"type": "function", "name": "weather_query", "parameters": {"type": "object"}},
        ],
        "tool_choice": "auto",
    }

    stripped = ResponsesAgentRuntime.without_hosted_tools(payload)

    assert stripped["tools"] == [
        {"type": "function", "name": "weather_query", "parameters": {"type": "object"}},
    ]
    assert stripped["tool_choice"] == "auto"


def test_responses_runtime_removes_tool_choice_when_no_functions_left():
    payload = {
        "model": "gpt-5.4",
        "input": [],
        "tools": [{"type": "web_search"}],
        "tool_choice": "auto",
    }

    stripped = ResponsesAgentRuntime.without_hosted_tools(payload)

    assert stripped["tools"] == []
    assert "tool_choice" not in stripped
