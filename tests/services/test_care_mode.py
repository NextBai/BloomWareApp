import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.ai_service import _build_base_system_prompt, _compose_messages_with_context  # noqa: E402


def test_care_mode_prompt_emphasizes_personalised_empathy():
    prompt = _build_base_system_prompt(
        use_care_mode=True,
        care_emotion="sad",
        user_name="小明",
    )
    assert "第一句必須貼近用戶訊息中的核心事件或感受" in prompt
    assert "總字數不超過 60 字" in prompt
    assert "小明" in prompt


def test_compose_messages_includes_current_request_section():
    messages = _compose_messages_with_context(
        base_prompt="基礎提示",
        history_entries=[],
        memory_context="",
        env_context="",
        time_context="",
        emotion_context="",
        current_request="我覺得好沮喪",
        user_id="user-1",
        chat_id="chat-1",
        use_care_mode=True,
        care_emotion="sad",
    )

    assert len(messages) == 2
    system_content = messages[0]["content"]
    assert "【當前請求】" in system_content
    assert "我覺得好沮喪" in system_content

    payload = json.loads(messages[1]["content"])
    assert payload["care_mode"] is True
    assert payload["current_request"] == "我覺得好沮喪"
