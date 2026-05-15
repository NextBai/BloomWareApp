---
name: mcp-tdx_thsr
description: "Use when the user request matches the Bloom Ware MCP tool tdx_thsr usage scenario."
tool_contract:
  name: "tdx_thsr"
  category: "transportation"
  module: "features.mcp.tools.transportation.tdx_thsr"
  class: "TDXTHSRTool"
  description: "查詢高鐵時刻表、票價和即時資訊"
  examples:
    - "高鐵從台北到台中"
    - "高鐵票價查詢"
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
