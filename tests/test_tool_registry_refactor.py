"""
測試重構後的工具註冊系統
驗證 Pydantic Schema 自動生成和 OpenAI Function Calling 格式
"""

import pytest
import sys
import os

# 添加專案根目錄到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tool_schema import (
    ToolSchema,
    ToolMetadata,
    ToolSchemaRegistry,
    extract_schema_from_mcp_tool,
)
from core.tool_registry import ToolRegistry, ToolDefinition


class TestToolSchema:
    """測試 ToolSchema 類別"""
    
    def test_to_openai_tool_basic(self):
        """測試基本的 OpenAI 工具格式轉換"""
        schema = ToolSchema(
            metadata=ToolMetadata(
                name="test_tool",
                description="測試工具",
                category="test",
                keywords=["測試", "test"],
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "查詢字串"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
        )
        
        openai_tool = schema.to_openai_tool(strict=True)
        
        assert openai_tool["type"] == "function"
        assert openai_tool["function"]["name"] == "test_tool"
        assert "測試工具" in openai_tool["function"]["description"]
        assert openai_tool["function"]["strict"] is True
        
        # 檢查 strict mode 要求
        params = openai_tool["function"]["parameters"]
        assert params["additionalProperties"] is False
        assert "query" in params["required"]
    
    def test_rich_description(self):
        """測試豐富描述生成"""
        schema = ToolSchema(
            metadata=ToolMetadata(
                name="weather",
                description="查詢天氣",
                keywords=["天氣", "氣溫", "下雨"],
                examples=["台北天氣", "明天會下雨嗎"],
            ),
            input_schema={"type": "object", "properties": {}},
        )
        
        openai_tool = schema.to_openai_tool()
        desc = openai_tool["function"]["description"]
        
        assert "查詢天氣" in desc
        assert "天氣" in desc
        assert "台北天氣" in desc
    
    def test_get_summary(self):
        """測試工具摘要"""
        schema = ToolSchema(
            metadata=ToolMetadata(
                name="bus_query",
                description="查詢公車到站時間",
                category="transportation",
                keywords=["公車", "bus"],
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "route": {"type": "string"},
                    "stop": {"type": "string"},
                },
            },
        )
        
        summary = schema.get_summary()
        
        assert summary["name"] == "bus_query"
        assert summary["category"] == "transportation"
        assert "route" in summary["params"]
        assert "stop" in summary["params"]


class TestToolSchemaRegistry:
    """測試 ToolSchemaRegistry 類別"""
    
    def test_register_and_get(self):
        """測試註冊和取得"""
        registry = ToolSchemaRegistry()
        
        schema = ToolSchema(
            metadata=ToolMetadata(name="test", description="Test"),
            input_schema={"type": "object", "properties": {}},
        )
        
        registry.register(schema)
        
        retrieved = registry.get("test")
        assert retrieved is not None
        assert retrieved.metadata.name == "test"
    
    def test_disable_enable(self):
        """測試停用和啟用"""
        registry = ToolSchemaRegistry()
        
        schema = ToolSchema(
            metadata=ToolMetadata(name="toggleable", description="Test"),
            input_schema={"type": "object", "properties": {}},
        )
        
        registry.register(schema)
        
        # 停用
        registry.disable("toggleable")
        assert registry.get("toggleable") is None
        
        # 啟用
        registry.enable("toggleable")
        assert registry.get("toggleable") is not None
    
    def test_get_openai_tools_filtering(self):
        """測試 OpenAI 工具列表過濾"""
        registry = ToolSchemaRegistry()
        
        # 註冊不同分類的工具
        registry.register(ToolSchema(
            metadata=ToolMetadata(name="weather", description="天氣", category="weather"),
            input_schema={"type": "object", "properties": {}},
        ))
        registry.register(ToolSchema(
            metadata=ToolMetadata(name="bus", description="公車", category="transportation"),
            input_schema={"type": "object", "properties": {}},
        ))
        registry.register(ToolSchema(
            metadata=ToolMetadata(
                name="geocode",
                description="地理編碼",
                category="location",
                requires_location=True,
            ),
            input_schema={"type": "object", "properties": {}},
        ))
        
        # 測試分類過濾
        weather_tools = registry.get_openai_tools(categories=["weather"])
        assert len(weather_tools) == 1
        assert weather_tools[0]["function"]["name"] == "weather"
        
        # 測試位置過濾
        no_location_tools = registry.get_openai_tools(include_location_tools=False)
        tool_names = [t["function"]["name"] for t in no_location_tools]
        assert "geocode" not in tool_names
    
    def test_get_stats(self):
        """測試統計資訊"""
        registry = ToolSchemaRegistry()
        
        registry.register(ToolSchema(
            metadata=ToolMetadata(name="t1", description="", category="a"),
            input_schema={"type": "object", "properties": {}},
        ))
        registry.register(ToolSchema(
            metadata=ToolMetadata(name="t2", description="", category="a"),
            input_schema={"type": "object", "properties": {}},
        ))
        registry.register(ToolSchema(
            metadata=ToolMetadata(name="t3", description="", category="b"),
            input_schema={"type": "object", "properties": {}},
        ))
        
        registry.disable("t1")
        
        stats = registry.get_stats()
        
        assert stats["total"] == 3
        assert stats["disabled"] == 1
        assert stats["active"] == 2
        assert stats["categories"]["a"] == 2
        assert stats["categories"]["b"] == 1


