from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.environment.context_builder import EnvironmentInjection


@dataclass
class ResponsesRuntimeRequest:
    user_input: str
    model: str
    instructions: Optional[str] = None
    environment: Optional[EnvironmentInjection] = None
    tools: List[Dict[str, Any]] = field(default_factory=list)
    input_items: Optional[List[Dict[str, Any]]] = None
    previous_response_id: Optional[str] = None
    reasoning_effort: Optional[str] = None
    max_output_tokens: Optional[int] = None
    text_format: Optional[Dict[str, Any]] = None
    tool_choice: Any = "auto"


class ResponsesAgentRuntime:
    """
    新版主 Agent runtime 骨架。

    目前先負責：
    1. 統一組裝 Responses API payload
    2. 固定附帶 environment injection
    3. 為 hosted tools / bridge tools 預留同一個組裝入口
    """

    def build_request_payload(self, request: ResponsesRuntimeRequest) -> Dict[str, Any]:
        input_parts: List[Dict[str, Any]] = list(request.input_items or [])

        if request.environment:
            input_parts.insert(
                0,
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Latest environment context:\n" + request.environment.summary_text,
                        }
                    ],
                }
            )

        input_parts.append(
            self.message_to_input_item({"role": "user", "content": request.user_input})
        )

        payload: Dict[str, Any] = {
            "model": request.model,
            "input": input_parts,
            "tools": self.normalize_tools_for_responses(request.tools),
        }

        if request.instructions:
            payload["instructions"] = request.instructions
        if request.previous_response_id:
            payload["previous_response_id"] = request.previous_response_id
        if request.reasoning_effort:
            payload["reasoning"] = {"effort": request.reasoning_effort}
        if request.max_output_tokens:
            payload["max_output_tokens"] = request.max_output_tokens
        if request.text_format:
            payload["text"] = {"format": request.text_format}
        if request.tools:
            payload["tool_choice"] = request.tool_choice

        return payload

    def build_payload_from_messages(
        self,
        *,
        messages: List[Dict[str, Any]],
        model: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        reasoning_effort: Optional[str] = None,
        max_output_tokens: Optional[int] = None,
        tool_choice: Any = "auto",
        text_format: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        input_items: List[Dict[str, Any]] = []
        instructions: Optional[str] = None

        for message in messages:
            if message.get("role") == "system":
                content = message.get("content") or ""
                instructions = f"{instructions}\n\n{content}" if instructions else str(content)
                continue
            input_items.append(self.message_to_input_item(message))

        payload: Dict[str, Any] = {
            "model": model,
            "input": input_items,
            "tools": self.normalize_tools_for_responses(tools or []),
        }
        if instructions:
            payload["instructions"] = instructions
        if reasoning_effort:
            payload["reasoning"] = {"effort": reasoning_effort}
        if max_output_tokens:
            payload["max_output_tokens"] = max_output_tokens
        if text_format:
            payload["text"] = {"format": text_format}
        if tools:
            payload["tool_choice"] = tool_choice
        return payload

    @staticmethod
    def without_hosted_tools(payload: Dict[str, Any]) -> Dict[str, Any]:
        stripped = dict(payload)
        tools = [
            tool for tool in stripped.get("tools", [])
            if tool.get("type") == "function"
        ]
        stripped["tools"] = tools
        if not tools:
            stripped.pop("tool_choice", None)
        return stripped

    @staticmethod
    def message_to_input_item(message: Dict[str, Any]) -> Dict[str, Any]:
        role = message.get("role") or "user"
        content = message.get("content") or ""
        if isinstance(content, list):
            return {"role": role, "content": [ResponsesAgentRuntime.normalize_content_part(part, role) for part in content]}
        content_type = "output_text" if role == "assistant" else "input_text"
        return {"role": role, "content": [{"type": content_type, "text": str(content)}]}

    @staticmethod
    def normalize_content_part(part: Dict[str, Any], role: str) -> Dict[str, Any]:
        part_type = part.get("type")
        if part_type == "text":
            return {
                "type": "output_text" if role == "assistant" else "input_text",
                "text": str(part.get("text", "")),
            }
        if part_type == "image_url":
            image_url = part.get("image_url") or {}
            return {
                "type": "input_image",
                "image_url": image_url.get("url", image_url if isinstance(image_url, str) else ""),
            }
        return dict(part)

    @staticmethod
    def normalize_tools_for_responses(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for tool in tools:
            if tool.get("type") != "function" or "function" not in tool:
                normalized.append(dict(tool))
                continue

            fn = tool.get("function") or {}
            converted = {
                "type": "function",
                "name": fn.get("name"),
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {"type": "object", "properties": {}}),
            }
            if "strict" in fn:
                converted["strict"] = fn["strict"]
            normalized.append(converted)
        return normalized

    @staticmethod
    def extract_output_text(response: Any) -> str:
        text = getattr(response, "output_text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()

        parts: List[str] = []
        for item in getattr(response, "output", []) or []:
            item_type = getattr(item, "type", None)
            if item_type != "message":
                continue
            for content in getattr(item, "content", []) or []:
                content_text = getattr(content, "text", None)
                if content_text:
                    parts.append(str(content_text))
        return "\n".join(parts).strip()

    @staticmethod
    def extract_function_calls(response: Any) -> List[Dict[str, Any]]:
        calls: List[Dict[str, Any]] = []
        for item in getattr(response, "output", []) or []:
            if getattr(item, "type", None) != "function_call":
                continue
            calls.append(
                {
                    "id": getattr(item, "call_id", None) or getattr(item, "id", None),
                    "type": "function",
                    "function": {
                        "name": getattr(item, "name", ""),
                        "arguments": getattr(item, "arguments", "{}") or "{}",
                    },
                }
            )
        return calls

    @staticmethod
    def decode_arguments(arguments: str) -> Dict[str, Any]:
        try:
            return json.loads(arguments or "{}")
        except json.JSONDecodeError:
            return {}
