"""
MCP 功能服務器 - 符合 2025 年最新 MCP 標準
整合所有天氣、新聞、匯率功能為 MCP Tools
"""

import json
import sys
import asyncio
import logging
import time
import os
from typing import Dict, Any, List, Optional, Callable, Tuple
from enum import Enum
from .types import Tool, ToolCallResult
from .auto_registry import MCPAutoRegistry

try:
    import jsonschema
except ImportError:
    jsonschema = None

LOG_LEVEL_NAME = os.getenv("BLOOMWARE_LOG_LEVEL", "WARNING").upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_NAME, logging.WARNING)
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("mcp.server")
logger.setLevel(LOG_LEVEL)


class JSONRPCError(Exception):
    """JSON-RPC 錯誤"""
    def __init__(self, code: int, message: str, data: Any = None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(message)


class ErrorCode(Enum):
    """標準 JSON-RPC 錯誤碼"""
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603


# Tool 類型已移至 types.py


class FeaturesMCPServer:
    """MCP 功能服務器 - 整合所有功能"""

    def __init__(self, name: str = "features-mcp-server", version: str = "2.0.0"):
        self.name = name
        self.version = version
        self.tools: Dict[str, Tool] = {}
        self.handlers: Dict[str, Callable] = {}

        # Schema 快取（用於 Lazy Loading）
        self._schema_cache: Dict[str, Tuple[Dict, float]] = {}  # {tool_name: (schema, timestamp)}
        self._schema_cache_ttl = 600  # 10 分鐘

        # 保存註冊器引用以便清理
        self._registry = None

        # 註冊內建處理器
        self._register_builtin_handlers()

        # 自動掃描並註冊所有工具
        self._auto_register_tools()

        logger.info(f"MCP 功能服務器初始化完成: {name} v{version}")

    def _register_builtin_handlers(self):
        """註冊內建的 MCP 協議處理器"""
        self.handlers["initialize"] = self._handle_initialize
        self.handlers["tools/list"] = self._handle_tools_list
        self.handlers["tools/call"] = self._handle_tools_call

    def _auto_register_tools(self):
        """自動掃描並註冊工具"""
        try:
            # 創建自動註冊器
            registry = MCPAutoRegistry()
            
            # 保存註冊器引用以便後續清理
            self._registry = registry

            # 不在这里異步發現工具，避免事件循環衝突
            # 工具發現將在應用啟動後的異步任務中進行
            logger.info("MCP 自動註冊器已創建，等待異步工具發現")

        except Exception as e:
            logger.error(f"創建自動註冊器失敗: {e}")

    async def async_discover_tools(self):
        """異步發現並註冊工具"""
        try:
            if not self._registry:
                logger.error("自動註冊器未初始化")
                return
            
            discovered_tools = await self._registry.auto_discover_async()
            
            # 註冊發現的工具
            for tool in discovered_tools:
                self.register_tool(tool)

            logger.info(f"異步工具發現完成，總計 {len(discovered_tools)} 個工具")

        except Exception as e:
            logger.error(f"異步工具發現失敗: {e}")

    async def start_external_servers(self):
        """啟動外部 MCP 服務器"""
        if hasattr(self, '_registry') and self._registry:
            # 先異步發現工具
            await self.async_discover_tools()
            
            # 然後啟動外部服務器
            await self._registry.start_external_servers()

        # 註冊系統工具
        self._register_system_tools()

    def _register_system_tools(self):
        """註冊系統工具"""

        # 列出所有功能工具
        async def list_features_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
            """列出所有可用功能"""
            try:
                tools = []
                for tool_name, tool in self.tools.items():
                    tools.append({
                        "name": tool_name,
                        "description": tool.description,
                        "parameters": tool.inputSchema.get("properties", {})
                    })

                # 分類整理
                categories = {}
                for tool_info in tools:
                    name_parts = tool_info["name"].split("_", 1)
                    category = name_parts[0] if len(name_parts) > 1 else "other"
                    if category not in categories:
                        categories[category] = []
                    categories[category].append(tool_info)

                # 格式化輸出
                result = "📋 MCP 功能列表\n\n"
                for category, tools_in_cat in categories.items():
                    cat_name = {"weather": "天氣", "news": "新聞", "exchange": "匯率", "system": "系統"}.get(category, category)
                    result += f"◆ {cat_name}\n"
                    for tool in tools_in_cat:
                        result += f"  • {tool['name']}: {tool['description']}\n"
                    result += "\n"

                return {
                    "success": True,
                    "content": result,
                    "tools": tools,
                    "categories": categories
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": str(e)
                }

        # 檢查是否已經存在系統工具占位符，如果存在則替換處理器
        system_tools_to_register = [
            ("system_list_features", "列出所有可用的 MCP 功能", list_features_handler),
            ("system_health_check", "檢查 MCP 服務器健康狀態", self._create_health_check_handler())
        ]

        for tool_name, description, handler in system_tools_to_register:
            if tool_name in self.tools:
                # 替換現有占位符的處理器
                self.tools[tool_name].handler = handler
                logger.info(f"替換系統工具處理器: {tool_name}")
            else:
                # 創建新的系統工具
                tool = Tool(
                    name=tool_name,
                    description=description,
                    inputSchema={"type": "object", "properties": {}},
                    handler=handler,
                    outputSchema={
                        "type": "object",
                        "properties": {
                            "success": {"type": "boolean"},
                            "content": {"type": "string"},
                            "error": {"type": ["string", "null"]},
                            "error_code": {"type": ["string", "null"]},
                        },
                        "required": ["success"],
                    }
                )
                self.register_tool(tool)

    def _create_health_check_handler(self):
        """創建健康檢查處理器"""
        async def health_check_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
            """系統健康檢查"""
            try:
                status = {
                    "server": "running",
                    "version": self.version,
                    "tools_count": len(self.tools)
                }

                return {
                    "success": True,
                    "status": status,
                    "content": f"✅ MCP 服務器運行正常 | 版本: {self.version} | 工具數: {len(self.tools)}"
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": str(e)
                }
        
        return health_check_handler

    def register_tool(self, tool: Tool):
        """註冊工具"""
        self.tools[tool.name] = tool
        logger.info(f"註冊工具: {tool.name}")

    def _format_tool_result(self, tool_name: str, result: Any) -> Dict[str, Any]:
        """轉成 MCP tools/call result，保留 structuredContent。"""
        if isinstance(result, ToolCallResult):
            return result.to_dict()

        if isinstance(result, dict):
            is_error = result.get("success") is False
            content = result.get("content")
            if not content:
                content = result.get("error") if is_error else json.dumps(result, ensure_ascii=False)

            output_issue = self._validate_tool_output(tool_name, result)
            if output_issue:
                return ToolCallResult(
                    content=[{"type": "text", "text": "工具輸出格式不符合契約"}],
                    structuredContent={
                        "success": False,
                        "error_code": "TOOL_OUTPUT_VALIDATION",
                        "tool_name": tool_name,
                        "details": output_issue,
                    },
                    isError=True,
                ).to_dict()

            payload = ToolCallResult(
                content=[{"type": "text", "text": str(content)}],
                structuredContent=result,
                isError=is_error,
            ).to_dict()
            if is_error and "error_code" not in payload["structuredContent"]:
                payload["structuredContent"]["error_code"] = "TOOL_EXECUTION_ERROR"
            return payload

        return ToolCallResult(
            content=[{"type": "text", "text": str(result)}],
            structuredContent={"tool_name": tool_name, "value": result},
            isError=False,
        ).to_dict()

    def _validate_tool_output(self, tool_name: str, result: Dict[str, Any]) -> Optional[str]:
        """用工具 outputSchema 驗證 structuredContent。"""
        tool = self.tools.get(tool_name)
        if not tool or not tool.outputSchema or jsonschema is None:
            return None

        try:
            jsonschema.validate(result, tool.outputSchema)
            return None
        except jsonschema.ValidationError as exc:
            field_path = ".".join(str(part) for part in exc.absolute_path)
            if field_path:
                return f"{field_path}: {exc.message}"
            return exc.message
    
    def get_tools_summary(self) -> List[Dict[str, Any]]:
        """
        獲取所有工具的摘要（用於 Intent Detection，減少 token 消耗）
        
        返回輕量級工具列表，只包含：
        - name, description_short, category, keywords, is_complex
        - 簡單工具額外包含 params 列表
        
        相比完整 schema，節省約 60-70% tokens
        """
        summaries = []
        
        for tool_name, tool in self.tools.items():
            try:
                # 檢查工具是否有 get_summary 方法（新工具）
                if hasattr(tool, 'get_summary') and callable(tool.get_summary):
                    summary = tool.get_summary()
                else:
                    # 向後兼容：為舊工具生成簡化摘要
                    summary = {
                        "name": tool_name,
                        "description": tool.description[:50] + "..." if len(tool.description) > 50 else tool.description,
                        "category": tool.metadata.get('category', 'general') if hasattr(tool, 'metadata') and tool.metadata else 'general',
                        "keywords": tool.metadata.get('keywords', []) if hasattr(tool, 'metadata') and tool.metadata else [],
                        "is_complex": False  # 舊工具預設為簡單工具
                    }
                
                summaries.append(summary)
                
            except Exception as e:
                logger.error(f"生成工具摘要失敗: {tool_name}, 錯誤: {e}")
                # 降級：返回最基本的資訊
                summaries.append({
                    "name": tool_name,
                    "description": tool.description if hasattr(tool, 'description') else "未知工具",
                    "category": "其他",
                    "keywords": [],
                    "is_complex": False
                })
        
        logger.debug(f"生成工具摘要: {len(summaries)} 個工具")
        return summaries
    
    def get_tool_full_schema(self, tool_name: str) -> Dict[str, Any]:
        """
        獲取工具的完整 Schema（Lazy Loading，按需載入）
        
        使用快取機制：
        - 首次調用：載入完整 schema 並快取 10 分鐘
        - 後續調用：直接從快取返回（節省計算）
        - 快取過期：重新載入
        
        Args:
            tool_name: 工具名稱
            
        Returns:
            完整的工具定義（包含 inputSchema, outputSchema 等）
            
        Raises:
            ValueError: 工具不存在
        """
        # 檢查快取
        if tool_name in self._schema_cache:
            schema, timestamp = self._schema_cache[tool_name]
            if time.time() - timestamp < self._schema_cache_ttl:
                logger.debug(f"Schema 快取命中: {tool_name}")
                return schema
            else:
                # 快取過期，刪除
                del self._schema_cache[tool_name]
                logger.debug(f"Schema 快取過期: {tool_name}")
        
        # 快取未命中，載入完整 schema
        if tool_name not in self.tools:
            raise ValueError(f"工具不存在: {tool_name}")
        
        tool = self.tools[tool_name]
        
        try:
            # 檢查工具是否有 get_full_definition 方法（新工具）
            if hasattr(tool, 'get_full_definition') and callable(tool.get_full_definition):
                schema = tool.get_full_definition()
            else:
                # 向後兼容：從現有屬性構建完整定義
                schema = {
                    "name": tool_name,
                    "description": tool.description if hasattr(tool, 'description') else "",
                    "inputSchema": tool.inputSchema if hasattr(tool, 'inputSchema') else {},
                    "outputSchema": getattr(tool, 'outputSchema', {}),
                    "metadata": getattr(tool, 'metadata', {})
                }
            
            # 更新快取
            self._schema_cache[tool_name] = (schema, time.time())
            logger.debug(f"Schema 已快取: {tool_name}")
            
            return schema
            
        except Exception as e:
            logger.error(f"載入工具 Schema 失敗: {tool_name}, 錯誤: {e}")
            raise ValueError(f"無法載入工具 {tool_name} 的 Schema: {e}")

    async def _handle_initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """處理初始化請求"""
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {"listChanged": True}
            },
            "serverInfo": {
                "name": self.name,
                "version": self.version
            }
        }

    async def _handle_tools_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """處理工具列表請求"""
        return {
            "tools": [tool.to_dict() for tool in self.tools.values()]
        }

    async def _handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """處理工具調用請求"""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if tool_name not in self.tools:
            raise JSONRPCError(
                ErrorCode.METHOD_NOT_FOUND.value,
                f"工具不存在: {tool_name}"
            )

        tool = self.tools[tool_name]
        if tool.handler:
            try:
                result = await tool.handler(arguments)
                return self._format_tool_result(tool_name, result)

            except Exception as e:
                logger.error(f"工具執行錯誤 {tool_name}: {e}")
                return ToolCallResult(
                    content=[{"type": "text", "text": "工具執行失敗"}],
                    structuredContent={
                        "success": False,
                        "error_code": "TOOL_EXECUTION_ERROR",
                        "tool_name": tool_name,
                    },
                    isError=True,
                ).to_dict()

        return ToolCallResult(
            content=[{"type": "text", "text": "工具未實作"}],
            structuredContent={
                "success": False,
                "error_code": "TOOL_NOT_IMPLEMENTED",
                "tool_name": tool_name,
            },
            isError=True,
        ).to_dict()

    async def cleanup(self):
        """清理資源"""
        if self._registry:
            await self._registry.cleanup()
        logger.info("MCP 功能服務器清理完成")

    async def run(self):
        """透過 stdio 運行服務器"""
        logger.info("MCP 功能服務器透過 stdio 啟動")

        reader = asyncio.StreamReader()
        reader_protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_event_loop().connect_read_pipe(lambda: reader_protocol, sys.stdin)

        writer = sys.stdout

        try:
            while True:
                try:
                    # 讀取請求
                    line = await reader.readline()
                    if not line:
                        break

                    request_data = json.loads(line.decode())

                    # 處理請求
                    response = await self.handle_request(request_data)

                    # 寫入響應
                    response_line = json.dumps(response, ensure_ascii=False) + "\n"
                    writer.write(response_line)
                    writer.flush()

                except json.JSONDecodeError as e:
                    logger.error(f"JSON 解析錯誤: {e}")
                    error_response = {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {
                            "code": ErrorCode.PARSE_ERROR.value,
                            "message": "JSON 解析錯誤"
                        }
                    }
                    writer.write(json.dumps(error_response) + "\n")
                    writer.flush()
                except Exception as e:
                    logger.error(f"未預期錯誤: {e}")
                    break
        finally:
            # 清理資源
            await self.cleanup()

        logger.info("MCP 功能服務器停止")

    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """處理 JSON-RPC 請求"""
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        try:
            if method not in self.handlers:
                raise JSONRPCError(
                    ErrorCode.METHOD_NOT_FOUND.value,
                    f"方法不存在: {method}"
                )

            handler = self.handlers[method]
            result = await handler(params)

            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result
            }
        except JSONRPCError as e:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": e.code,
                    "message": e.message,
                    "data": e.data
                }
            }
        except Exception as e:
            logger.error(f"處理請求錯誤: {e}")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": ErrorCode.INTERNAL_ERROR.value,
                    "message": str(e)
                }
            }

    

    async def run(self):
        """透過 stdio 運行服務器"""
        logger.info("MCP 功能服務器透過 stdio 啟動")

        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

        writer = sys.stdout

        while True:
            try:
                # 讀取請求
                line = await reader.readline()
                if not line:
                    break

                request_data = json.loads(line.decode())

                # 處理請求
                response = await self.handle_request(request_data)

                # 寫入響應
                response_line = json.dumps(response, ensure_ascii=False) + "\n"
                writer.write(response_line)
                writer.flush()

            except json.JSONDecodeError as e:
                logger.error(f"JSON 解析錯誤: {e}")
                error_response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": ErrorCode.PARSE_ERROR.value,
                        "message": "JSON 解析錯誤"
                    }
                }
                writer.write(json.dumps(error_response) + "\n")
                writer.flush()
            except Exception as e:
                logger.error(f"未預期錯誤: {e}")
                break

        logger.info("MCP 功能服務器停止")


async def main():
    """主程序入口"""
    server = FeaturesMCPServer()
    await server.run()


if __name__ == "__main__":
    # 執行主程序
    asyncio.run(main())
