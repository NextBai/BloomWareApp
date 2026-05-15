---
name: mcp-directions
description: "Use when the user request matches the Bloom Ware MCP tool directions usage scenario."
tool_contract:
  name: "directions"
  category: "location"
  module: "features.mcp.tools.location.directions_tool"
  class: "DirectionsTool"
  description: "規劃兩點之間的路線"
  examples:
    - "從這裡到台北車站怎麼走"
    - "幫我規劃路線"
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
