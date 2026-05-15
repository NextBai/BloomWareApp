import json

from features.mcp.openai_tools import build_openai_hosted_tools
from features.mcp.openai_tools import DEFAULT_CONFIG_PATH


def test_default_config_path_points_to_project_mcp_config():
    assert DEFAULT_CONFIG_PATH.name == "mcp_config.json"
    assert DEFAULT_CONFIG_PATH.parent.name == "features"
    assert DEFAULT_CONFIG_PATH.exists()


class _Settings:
    OPENAI_ENABLE_WEB_SEARCH = True
    OPENAI_ENABLE_REMOTE_MCP = True
    OPENAI_REMOTE_MCP_SERVERS_JSON = "[]"
    OPENAI_ENABLE_SKILLS = True


def test_openai_hosted_tools_reads_project_mcp_config(tmp_path, monkeypatch):
    config_path = tmp_path / "mcp_config.json"
    config_path.write_text(
        json.dumps(
            {
                "openai_tools": {
                    "web_search": {"enabled": True},
                    "remote_mcp": {
                        "enabled": True,
                        "approval_default": "always",
                        "items": [
                            {
                                "enabled": True,
                                "server_label": "dmcp",
                                "server_url": "https://dmcp-server.deno.dev/sse",
                                "allowed_tools": ["roll"],
                            }
                        ],
                    },
                    "skills": {
                        "enabled": True,
                        "mode": "system_context",
                        "skills_root": "features/mcp/skills",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("features.mcp.openai_tools.settings", _Settings)

    specs = build_openai_hosted_tools(config_path)

    assert specs == [
        {"type": "web_search"},
        {
            "type": "mcp",
            "server_label": "dmcp",
            "server_url": "https://dmcp-server.deno.dev/sse",
            "allowed_tools": ["roll"],
            "require_approval": "always",
        }
    ]


def test_openai_hosted_tools_keeps_remote_mcp_and_skills_disabled_by_env(tmp_path, monkeypatch):
    class DisabledSettings(_Settings):
        OPENAI_ENABLE_REMOTE_MCP = False
        OPENAI_ENABLE_SKILLS = False

    config_path = tmp_path / "mcp_config.json"
    config_path.write_text(
        json.dumps(
            {
                "openai_tools": {
                    "web_search": {"enabled": True},
                    "remote_mcp": {
                        "enabled": True,
                        "items": [{"server_label": "dmcp", "server_url": "https://example.com/mcp"}],
                    },
                    "skills": {"enabled": True, "mode": "system_context"},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("features.mcp.openai_tools.settings", DisabledSettings)

    assert build_openai_hosted_tools(config_path) == [{"type": "web_search"}]


def test_openai_hosted_tools_skips_local_mcp_without_remote_url(tmp_path, monkeypatch):
    config_path = tmp_path / "mcp_config.json"
    config_path.write_text(
        json.dumps(
            {
                "openai_tools": {
                    "web_search": {"enabled": False},
                    "remote_mcp": {
                        "enabled": True,
                        "items": [{"enabled": True, "server_label": "local-features"}],
                    },
                    "skills": {"enabled": False},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("features.mcp.openai_tools.settings", _Settings)

    assert build_openai_hosted_tools(config_path) == []


def test_openai_hosted_tools_never_emits_executable_skill_adapter(tmp_path, monkeypatch):
    config_path = tmp_path / "mcp_config.json"
    config_path.write_text(
        json.dumps(
            {
                "openai_tools": {
                    "web_search": {"enabled": False},
                    "remote_mcp": {"enabled": False},
                    "skills": {"enabled": True, "mode": "system_context"},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("features.mcp.openai_tools.settings", _Settings)

    assert build_openai_hosted_tools(config_path) == []
