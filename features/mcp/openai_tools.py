from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.config import settings
from core.logging import get_logger

logger = get_logger("mcp.openai_tools")

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "mcp_config.json"


def _load_mcp_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    path = config_path or DEFAULT_CONFIG_PATH
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("MCP 配置不存在: %s", path)
    except json.JSONDecodeError as exc:
        logger.warning("MCP 配置 JSON 無效: %s", exc)
    return {}


def _configured_items(section: Dict[str, Any]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for item in section.get("items", []):
        if isinstance(item, dict) and item.get("enabled", True):
            items.append({key: value for key, value in item.items() if key != "enabled"})
    return items


def _configured_remote_mcp_items(section: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = []
    for item in _configured_items(section):
        if item.get("server_url") or item.get("connector_id"):
            items.append(item)
        else:
            logger.info("跳過沒有 server_url/connector_id 的 hosted MCP 設定: %s", item.get("server_label"))
    return items


def _env_json_list(raw: str, *, label: str) -> List[Dict[str, Any]]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("%s 不是合法 JSON，已忽略: %s", label, exc)
        return []
    if not isinstance(parsed, list):
        logger.warning("%s 必須是 list，已忽略", label)
        return []
    return [item for item in parsed if isinstance(item, dict)]


def build_openai_hosted_tools(config_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    config = _load_mcp_config(config_path)
    openai_tools = config.get("openai_tools", {})
    specs: List[Dict[str, Any]] = []

    web_search = openai_tools.get("web_search", {})
    if settings.OPENAI_ENABLE_WEB_SEARCH and web_search.get("enabled", True):
        specs.append({"type": "web_search"})

    remote_mcp = openai_tools.get("remote_mcp", {})
    if settings.OPENAI_ENABLE_REMOTE_MCP and remote_mcp.get("enabled", False):
        for server in _configured_remote_mcp_items(remote_mcp) + _configured_remote_mcp_items(
            {"items": _env_json_list(
                settings.OPENAI_REMOTE_MCP_SERVERS_JSON,
                label="OPENAI_REMOTE_MCP_SERVERS_JSON",
            )}
        ):
            spec = dict(server)
            spec["type"] = "mcp"
            spec.setdefault("require_approval", remote_mcp.get("approval_default", "always"))
            specs.append(spec)

    return specs
