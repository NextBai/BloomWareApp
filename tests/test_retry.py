"""
測試 core/retry.py 重試機制
"""

import pytest
import asyncio
from core.retry import (
    RetryConfig,
    retry_async,
    with_retry,
    default_retry_config,
    api_retry_config,
)


class TestRetryConfig:
    """測試重試配置"""

    def test_default_config(self):
        """測試預設配置"""
        config = RetryConfig()
        assert config.max_retries == 3
        assert config.base_delay == 1.0
        assert config.max_delay == 30.0

    def test_custom_config(self):
        """測試自訂配置"""
        config = RetryConfig(max_retries=5, base_delay=0.5)
        assert config.max_retries == 5
        assert config.base_delay == 0.5

    def test_calculate_delay(self):
        """測試延遲計算"""
        config = RetryConfig(base_delay=1.0, jitter=False)
        
        # 第一次重試
        delay0 = config.calculate_delay(0)
        assert delay0 == 1.0
        
        # 第二次重試（指數退避）
        delay1 = config.calculate_delay(1)
        assert delay1 == 2.0

    def test_max_delay_cap(self):
        """測試最大延遲上限"""
        config = RetryConfig(base_delay=10.0, max_delay=15.0, jitter=False)
        delay = config.calculate_delay(5)  # 10 * 2^5 = 320，應被限制
        assert delay == 15.0


class TestRetryAsync:
    """測試異步重試"""

    @pytest.mark.asyncio
    async def test_success_no_retry(self):
        """測試成功時不重試"""
        call_count = 0

        async def success_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = await retry_async(success_func)
        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_then_success(self):
        """測試重試後成功"""
        call_count = 0

        async def fail_then_success():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("temporary error")
            return "success"

        config = RetryConfig(max_retries=3, base_delay=0.01)
        result = await retry_async(fail_then_success, config=config)
        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_all_retries_fail(self):
        """測試所有重試都失敗"""
        call_count = 0

        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise ValueError("always fails")

        config = RetryConfig(max_retries=2, base_delay=0.01)
        
        with pytest.raises(ValueError):
            await retry_async(always_fail, config=config)
        
        assert call_count == 3  # 初始 + 2 次重試


class TestWithRetryDecorator:
    """測試重試裝飾器"""

    @pytest.mark.asyncio
    async def test_decorator_success(self):
        """測試裝飾器成功"""
        @with_retry(max_retries=2, base_delay=0.01)
        async def decorated_func():
            return "decorated"

        result = await decorated_func()
        assert result == "decorated"


class TestPredefinedConfigs:
    """測試預定義配置"""

    def test_default_config_exists(self):
        """測試預設配置存在"""
        assert default_retry_config is not None
        assert default_retry_config.max_retries == 3

    def test_api_config_exists(self):
        """測試 API 配置存在"""
        assert api_retry_config is not None
        assert api_retry_config.max_retries == 2
        assert api_retry_config.base_delay == 0.5
