"""
MCP 協議客戶端實作
支援與外部 MCP 服務器進行通信，動態發現和調用工具
"""

import asyncio
import json
import logging
import subprocess
import sys
import os
from typing import Dict, Any, List, Optional, Callable, Union
from pathlib import Path
import uuid
import time

from .types import Tool

logger = logging.getLogger("mcp.client")


class MCPClientError(Exception):
    """MCP 客戶端錯誤"""
    pass


class MCPClient:
    """MCP 協議客戶端"""

    def __init__(self, server_name: str, server_config: Dict[str, Any]):
        self.server_name = server_name
        self.server_config = server_config
        self.process: Optional[subprocess.Popen] = None
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.request_id = 0
        self.pending_requests: Dict[str, asyncio.Future] = {}
        self.tools: Dict[str, Tool] = {}
        self.connected = False
        self.initialized = False

    def _get_next_request_id(self) -> str:
        """獲取下一個請求ID"""
        self.request_id += 1
        return str(self.request_id)

    async def start(self) -> bool:
        """啟動 MCP 服務器進程"""
        try:
            command = self.server_config.get("command", "")
            args = self.server_config.get("args", [])
            env = self.server_config.get("env", {})

            if not command:
                raise MCPClientError(f"服務器 {self.server_name} 沒有指定命令")

            # 合併環境變數
            process_env = dict(os.environ)
            process_env.update(env)

            # 啟動進程
            cmd = [command] + args
            logger.info(f"啟動 MCP 服務器: {' '.join(cmd)}")

            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=process_env,
                text=False  # 使用二進制模式
            )

            # 創建異步流
            loop = asyncio.get_event_loop()
            self.reader = asyncio.StreamReader()
            reader_protocol = asyncio.StreamReaderProtocol(self.reader)
            await loop.connect_read_pipe(lambda: reader_protocol, self.process.stdout)

            # 啟動消息處理循環
            asyncio.create_task(self._message_loop())

            # 等待連接建立
            await asyncio.sleep(0.1)

            # 初始化服務器
            success = await self._initialize()
            if success:
                # 發現工具
                await self._discover_tools()
                self.connected = True
                logger.info(f"MCP 服務器 {self.server_name} 連接成功，發現 {len(self.tools)} 個工具")
                return True
            else:
                await self.stop()
                return False

        except Exception as e:
            logger.error(f"啟動 MCP 服務器失敗 {self.server_name}: {e}")
            await self.stop()
            return False

    async def stop(self):
        """停止 MCP 服務器"""
        self.connected = False
        self.initialized = False

        if self.process:
            try:
                self.process.terminate()
                await asyncio.wait_for(asyncio.sleep(1), timeout=2.0)
                if self.process.poll() is None:
                    self.process.kill()
            except Exception as e:
                logger.error(f"停止進程時發生錯誤: {e}")

        self.pending_requests.clear()
        self.tools.clear()

    async def _initialize(self) -> bool:
        """初始化 MCP 服務器"""
        try:
            response = await self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {"listChanged": True}
                },
                "clientInfo": {
                    "name": "mcp-client",
                    "version": "1.0.0"
                }
            })

            if response and response.get("result"):
                self.initialized = True
                logger.info(f"MCP 服務器 {self.server_name} 初始化成功")
                return True
            else:
                logger.error(f"MCP 服務器 {self.server_name} 初始化失敗")
                return False

        except Exception as e:
            logger.error(f"初始化 MCP 服務器失敗 {self.server_name}: {e}")
            return False

    async def _discover_tools(self):
        """發現服務器提供的工具"""
        try:
            response = await self._send_request("tools/list", {})

            if response and response.get("result"):
                tools_data = response["result"].get("tools", [])
                for tool_data in tools_data:
                    tool = self._create_tool_from_data(tool_data)
                    if tool:
                        self.tools[tool.name] = tool
                        logger.info(f"發現外部工具: {tool.name}")

        except Exception as e:
            logger.error(f"發現工具失敗 {self.server_name}: {e}")

    def _create_tool_from_data(self, tool_data: Dict[str, Any]) -> Optional[Tool]:
        """從工具數據創建 Tool 實例"""
        try:
            name = tool_data.get("name")
            description = tool_data.get("description", "")
            input_schema = tool_data.get("inputSchema", {"type": "object", "properties": {}})

            # 創建代理處理器
            async def tool_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
                return await self._call_tool(name, arguments)

            tool = Tool(
                name=name,
                description=description,
                inputSchema=input_schema,
                handler=tool_handler
            )

            return tool

        except Exception as e:
            logger.error(f"創建工具失敗: {e}")
            return None

    async def _call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """調用外部工具"""
        try:
            response = await self._send_request("tools/call", {
                "name": tool_name,
                "arguments": arguments
            })

            if response and response.get("result"):
                content = response["result"].get("content", [])
                return {
                    "success": True,
                    "content": "\n".join([item.get("text", "") for item in content if item.get("type") == "text"])
                }
            else:
                error = response.get("error", {}).get("message", "未知錯誤")
                return {
                    "success": False,
                    "error": error
                }

        except Exception as e:
            logger.error(f"調用工具失敗 {tool_name}: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def _send_request(self, method: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """發送 JSON-RPC 請求"""
        if not self.process or not self.initialized:
            return None

        request_id = self._get_next_request_id()
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params
        }

        # 創建等待響應的 Future
        future = asyncio.Future()
        self.pending_requests[request_id] = future

        try:
            # 發送請求
            request_json = json.dumps(request, ensure_ascii=False) + "\n"
            self.process.stdin.write(request_json.encode('utf-8'))
            self.process.stdin.flush()

            # 等待響應
            response = await asyncio.wait_for(future, timeout=30.0)
            return response

        except asyncio.TimeoutError:
            logger.error(f"請求超時: {method}")
            return None
        except Exception as e:
            logger.error(f"發送請求失敗: {e}")
            return None
        finally:
            # 清理
            self.pending_requests.pop(request_id, None)

    async def _message_loop(self):
        """消息處理循環"""
        try:
            while self.process and self.process.poll() is None:
                try:
                    # 讀取一行
                    line = await self.reader.readline()
                    if not line:
                        break

                    # 解析 JSON
                    message = json.loads(line.decode('utf-8'))

                    # 處理消息
                    await self._handle_message(message)

                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    logger.error(f"處理消息時發生錯誤: {e}")
                    break

        except Exception as e:
            logger.error(f"消息循環錯誤: {e}")
        finally:
            self.connected = False

    async def _handle_message(self, message: Dict[str, Any]):
        """處理接收到的消息"""
        try:
            # 檢查是否是響應
            if "id" in message and "result" in message or "error" in message:
                request_id = str(message["id"])
                if request_id in self.pending_requests:
                    future = self.pending_requests[request_id]
                    if not future.done():
                        future.set_result(message)

            # 處理服務器主動消息 (如工具列表變化通知)
            elif "method" in message:
                method = message.get("method")
                params = message.get("params", {})

                if method == "tools/listChanged":
                    # 工具列表發生變化，重新發現
                    logger.info(f"MCP 服務器 {self.server_name} 工具列表發生變化")
                    await self._discover_tools()

        except Exception as e:
            logger.error(f"處理消息失敗: {e}")


class MCPClientManager:
    """MCP 客戶端管理器"""

    def __init__(self):
        self.clients: Dict[str, MCPClient] = {}
        self.logger = logging.getLogger("mcp.client_manager")

    async def start_client(self, server_name: str, server_config: Dict[str, Any]) -> bool:
        """啟動 MCP 客戶端"""
        try:
            client = MCPClient(server_name, server_config)
            success = await client.start()

            if success:
                self.clients[server_name] = client
                self.logger.info(f"MCP 客戶端 {server_name} 啟動成功")
                return True
            else:
                self.logger.error(f"MCP 客戶端 {server_name} 啟動失敗")
                return False

        except Exception as e:
            self.logger.error(f"啟動 MCP 客戶端失敗 {server_name}: {e}")
            return False

    async def stop_client(self, server_name: str):
        """停止 MCP 客戶端"""
        if server_name in self.clients:
            client = self.clients[server_name]
            await client.stop()
            del self.clients[server_name]
            self.logger.info(f"MCP 客戶端 {server_name} 已停止")

    async def stop_all(self):
        """停止所有客戶端"""
        for server_name in list(self.clients.keys()):
            await self.stop_client(server_name)

    def get_client_tools(self, server_name: str) -> Dict[str, Tool]:
        """獲取客戶端的工具"""
        if server_name in self.clients:
            return self.clients[server_name].tools
        return {}

    def get_all_tools(self) -> Dict[str, Tool]:
        """獲取所有客戶端的工具"""
        all_tools = {}
        for server_name, client in self.clients.items():
            for tool_name, tool in client.tools.items():
                # 添加服務器前綴避免衝突
                prefixed_name = f"{server_name}_{tool_name}"
                all_tools[prefixed_name] = tool
        return all_tools

    def is_client_connected(self, server_name: str) -> bool:
        """檢查客戶端是否連接"""
        return server_name in self.clients and self.clients[server_name].connected