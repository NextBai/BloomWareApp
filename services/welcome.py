from __future__ import annotations

from typing import Dict


def _greet_from_period(period: str) -> str:
    mapping = {
        "早晨": "早安",
        "上午": "早安",
        "中午": "午安",
        "下午": "下午好",
        "傍晚": "晚安",
        "晚上": "晚上好",
        "凌晨": "夜安",
        "深夜": "夜安",
    }
    return mapping.get(period, "您好")


def _mood_from_emotion_label(emo_label: str) -> str:
    if not emo_label:
        return "很高興再次見到你！"
    if "開心" in emo_label:
        return "您今天心情感覺不錯喔！"
    if "悲傷" in emo_label:
        return "今天心情有點低落，我在這陪你。"
    if "生氣" in emo_label:
        return "看起來有點不爽，想聊聊發生什麼事嗎？"
    if "恐懼" in emo_label:
        return "別擔心，有我在，慢慢來。"
    if "驚訝" in emo_label:
        return "哇，今天似乎有新鮮事！"
    if "中性" in emo_label:
        return "很高興再次見到你！"
    return "很高興再次見到你！"


def compose_welcome(user_name: str, time_data: Dict, emotion_label: str) -> str:
    name = user_name or "用戶"
    greet = _greet_from_period(str(time_data.get("day_period", "")))
    month = time_data.get("month")
    day = time_data.get("day")
    weekday = time_data.get("weekday_full_chinese", "")
    date_str = f"{month}月{day}號{weekday}"
    mood = _mood_from_emotion_label(str(emotion_label or ""))
    return f"{name}{greet}！今天是{date_str}，{mood}有什麼要與我分享呢？"