class TestToolRegistry:
    """測試重構後的 ToolRegistry 類別"""
    
    def test_register_legacy(self):
        """測試舊版註冊方式（向後兼容）"""
        # 使用獨立的 schema registry 避免全域污染
        from core.tool_schema import ToolSchemaRegistry
        isolated_schema_registry = ToolSchemaRegistry()
        
        registry = ToolRegistry()
        registry._schema_registry = isolated_schema_registry
        
        registry.register(
            name="legacy_tool",
            description="舊版工具",
            parameters={"type": "object", "properties": {"x": {"type": "string"}}},
            category="test",
            keywords=["legacy"],
        )
        
        tool = registry.get_tool("legacy_tool")
        assert tool is not None
        assert tool.name == "legacy_tool"
        assert tool.keywords == ["legacy"]
    
    def test_get_openai_tools_strict(self):
        """測試 strict mode 的 OpenAI 工具格式"""
        # 使用獨立的 schema registry 避免全域污染
        from core.tool_schema import ToolSchemaRegistry
        isolated_schema_registry = ToolSchemaRegistry()
        
        registry = ToolRegistry()
        registry._schema_registry = isolated_schema_registry
        
        registry.register(
            name="strict_tool",
            description="Strict 工具",
            parameters={
                "type": "object",
                "properties": {
                    "required_param": {"type": "string"},
                    "optional_param": {"type": "integer", "default": 5},
                },
                "required": ["required_param"],
            },
        )
        
        tools = registry.get_openai_tools(strict=True)
        
        assert len(tools) == 1
        tool = tools[0]
        
        # 檢查 strict mode 格式
        assert tool["function"]["strict"] is True
        params = tool["function"]["parameters"]
        assert params["additionalProperties"] is False
    
    def test_get_summaries(self):
        """測試取得工具摘要"""
        # 使用獨立的 schema registry 避免全域污染
        from core.tool_schema import ToolSchemaRegistry
        isolated_schema_registry = ToolSchemaRegistry()
        
        registry = ToolRegistry()
        registry._schema_registry = isolated_schema_registry
        
        registry.register(
            name="summary_tool",
            description="摘要測試工具",
            parameters={"type": "object", "properties": {"a": {"type": "string"}}},
            keywords=["摘要", "test"],
        )
        
        summaries = registry.get_summaries()
        
        assert len(summaries) == 1
        assert summaries[0]["name"] == "summary_tool"
        assert "摘要" in summaries[0]["keywords"]


class TestExtractSchemaFromMCPTool:
    """測試從 MCPTool 類別提取 Schema"""
    
    def test_extract_from_mock_tool(self):
        """測試從模擬的 MCPTool 類別提取"""
        
        class MockTool:
            NAME = "mock_tool"
            DESCRIPTION = "模擬工具"
            CATEGORY = "test"
            KEYWORDS = ["mock", "test"]
            USAGE_TIPS = ["使用範例"]
            
            @classmethod
            def get_input_schema(cls):
                return {
                    "type": "object",
                    "properties": {
                        "param1": {"type": "string"},
                    },
                    "required": ["param1"],
                }
            
            @classmethod
            def get_output_schema(cls):
                return {"type": "object", "properties": {"result": {"type": "string"}}}
            
            @classmethod
            async def execute(cls, arguments):
                return {"result": "ok"}
        
        schema = extract_schema_from_mcp_tool(MockTool)
        
        assert schema is not None
        assert schema.metadata.name == "mock_tool"
        assert schema.metadata.description == "模擬工具"
        assert schema.metadata.category == "test"
        assert "mock" in schema.metadata.keywords
        assert "param1" in schema.input_schema["properties"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
