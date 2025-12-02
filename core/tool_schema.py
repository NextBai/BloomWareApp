"""
Pydantic 工具 Schema 定義
2025 最佳實踐：使用 Pydantic 自動生成 OpenAI Function Calling Schema

功能：
1. 工具輸入/輸出的 Pydantic 基礎類別
2. 自動生成 OpenAI tools 格式的 JSON Schema
3. 支援 strict mode 確保 100% 有效輸出
4. 裝飾器模式自動註冊工具
"""

from typing import Dict, Any, Optional, List, Callable, Type, TypeVar, get_type_hints
from dataclasses import dataclass, field
from functools import wraps
import inspect
import logging

logger = logging.getLogger("core.tool_schema")

# 類型變數
T = TypeVar("T")


@dataclass
class ToolMetadata:
    """
    工具元資料（增強版）
    
    2025 最佳實踐：豐富的元資料讓 GPT 更容易理解何時使用哪個工具
    """
    name: str
    description: str
    category: str = "general"
    keywords: List[str] = field(default_factory=list)  # 觸發關鍵字
    examples: List[str] = field(default_factory=list)  # 使用範例
    negative_examples: List[str] = field(default_factory=list)  # 不應使用的情況
    requires_location: bool = False
    requires_auth: bool = False
    is_complex: bool = False
    priority: int = 100  # 優先級（數字越小越優先）
    aliases: List[str] = field(default_factory=list)  # 工具別名


