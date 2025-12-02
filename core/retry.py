"""
API 重試機制
自動重試失敗的 API 調用，支援指數退避
"""

import asyncio
import functools
import random
from typing import Callable, TypeVar, Any, Optional, Tuple, Type

from core.logging import get_logger

logger = get_logger("core.retry")

T = TypeVar("T")

# 預設重試配置
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # 秒
DEFAULT_MAX_DELAY = 30.0  # 秒
DEFAULT_EXPONENTIAL_BASE = 2


class RetryConfig:
    """重試配置"""

    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        exponential_base: float = DEFAULT_EXPONENTIAL_BASE,
        jitter: bool = True,
        retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.retryable_exceptions = retryable_exceptions

    def calculate_delay(self, attempt: int) -> float:
        """計算重試延遲（指數退避 + 抖動）"""
        delay = self.base_delay * (self.exponential_base ** attempt)
        delay = min(delay, self.max_delay)

        if self.jitter:
            # 添加 ±25% 的隨機抖動
            jitter_range = delay * 0.25
            delay += random.uniform(-jitter_range, jitter_range)

        return max(0, delay)


async def retry_async(
    func: Callable[..., Any],
    *args,
    config: Optional[RetryConfig] = None,
    **kwargs,
) -> Any:
    """
    異步重試執行函數

    Args:
        func: 要執行的異步函數
        *args: 函數參數
        config: 重試配置
        **kwargs: 函數關鍵字參數

    Returns:
        函數執行結果

    Raises:
        最後一次重試的異常
    """
    if config is None:
        config = RetryConfig()

    last_exception = None

    for attempt in range(config.max_retries + 1):
        try:
            return await func(*args, **kwargs)

        except config.retryable_exceptions as e:
            last_exception = e

            if attempt < config.max_retries:
                delay = config.calculate_delay(attempt)
                logger.warning(
                    f"重試 {attempt + 1}/{config.max_retries}: "
                    f"{func.__name__} 失敗 ({type(e).__name__}: {e})，"
                    f"{delay:.2f}s 後重試"
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    f"重試耗盡: {func.__name__} 在 {config.max_retries} 次重試後仍失敗"
                )

    raise last_exception


def with_retry(
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
):
    """
    重試裝飾器

    用法：
        @with_retry(max_retries=3)
        async def my_api_call():
            ...
    """
    config = RetryConfig(
        max_retries=max_retries,
        base_delay=base_delay,
        retryable_exceptions=retryable_exceptions,
    )

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            return await retry_async(func, *args, config=config, **kwargs)

        return wrapper

    return decorator


# 預設配置實例
default_retry_config = RetryConfig()

# API 調用專用配置（較短延遲）
api_retry_config = RetryConfig(
    max_retries=2,
    base_delay=0.5,
    max_delay=5.0,
    retryable_exceptions=(ConnectionError, TimeoutError, OSError),
)

# 資料庫操作專用配置（較長延遲）
db_retry_config = RetryConfig(
    max_retries=3,
    base_delay=1.0,
    max_delay=10.0,
)
