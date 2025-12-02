"""
工具註冊中心
統一管理 MCP 工具的 OpenAI Function Calling Schema
2025 最佳實踐：讓 GPT 原生選擇工具，不需要自定義意圖檢測 Prompt

重構版本：整合 Pydantic Schema 自動生成
"""

from typing import Dict, List, Any, Optional, Callable, Type
from dataclasses import dataclass, field

from core.logging import get_logger
from core.tool_schema import (
    ToolSchema,
    ToolMetadata,
    ToolSchemaRegistry,
    tool_schema_registry,
    extract_schema_from_mcp_tool,
)

logger = get_logger("core.tool_registry")


@dataclass
class ToolDefinition:
    """工具定義（向後兼容）"""
    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Optional[Callable] = None
    category: str = "general"
    requires_auth: bool = False
    requires_location: bool = False
    keywords: List[str] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)


class ToolRegistry:
    """
    工具註冊中心（重構版）

    功能：
    1. 統一註冊所有 MCP 工具
    2. 自動從 MCPTool 類別生成 OpenAI Function Calling Schema
    3. 支援工具分類和過濾
    4. 動態啟用/停用工具
    5. 整合 ToolSchemaRegistry 提供 Pydantic 支援
    """

    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}
        self._disabled_tools: set = set()
        # 整合新的 Schema Registry
        self._schema_registry = tool_schema_registry

    def register(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: Optional[Callable] = None,
        category: str = "general",
        requires_auth: bool = False,
        requires_location: bool = False,
        keywords: Optional[List[str]] = None,
        examples: Optional[List[str]] = None,
    ) -> None:
        """註冊工具（向後兼容 + 自動同步到 Schema Registry）"""
        self._tools[name] = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
            category=category,
            requires_auth=requires_auth,
            requires_location=requires_location,
            keywords=keywords or [],
            examples=examples or [],
        )
        
        # 同步到 Schema Registry
        schema = ToolSchema(
            metadata=ToolMetadata(
                name=name,
                description=description,
                category=category,
                keywords=keywords or [],
                examples=examples or [],
                requires_location=requires_location,
                requires_auth=requires_auth,
            ),
            input_schema=parameters,
            handler=handler,
        )
        self._schema_registry.register(schema)
        
        logger.debug(f"註冊工具: {name}")

    def register_mcp_tool(self, tool_class: Type) -> bool:
        """
        從 MCPTool 類別自動註冊工具
        
        Args:
            tool_class: MCPTool 子類別
        
        Returns:
            是否註冊成功
        """
        schema = extract_schema_from_mcp_tool(tool_class)
        if not schema:
            return False
        
        # 註冊到 Schema Registry
        self._schema_registry.register(schema)
        
        # 同步到舊的 _tools（向後兼容）
        self._tools[schema.metadata.name] = ToolDefinition(
            name=schema.metadata.name,
            description=schema.metadata.description,
            parameters=schema.input_schema,
            handler=schema.handler,
            category=schema.metadata.category,
            requires_auth=schema.metadata.requires_auth,
            requires_location=schema.metadata.requires_location,
            keywords=schema.metadata.keywords,
            examples=schema.metadata.examples,
        )
        
        logger.debug(f"從 MCPTool 註冊工具: {schema.metadata.name}")
        return True

    def unregister(self, name: str) -> bool:
        """取消註冊工具"""
        if name in self._tools:
            del self._tools[name]
            self._schema_registry.unregister(name)
            return True
        return False

    def disable(self, name: str) -> None:
        """停用工具"""
        self._disabled_tools.add(name)
        self._schema_registry.disable(name)

    def enable(self, name: str) -> None:
        """啟用工具"""
        self._disabled_tools.discard(name)
        self._schema_registry.enable(name)

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """取得工具定義"""
        if name in self._disabled_tools:
            return None
        return self._tools.get(name)

    def get_openai_tools(
        self,
        categories: Optional[List[str]] = None,
        include_location_tools: bool = True,
        strict: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        生成 OpenAI Function Calling 格式的工具列表

        Args:
            categories: 只包含指定分類的工具
            include_location_tools: 是否包含需要位置的工具
            strict: 是否啟用 strict mode（確保輸出符合 schema）

        Returns:
            OpenAI tools 格式的列表
        """
        # 優先使用 Schema Registry（支援 strict mode）
        return self._schema_registry.get_openai_tools(
            categories=categories,
            include_location_tools=include_location_tools,
            strict=strict,
        )

    def get_openai_tools_legacy(
        self,
        categories: Optional[List[str]] = None,
        include_location_tools: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        生成 OpenAI Function Calling 格式的工具列表（舊版，不支援 strict mode）
        """
        tools = []

        for name, tool in self._tools.items():
            # 跳過停用的工具
            if name in self._disabled_tools:
                continue

            # 分類過濾
            if categories and tool.category not in categories:
                continue

            # 位置過濾
            if not include_location_tools and tool.requires_location:
                continue

            tools.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                }
            })

        return tools

    def get_tool_names(self) -> List[str]:
        """取得所有已註冊的工具名稱"""
        return [
            name for name in self._tools.keys()
            if name not in self._disabled_tools
        ]

    def get_stats(self) -> Dict[str, Any]:
        """取得統計資訊"""
        return self._schema_registry.get_stats()

    def get_summaries(self) -> List[Dict[str, Any]]:
        """取得所有工具摘要（用於快速意圖匹配）"""
        return self._schema_registry.get_summaries()


