"""
MCP 功能服務器 - 符合 2025 年最新 MCP 標準
整合所有天氣、新聞、匯率功能為 MCP Tools
"""

import json
import sys
import asyncio
import logging
from typing import Dict, Any, List, Optional, Callable
from enum import Enum
from .types import Tool
from .auto_registry import MCPAutoRegistry

logger = logging.getLogger("mcp.server")

# 設置日誌級別
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


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
                    handler=handler
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

                # 統一回應格式
                if isinstance(result, dict) and result.get("success"):
                    content = result.get("content", "")
                    return {"content": [{"type": "text", "text": content}]}
                elif isinstance(result, dict) and not result.get("success"):
                    error_msg = result.get("error", "工具執行失敗")
                    return {"content": [{"type": "text", "text": f"❌ {error_msg}"}], "isError": True}
                else:
                    return {"content": [{"type": "text", "text": str(result)}]}

            except Exception as e:
                logger.error(f"工具執行錯誤 {tool_name}: {e}")
                return {"content": [{"type": "text", "text": f"❌ 執行錯誤: {str(e)}"}], "isError": True}

        return {"content": [{"type": "text", "text": "工具未實作"}]}

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