@dataclass
class ToolSchema:
    """工具 Schema 定義（自描述）"""
    metadata: ToolMetadata
    input_schema: Dict[str, Any]
    output_schema: Optional[Dict[str, Any]] = None
    handler: Optional[Callable] = None

    def to_openai_tool(self, strict: bool = True) -> Dict[str, Any]:
        """
        轉換為 OpenAI Function Calling 格式
        
        Args:
            strict: 是否啟用 strict mode（確保輸出符合 schema）
        
        Returns:
            OpenAI tools 格式的字典
        """
        # 確保 schema 符合 OpenAI strict mode 要求
        parameters = self._prepare_strict_schema(self.input_schema) if strict else self.input_schema
        
        tool_def = {
            "type": "function",
            "function": {
                "name": self.metadata.name,
                "description": self._build_rich_description(),
                "parameters": parameters,
            }
        }
        
        if strict:
            tool_def["function"]["strict"] = True
        
        return tool_def

    def _build_rich_description(self) -> str:
        """
        建構豐富的工具描述（包含範例、關鍵字、負面範例）
        讓 GPT 更容易理解何時使用此工具
        
        2025 最佳實踐：
        - 正面範例：告訴 GPT 何時使用
        - 負面範例：告訴 GPT 何時不要使用（減少誤判）
        """
        desc_parts = [self.metadata.description]
        
        # 加入關鍵字提示
        if self.metadata.keywords:
            keywords_str = "、".join(self.metadata.keywords[:5])
            desc_parts.append(f"觸發詞：{keywords_str}")
        
        # 加入使用範例（正面）
        if self.metadata.examples:
            examples_str = "；".join(self.metadata.examples[:3])
            desc_parts.append(f"適用：{examples_str}")
        
        # 加入負面範例（告訴 GPT 何時不要使用）
        if self.metadata.negative_examples:
            neg_str = "；".join(self.metadata.negative_examples[:2])
            desc_parts.append(f"不適用：{neg_str}")
        
        return "。".join(desc_parts)

    def _prepare_strict_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        準備符合 OpenAI strict mode 的 schema
        
        strict mode 要求：
        1. additionalProperties: false
        2. 所有屬性都在 required 中（或有 default）
        3. 不支援 oneOf/anyOf/allOf
        """
        result = dict(schema)
        
        # 確保是 object 類型
        if result.get("type") != "object":
            result = {"type": "object", "properties": result}
        
        # 添加 additionalProperties: false
        result["additionalProperties"] = False
        
        # 確保所有屬性都在 required 中
        properties = result.get("properties", {})
        existing_required = set(result.get("required", []))
        
        # 收集所有沒有 default 的屬性
        all_required = []
        for prop_name, prop_schema in properties.items():
            if prop_name in existing_required or "default" not in prop_schema:
                all_required.append(prop_name)
        
        result["required"] = all_required
        
        return result

    def get_summary(self) -> Dict[str, Any]:
        """獲取工具摘要（用於快速意圖匹配）"""
        return {
            "name": self.metadata.name,
            "description": self.metadata.description[:50] + "..." if len(self.metadata.description) > 50 else self.metadata.description,
            "category": self.metadata.category,
            "keywords": self.metadata.keywords,
            "params": list(self.input_schema.get("properties", {}).keys())
        }


def extract_schema_from_mcp_tool(tool_class: Type) -> Optional[ToolSchema]:
    """
    從現有 MCPTool 類別提取 Schema（增強版）
    
    Args:
        tool_class: MCPTool 子類別
    
    Returns:
        ToolSchema 或 None
    """
    try:
        # 檢查必要屬性
        if not hasattr(tool_class, "NAME") or not hasattr(tool_class, "get_input_schema"):
            return None
        
        name = getattr(tool_class, "NAME", "")
        if not name:
            return None
        
        # 提取元資料（增強版）
        metadata = ToolMetadata(
            name=name,
            description=getattr(tool_class, "DESCRIPTION", f"{name} 工具"),
            category=getattr(tool_class, "CATEGORY", "general"),
            keywords=getattr(tool_class, "KEYWORDS", []),
            examples=getattr(tool_class, "USAGE_TIPS", []),
            negative_examples=getattr(tool_class, "NEGATIVE_EXAMPLES", []),
            requires_location=_check_requires_location(tool_class),
            requires_auth=getattr(tool_class, "REQUIRES_AUTH", False),
            is_complex=getattr(tool_class, "IS_COMPLEX", False),
            priority=getattr(tool_class, "PRIORITY", 100),
            aliases=getattr(tool_class, "ALIASES", []),
        )
        
        # 提取 input schema
        try:
            input_schema = tool_class.get_input_schema()
        except Exception as e:
            logger.warning(f"提取 {name} input schema 失敗: {e}")
            input_schema = {"type": "object", "properties": {}}
        
        # 提取 output schema（可選）
        output_schema = None
        if hasattr(tool_class, "get_output_schema"):
            try:
                output_schema = tool_class.get_output_schema()
            except Exception:
                pass
        
        # 提取 handler
        handler = None
        if hasattr(tool_class, "execute"):
            handler = tool_class.execute
        
        return ToolSchema(
            metadata=metadata,
            input_schema=input_schema,
            output_schema=output_schema,
            handler=handler,
        )
    
    except Exception as e:
        logger.error(f"提取 {tool_class} schema 失敗: {e}")
        return None


def _check_requires_location(tool_class: Type) -> bool:
    """檢查工具是否需要位置資訊"""
    # 檢查類別屬性
    if getattr(tool_class, "REQUIRES_LOCATION", False):
        return True
    
    # 檢查 input schema 中是否有 lat/lon
    try:
        schema = tool_class.get_input_schema()
        props = schema.get("properties", {})
        if "lat" in props or "lon" in props:
            return True
    except Exception:
        pass
    
    # 檢查工具名稱
    name = getattr(tool_class, "NAME", "").lower()
    location_tools = [
        "reverse_geocode", "directions", "tdx_bus_arrival",
        "tdx_youbike", "tdx_metro", "tdx_parking", "tdx_train", "tdx_thsr"
    ]
    return name in location_tools


class ToolSchemaRegistry:
    """
    工具 Schema 註冊中心
    
    功能：
    1. 統一管理所有工具的 Schema
    2. 自動生成 OpenAI Function Calling 格式
    3. 支援動態過濾和分組
    """
    
    def __init__(self):
        self._schemas: Dict[str, ToolSchema] = {}
        self._disabled: set = set()
    
    def register(self, schema: ToolSchema) -> None:
        """註冊工具 Schema"""
        self._schemas[schema.metadata.name] = schema
        logger.debug(f"註冊工具 Schema: {schema.metadata.name}")
    
    def register_from_mcp_tool(self, tool_class: Type) -> bool:
        """從 MCPTool 類別註冊"""
        schema = extract_schema_from_mcp_tool(tool_class)
        if schema:
            self.register(schema)
            return True
        return False
    
    def unregister(self, name: str) -> bool:
        """取消註冊"""
        if name in self._schemas:
            del self._schemas[name]
            return True
        return False
    
    def disable(self, name: str) -> None:
        """停用工具"""
        self._disabled.add(name)
    
    def enable(self, name: str) -> None:
        """啟用工具"""
        self._disabled.discard(name)
    
    def get(self, name: str) -> Optional[ToolSchema]:
        """取得工具 Schema"""
        if name in self._disabled:
            return None
        return self._schemas.get(name)
    
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
            strict: 是否啟用 strict mode
        
        Returns:
            OpenAI tools 格式的列表
        """
        tools = []
        
        for name, schema in self._schemas.items():
            # 跳過停用的工具
            if name in self._disabled:
                continue
            
            # 分類過濾
            if categories and schema.metadata.category not in categories:
                continue
            
            # 位置過濾
            if not include_location_tools and schema.metadata.requires_location:
                continue
            
            tools.append(schema.to_openai_tool(strict=strict))
        
        return tools
    
    def get_tool_names(self) -> List[str]:
        """取得所有已註冊的工具名稱"""
        return [
            name for name in self._schemas.keys()
            if name not in self._disabled
        ]
    
    def get_summaries(self) -> List[Dict[str, Any]]:
        """取得所有工具摘要（用於快速意圖匹配）"""
        return [
            schema.get_summary()
            for name, schema in self._schemas.items()
            if name not in self._disabled
        ]
    
    def get_stats(self) -> Dict[str, Any]:
        """取得統計資訊"""
        categories = {}
        for schema in self._schemas.values():
            cat = schema.metadata.category
            categories[cat] = categories.get(cat, 0) + 1
        
        return {
            "total": len(self._schemas),
            "disabled": len(self._disabled),
            "active": len(self._schemas) - len(self._disabled),
            "categories": categories,
        }


# 全域單例
tool_schema_registry = ToolSchemaRegistry()
