from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List

import json

SKILLS_ROOT = Path(__file__).resolve().parent / "skills"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "mcp_config.json"


def _load_mcp_config(config_path: Path = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def _slug(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in name).strip("-").lower()


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    text = str(value).replace('"', '\\"')
    return f'"{text}"'


def _yaml_list(values: Iterable[Any], indent: int = 2) -> str:
    prefix = " " * indent
    items = list(values)
    if not items:
        return f"{prefix}[]"
    return "\n".join(f"{prefix}- {_yaml_scalar(item)}" for item in items)


def tool_skill_path(tool_name: str) -> Path:
    return SKILLS_ROOT / _slug(tool_name) / "SKILL.md"


def render_tool_skill(tool_name: str, tool_info: Dict[str, Any]) -> str:
    examples = tool_info.get("examples") or []
    return "\n".join(
        [
            "---",
            f"name: mcp-{tool_name}",
            f"description: { _yaml_scalar('Use when the user request matches the Bloom Ware MCP tool ' + tool_name + ' usage scenario.') }",
            "tool_contract:",
            f"  name: {_yaml_scalar(tool_name)}",
            f"  category: {_yaml_scalar(tool_info.get('category', 'general'))}",
            f"  module: {_yaml_scalar(tool_info.get('module', ''))}",
            f"  class: {_yaml_scalar(tool_info.get('class', ''))}",
            f"  description: {_yaml_scalar(tool_info.get('description', ''))}",
            "  examples:",
            _yaml_list(examples, indent=4),
            "routing:",
            "  invocation_mode: \"local_mcp_bridge_function_calling\"",
            "  openai_hosted_mcp: \"disabled_unless_remote_server_url_is_configured\"",
            "  required_action: \"Select this tool only when the request maps to its category and required inputs can be extracted or safely derived from environment context.\"",
            "safety:",
            "  do_not_fabricate_missing_data: true",
            "  preserve_tool_failure_semantics: true",
            "  user_approval_required_for_high_impact_actions: true",
            "---",
            "",
            "Use this skill as the authoritative routing note for this Bloom Ware MCP tool.",
            "The actual tool call must go through the local MCP bridge/function-calling path.",
            "",
        ]
    )


def write_tool_skills(config_path: Path = DEFAULT_CONFIG_PATH) -> List[Path]:
    config = _load_mcp_config(config_path)
    written: List[Path] = []
    for tool_name, tool_info in sorted((config.get("tools") or {}).items()):
        if not (tool_info.get("module") and tool_info.get("class")):
            continue
        path = tool_skill_path(tool_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_tool_skill(tool_name, tool_info), encoding="utf-8")
        written.append(path)
    return written


def skills_prompt_block(config_path: Path = DEFAULT_CONFIG_PATH) -> str:
    config = _load_mcp_config(config_path)
    lines = [
        "Bloom Ware tool skills:",
        "Use these routing notes when selecting local MCP bridge tools or OpenAI hosted tools. Do not call hosted MCP for local tools unless a remote server_url is configured.",
        "- web_search: category=hosted_openai_tool; use_when=current, recent, time-sensitive, public, or externally verifiable information is needed; call_via=responses_hosted_tool_auto; read_skill=features/mcp/skills/web_search/SKILL.md; rule=use time/environment context and source timestamps to decide, without domain-specific hardcoding",
    ]
    for tool_name, tool_info in sorted((config.get("tools") or {}).items()):
        if not (tool_info.get("module") and tool_info.get("class")):
            continue
        examples = ", ".join(tool_info.get("examples") or [])
        lines.append(
            f"- {tool_name}: category={tool_info.get('category', 'general')}; "
            f"use_when={tool_info.get('description', '')}; examples={examples}; "
            f"call_via=local_function_calling_tool_schema"
        )
    return "\n".join(lines)
