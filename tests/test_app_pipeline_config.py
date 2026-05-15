from pathlib import Path


def test_app_detect_timeout_keeps_agent_tool_judgement_room():
    source = Path("app.py").read_text(encoding="utf-8")

    assert "detect_timeout=25.0" in source


def test_app_ai_timeout_allows_hosted_tool_streaming():
    source = Path("app.py").read_text(encoding="utf-8")

    assert "ai_timeout=60.0" in source


def test_app_has_resolved_language_helper_for_agent_response_text():
    source = Path("app.py").read_text(encoding="utf-8")

    assert "def _resolve_conversation_language(" in source
    assert "_preferred_language_from_text(res.text)" in source


def test_app_passes_user_message_language_into_handle_message():
    source = Path("app.py").read_text(encoding="utf-8")

    assert 'message_language = message_data.get("language") or "auto"' in source
    assert "handle_message(user_message, user_id, chat_id, messages_for_handler, request_id=request_id, language=message_language, emotion_callback=_on_text_emotion)" in source
