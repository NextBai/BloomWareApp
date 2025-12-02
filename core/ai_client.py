"""
統一 OpenAI 客戶端管理
單一真理來源，避免重複初始化
"""

import logging
from typing import Optional

from core.config import settings
from core.logging import get_logger

logger = get_logger("core.ai_client")

# 全域 OpenAI 客戶端
_openai_client = None
_initialized = False


def get_openai_client():
    """
    取得 OpenAI 客戶端（單例模式）

    Returns:
        OpenAI 客戶端實例，若初始化失敗則返回 None
    """
    global _openai_client, _initialized

    if _initialized:
        return _openai_client

    try:
        from openai import OpenAI

        api_key = settings.OPENAI_API_KEY
        if not api_key:
            logger.error("❌ OpenAI API Key 未設定")
            _initialized = True
            return None

        _openai_client = OpenAI(
            api_key=api_key,
            timeout=float(settings.OPENAI_TIMEOUT),
            max_retries=3,
        )

        _initialized = True
        logger.info("✅ OpenAI 客戶端初始化成功")
        return _openai_client

    except ImportError:
        logger.error("❌ 無法導入 OpenAI SDK")
        _initialized = True
        return None

    except Exception as e:
        logger.error(f"❌ OpenAI 客戶端初始化失敗: {e}")
        _initialized = True
        return None


def reset_client() -> None:
    """
    重置客戶端（用於測試或重新初始化）
    """
    global _openai_client, _initialized
    _openai_client = None
    _initialized = False
    logger.info("OpenAI 客戶端已重置")


def is_available() -> bool:
    """
    檢查 OpenAI 服務是否可用

    Returns:
        True 如果客戶端已初始化且可用
    """
    client = get_openai_client()
    return client is not None


# 便捷別名
client = property(lambda self: get_openai_client())
