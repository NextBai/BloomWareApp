"""
Prompt 模板管理
統一管理 AI 系統提示詞，支援動態組合
"""

from .intent_detection import get_intent_prompt, TOOL_RULES
from .care_mode import CARE_MODE_PROMPT

__all__ = [
    "get_intent_prompt",
    "TOOL_RULES",
    "CARE_MODE_PROMPT",
]
