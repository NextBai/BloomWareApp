---
name: mcp-tdx_parking
description: "Use when the user request matches the Bloom Ware MCP tool tdx_parking usage scenario."
tool_contract:
  name: "tdx_parking"
  category: "transportation"
  module: "features.mcp.tools.transportation.tdx_parking"
  class: "TDXParkingTool"
  description: "查詢附近停車場資訊和即時空位"
  examples:
    - "附近停車場"
    - "台北車站附近停車位"
    - "中正路100號附近停車場"
routing:
  invocation_mode: "local_mcp_bridge_function_calling"
  openai_hosted_mcp: "disabled_unless_remote_server_url_is_configured"
  required_action: "Select this tool only when the request maps to its category and required inputs can be extracted or safely derived from environment context. For precise addresses, landmarks, or intersections, fill location_query instead of forcing city."
safety:
  do_not_fabricate_missing_data: true
  preserve_tool_failure_semantics: true
  user_approval_required_for_high_impact_actions: true
---

Use this skill as the authoritative routing note for this Bloom Ware MCP tool.
The actual tool call must go through the local MCP bridge/function-calling path.
