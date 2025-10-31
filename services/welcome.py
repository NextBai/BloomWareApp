from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:  # pragma: no cover - zoneinfo may不可用
    ZoneInfo = None  # type: ignore


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


def _derive_period_from_hour(hour: int) -> str:
    if 5 <= hour < 9:
        return "早晨"
    if 9 <= hour < 12:
        return "上午"
    if 12 <= hour < 14:
        return "中午"
    if 14 <= hour < 18:
        return "下午"
    if 18 <= hour < 20:
        return "傍晚"
    if 20 <= hour < 23:
        return "晚上"
    if 23 <= hour or hour < 2:
        return "深夜"
    return "凌晨"


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


def compose_welcome(
    user_name: str,
    time_data: Dict,
    emotion_label: str,
    timezone: Optional[str] = None,
) -> str:
    name = user_name or "用戶"
    dt: Optional[datetime] = None

    if timezone and ZoneInfo:
        try:
            dt = datetime.now(ZoneInfo(timezone))
        except Exception:
            dt = None

    if dt is None:
        dt = datetime.now()

    day_period = _derive_period_from_hour(dt.hour)
    greet = _greet_from_period(day_period)

    month = dt.month
    day = dt.day
    weekday_list = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    weekday = weekday_list[dt.weekday()]

    date_str = f"{month}月{day}號{weekday}"
    mood = _mood_from_emotion_label(str(emotion_label or ""))
    return f"{name}{greet}！今天是{date_str}，{mood}有什麼要與我分享呢？"