# 全域單例
tool_registry = ToolRegistry()


def register_mcp_tools_to_registry(mcp_server) -> int:
    """
    從 MCP Server 自動註冊工具到 Registry
    
    2025 重構版：優先使用 MCPTool 類別自動提取 Schema

    Args:
        mcp_server: MCPServer 實例

    Returns:
        註冊的工具數量
    """
    count = 0

    for tool_name, tool in mcp_server.tools.items():
        # 優先嘗試從 MCPTool 類別提取完整 Schema
        if hasattr(tool, 'handler') and hasattr(tool.handler, '__self__'):
            tool_class = tool.handler.__self__
            if tool_registry.register_mcp_tool(type(tool_class)):
                count += 1
                continue
        
        # 降級：使用舊方法註冊
        description = getattr(tool, 'description', f'{tool_name} 工具')
        parameters = {"type": "object", "properties": {}, "required": []}

        if hasattr(tool, 'handler') and hasattr(tool.handler, '__self__'):
            tool_class = tool.handler.__self__
            if hasattr(tool_class, 'get_input_schema'):
                try:
                    parameters = tool_class.get_input_schema()
                except Exception as e:
                    logger.warning(f"取得 {tool_name} schema 失敗: {e}")

        # 提取關鍵字和範例
        keywords = []
        examples = []
        if hasattr(tool, 'handler') and hasattr(tool.handler, '__self__'):
            tool_class = tool.handler.__self__
            keywords = getattr(tool_class, 'KEYWORDS', [])
            examples = getattr(tool_class, 'USAGE_TIPS', [])

        # 判斷分類
        category = _infer_category(tool_name)

        # 判斷是否需要位置
        requires_location = _requires_location(tool_name, parameters)

        tool_registry.register(
            name=tool_name,
            description=description,
            parameters=parameters,
            handler=getattr(tool, 'handler', None),
            category=category,
            requires_location=requires_location,
            keywords=keywords,
            examples=examples,
        )
        count += 1

    logger.info(f"從 MCP Server 註冊了 {count} 個工具")
    return count


def _infer_category(tool_name: str) -> str:
    """推斷工具分類"""
    name_lower = tool_name.lower()

    if any(k in name_lower for k in ['weather', 'forecast']):
        return "weather"
    if any(k in name_lower for k in ['bus', 'train', 'metro', 'thsr', 'youbike', 'parking']):
        return "transportation"
    if any(k in name_lower for k in ['geocode', 'directions', 'location']):
        return "location"
    if any(k in name_lower for k in ['news']):
        return "information"
    if any(k in name_lower for k in ['exchange', 'currency']):
        return "finance"
    if any(k in name_lower for k in ['health', 'heart', 'sleep', 'step']):
        return "health"

    return "general"


def _requires_location(tool_name: str, parameters: Dict) -> bool:
    """判斷工具是否需要位置資訊"""
    # 檢查參數中是否有 lat/lon
    props = parameters.get("properties", {})
    if "lat" in props or "lon" in props or "latitude" in props or "longitude" in props:
        return True

    # 檢查工具名稱
    location_tools = [
        'reverse_geocode', 'directions', 'tdx_bus_arrival',
        'tdx_youbike', 'tdx_metro', 'tdx_parking', 'tdx_train', 'tdx_thsr'
    ]
    return tool_name in location_tools
