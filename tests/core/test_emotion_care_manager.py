import pytest

from core.emotion_care_manager import EmotionCareManager


@pytest.fixture(autouse=True)
def reset_care_states():
    EmotionCareManager._user_states.clear()  # type: ignore[attr-defined]
    yield
    EmotionCareManager._user_states.clear()  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "message",
    [
        "我沒事了",
        "我没事了",
        "沒關係了，謝謝你",
        "没关系了，谢谢你",
        "不用擔心",
        "不用担心我啦",
    ],
)
def test_check_release_supports_traditional_and_simplified(message):
    user_id = "user-1"
    chat_id = "chat-123"

    # 先手動讓用戶進入關懷模式
    EmotionCareManager._set_state(user_id, chat_id, {  # type: ignore[attr-defined]
        "in_care_mode": True,
        "emotion": "sad",
        "start_time": 0.0,
        "last_exit_time": 0.0,
    })

    assert EmotionCareManager.is_in_care_mode(user_id, chat_id) is True
    released = EmotionCareManager.check_release(user_id, message, chat_id)
    assert released is True
    assert EmotionCareManager.is_in_care_mode(user_id, chat_id) is False
