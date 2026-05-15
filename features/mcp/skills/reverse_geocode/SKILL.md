---
name: mcp-reverse_geocode
description: "Use when the user request matches the Bloom Ware MCP tool reverse_geocode usage scenario."
tool_contract:
  name: "reverse_geocode"
  category: "location"
  module: "features.mcp.tools.location.geocode_tool"
  class: "ReverseGeocodeTool"
  description: "將座標轉換成地址、城市與行政區"
  examples:
    - "我在哪裡"
    - "這個座標是哪裡"
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
