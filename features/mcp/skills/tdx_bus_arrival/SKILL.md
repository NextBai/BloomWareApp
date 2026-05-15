---
name: mcp-tdx_bus_arrival
description: "Use when the user request matches the Bloom Ware MCP tool tdx_bus_arrival usage scenario."
tool_contract:
  name: "tdx_bus_arrival"
  category: "transportation"
  module: "features.mcp.tools.transportation.tdx_bus_arrival"
  class: "TDXBusArrivalTool"
  description: "查詢公車即時到站時間（自動感知用戶位置，找最近站點）"
  examples:
    - "307 公車還要多久"
    - "附近有什麼公車"
    - "桃園火車站附近公車"
routing:
  invocation_mode: "local_mcp_bridge_function_calling"
  openai_hosted_mcp: "disabled_unless_remote_server_url_is_configured"
  required_action: "Select this tool only when the request maps to its category and required inputs can be extracted or safely derived from environment context. For precise stop areas, landmarks, roads, or intersections, fill location_query."
safety:
  do_not_fabricate_missing_data: true
  preserve_tool_failure_semantics: true
  user_approval_required_for_high_impact_actions: true
---

Use this skill as the authoritative routing note for this Bloom Ware MCP tool.
The actual tool call must go through the local MCP bridge/function-calling path.
