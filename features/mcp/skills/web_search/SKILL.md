---
name: hosted-web-search
description: "Use when the user asks for current, recent, time-sensitive, public, or externally verifiable information and OpenAI hosted web_search is enabled."
tool_contract:
  name: "web_search"
  category: "hosted_openai_tool"
  invocation_mode: "responses_hosted_tool_auto"
  description: "OpenAI hosted web_search for current public information."
usage_policy:
  decide_need_from_request: true
  use_environment_context: true
  use_time_context: true
  avoid_domain_specific_hardcoding: true
  do_not_invent_missing_facts: true
  cite_or_describe_source_time_when_available: true
---

# Hosted Web Search

Use `web_search` when the answer depends on information that may have changed after the model's knowledge cutoff or depends on the user's current time, location, market/session state, availability, price, schedule, law, weather, news, or other public facts.

Before answering, compare the user's wording with the available time and environment context. Decide whether the retrieved information is current enough for the question. If results are older than the requested time frame, reason from the context instead of treating it as a tool failure: explain what is known, what remains uncertain, and why.

If the user asks for "today", "now", "latest", "current", "closing", "real-time", or equivalent wording, compare source timestamps against the current time context. If the source timestamp is earlier than the requested time frame, do not present it as today's/current result. Label it as the latest source timestamp you found, then explain the likely timing or availability limitation using only general reasoning from time/environment/source context.

Do not hardcode domain-specific behavior. Do not force a specific market, source, company, route, or conclusion unless the user supplied it or the sources clearly establish it. If multiple interpretations are plausible, state the interpretation used and how to ask for another one.

When results are insufficient, stale, conflicting, or unavailable, say so plainly and avoid fabricating exact values. You may still provide the closest verified information as reference if you label its timestamp and uncertainty.
