"""
MCP 類型定義
避免循環導入問題
"""

from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass


@dataclass
class Tool:
    """MCP Tool 定義"""
    name: str
    description: str
    inputSchema: Dict[str, Any]
    handler: Optional[Callable] = None
    metadata: Optional[Dict[str, Any]] = None
    outputSchema: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """轉換為 MCP 工具描述格式"""
        payload = {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.inputSchema
        }
        if self.outputSchema:
            payload["outputSchema"] = self.outputSchema
        return payload


@dataclass
class ToolCallResult:
    """MCP tools/call 結果格式。"""
    content: List[Dict[str, Any]]
    structuredContent: Optional[Dict[str, Any]] = None
    isError: bool = False

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "content": self.content,
            "isError": self.isError,
        }
        if self.structuredContent is not None:
            payload["structuredContent"] = self.structuredContent
        return payload
