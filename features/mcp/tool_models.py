from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set


@dataclass
class ToolMetadata:
    name: str
    requires_env: Set[str] = field(default_factory=set)
    defaults: Dict[str, Any] = field(default_factory=dict)
    enable_reformat: bool = False
    flow: Optional[str] = None  # 例如 "navigation"


@dataclass
class ToolResult:
    name: str
    message: str
    data: Optional[Any] = None
    raw: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "message": self.message,
            "tool_name": self.name,
        }
        if self.data is not None:
            payload["tool_data"] = self.data
        if self.metadata:
            payload["metadata"] = self.metadata
        return payload
