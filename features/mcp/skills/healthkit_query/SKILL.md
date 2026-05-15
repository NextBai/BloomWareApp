---
name: mcp-healthkit_query
description: "Use when the user request matches the Bloom Ware MCP tool healthkit_query usage scenario."
tool_contract:
  name: "healthkit_query"
  category: "utility"
  module: "features.mcp.tools.utility.healthkit_tool"
  class: "HealthKitTool"
  description: "查詢使用者健康資料（心率、步數、血氧、睡眠等）"
  examples:
    - "我今天走幾步"
    - "最近心率如何"
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
