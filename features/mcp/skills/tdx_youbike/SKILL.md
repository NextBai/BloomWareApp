---
name: mcp-tdx_youbike
description: "Use when the user request matches the Bloom Ware MCP tool tdx_youbike usage scenario."
tool_contract:
  name: "tdx_youbike"
  category: "transportation"
  module: "features.mcp.tools.transportation.tdx_youbike"
  class: "TDXBikeTool"
  description: "查詢 YouBike 站點資訊和即時車輛數量"
  examples:
    - "附近 YouBike"
    - "捷運站 YouBike 數量"
    - "桃園火車站附近的 YouBike"
routing:
  invocation_mode: "local_mcp_bridge_function_calling"
  openai_hosted_mcp: "disabled_unless_remote_server_url_is_configured"
  required_action: "Select this tool only when the request maps to its category and required inputs can be extracted or safely derived from environment context. For precise addresses, landmarks, intersections, or station areas, fill location_query instead of forcing city."
safety:
  do_not_fabricate_missing_data: true
  preserve_tool_failure_semantics: true
  user_approval_required_for_high_impact_actions: true
---

Use this skill as the authoritative routing note for this Bloom Ware MCP tool.
The actual tool call must go through the local MCP bridge/function-calling path.
