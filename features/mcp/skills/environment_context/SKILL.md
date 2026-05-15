---
name: mcp-environment_context
description: "Use when the user request matches the Bloom Ware MCP tool environment_context usage scenario."
tool_contract:
  name: "environment_context"
  category: "environment"
  module: "features.mcp.tools.environment.context_tool"
  class: "EnvironmentContextTool"
  description: "取得使用者目前環境感知資料（位置、時區、語言、裝置、活動狀態）"
  examples:
    - "我現在在哪"
    - "目前環境資訊"
routing:
  invocation_mode: "local_mcp_bridge_function_calling"
  openai_hosted_mcp: "disabled_unless_remote_server_url_is_configured"
  required_action: "Select this tool only when the request maps to its category and required inputs can be extracted or safely derived from environment context."
safety:
  do_not_fabricate_missing_data: true
  preserve_tool_failure_semantics: true
  user_approval_required_for_high_impact_actions: true
---

Use this skill as the authoritative routing note for this Bloom Ware MCP tool.
The actual tool call must go through the local MCP bridge/function-calling path.
