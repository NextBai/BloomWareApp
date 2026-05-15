import json
from unittest.mock import AsyncMock, patch

import pytest

from features.mcp.tools.environment.context_tool import EnvironmentContextTool


@pytest.mark.asyncio
async def test_environment_context_tool_requires_injected_user_id():
    tool = EnvironmentContextTool()

    result = await tool.execute({})

    assert result["success"] is False
    assert "_user_id" in result["error"]


@pytest.mark.asyncio
async def test_environment_context_tool_reads_real_user_context():
    tool = EnvironmentContextTool()
    fetcher = AsyncMock(
        return_value={
            "success": True,
            "context": {"city": "Taipei", "tz": "Asia/Taipei"},
        }
    )

    with patch("core.database.get_user_env_current", fetcher):
        result = await tool.execute({"_user_id": "user-1"})

    assert result["success"] is True
    assert result["data"] == {"city": "Taipei", "tz": "Asia/Taipei"}
    assert json.loads(result["content"]) == {"city": "Taipei", "tz": "Asia/Taipei"}
    fetcher.assert_awaited_once_with("user-1")
