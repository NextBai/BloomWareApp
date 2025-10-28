"""
MCP 類型定義
避免循環導入問題
"""

from typing import Dict, Any, Optional, Callable
from dataclasses import dataclass


@dataclass
class Tool:
    """MCP Tool 定義"""
    name: str
    description: str
    inputSchema: Dict[str, Any]
    handler: Optional[Callable] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """轉換為 MCP 工具描述格式"""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.inputSchema
        }