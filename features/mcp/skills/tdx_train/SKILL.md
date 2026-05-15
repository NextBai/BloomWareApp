---
name: mcp-tdx_train
description: "Use when the user request matches the Bloom Ware MCP tool tdx_train usage scenario."
tool_contract:
  name: "tdx_train"
  category: "transportation"
  module: "features.mcp.tools.transportation.tdx_train"
  class: "TDXTrainTool"
  description: "查詢台鐵時刻表和即時資訊"
  examples:
    - "台鐵從台北到新竹"
    - "火車時刻表"
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
