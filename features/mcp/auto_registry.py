"""
MCP 工具自動註冊機制
支援從配置文件和目錄自動掃描並註冊工具
"""

import json
import importlib
import inspect
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Type, Union
from .types import Tool
from .mcp_client import MCPClientManager

logger = logging.getLogger("mcp.auto_registry")


class MCPAutoRegistry:
    """MCP 工具自動註冊器"""

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or "features/mcp_config.json"
        self.tools: Dict[str, Tool] = {}
        self.config: Dict[str, Any] = {}
        self.client_manager = MCPClientManager()
        self._disabled_tools = set()

        # 載入配置
        self._load_config()

    def _load_config(self):
        """載入配置文件"""
        try:
            config_file = Path(self.config_path)
            if config_file.exists():
                with open(config_file, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
                logger.info(f"載入配置文件: {self.config_path}")
            else:
                logger.warning(f"配置文件不存在: {self.config_path}")
                self.config = {}
        except Exception as e:
            logger.error(f"載入配置文件失敗: {e}")
            self.config = {}

    def discover_tools_from_directory(self, tools_dir: str = "features.mcp.tools") -> List[Tool]:
        """從目錄自動掃描工具"""
        discovered_tools = []

        try:
            # 動態導入 tools 模組
            tools_module = importlib.import_module(tools_dir)
            tools_path = Path(tools_module.__file__).parent

            logger.info(f"掃描工具目錄: {tools_path}")

            # 掃描所有 Python 文件（包含 *_tool.py 和 tdx_*.py）
            tool_files = list(tools_path.glob("*_tool.py")) + list(tools_path.glob("tdx_*.py"))
            # 去重（避免 tdx_*_tool.py 被掃描兩次）
            tool_files = list(set(tool_files))
            
            for py_file in tool_files:
                tool_name = py_file.stem
                module_name = f"{tools_dir}.{tool_name}"

                try:
                    # 動態導入模組
                    module = importlib.import_module(module_name)

                    # 尋找工具類別 (以Tool結尾的類)
                    for name, obj in inspect.getmembers(module, inspect.isclass):
                        if name.endswith('Tool') and hasattr(obj, 'get_definition'):
                            # 跳過抽象類
                            if inspect.isabstract(obj):
                                logger.debug(f"跳過抽象類: {name}")
                                continue

                            # 檢查是否已經在配置中定義且有 module/class 路徑
                            definition = obj.get_definition()
                            tool_config = self.config.get("tools", {}).get(definition['name'], {})

                            # 如果配置中有 module 和 class，優先使用配置掃描
                            # 但是不跳過，讓兩種方式都能發現工具，最後會去重
                            # if tool_config.get("module") and tool_config.get("class"):
                            #     logger.debug(f"工具 {definition['name']} 在配置中有 module/class 定義，跳過目錄掃描")
                            #     continue

                            # 創建標準化工具實例
                            if definition["name"] in self._disabled_tools:
                                logger.info(f"跳過已禁用工具: {definition['name']}")
                                continue

                            tool_instance = obj()
                            tool = self._create_tool_from_instance(tool_instance, definition)
                            if tool:
                                discovered_tools.append(tool)
                                logger.info(f"從目錄發現工具: {tool.name} (來源: {module_name}.{name})")

                except Exception as e:
                    logger.error(f"導入工具模組失敗 {module_name}: {e}")

        except Exception as e:
            logger.error(f"掃描工具目錄失敗: {e}")

        return discovered_tools

    def discover_tools_from_config(self) -> List[Tool]:
        """從配置文件發現工具"""
        discovered_tools = []

        tools_config = self.config.get("tools", {})

        for tool_name, tool_info in tools_config.items():
            try:
                # 檢查是否有模組路徑
                module_path = tool_info.get("module")
                class_name = tool_info.get("class")

                if module_path and class_name:
                    # 從配置指定的模組載入
                    if tool_name in self._disabled_tools:
                        logger.info(f"跳過已禁用工具: {tool_name}")
                        continue
                    tool = self._create_tool_from_config(tool_name, tool_info)
                    if tool:
                        discovered_tools.append(tool)
                        logger.info(f"從配置載入工具: {tool_name}")
                else:
                    # 對於沒有 module/class 的工具（系統工具），創建占位符工具
                    # 這些工具的實際處理邏輯會在 FeaturesMCPServer 中實現
                    tool = self._create_placeholder_tool(tool_name, tool_info)
                    if tool:
                        discovered_tools.append(tool)
                        logger.info(f"從配置創建系統工具占位符: {tool_name}")

            except Exception as e:
                logger.error(f"從配置載入工具失敗 {tool_name}: {e}")

        return discovered_tools

    def _create_tool_from_class(self, tool_class: Type) -> Optional[Tool]:
        """從類別創建工具"""
        try:
            # 獲取工具定義
            definition = tool_class.get_definition()
            if definition["name"] in self._disabled_tools:
                logger.info(f"跳過已禁用工具: {definition['name']}")
                return None

            # 檢查是否有模組級別的execute函數
            module = inspect.getmodule(tool_class)
            handler = None

            if module and hasattr(module, 'execute'):
                # 使用模組級別的execute函數
                handler = module.execute
            else:
                # 檢查 execute 是否為 classmethod
                execute_method = getattr(tool_class, 'execute', None)
                if execute_method and isinstance(inspect.getattr_static(tool_class, 'execute'), classmethod):
                    # execute 是 classmethod，直接調用類別方法
                    async def classmethod_wrapper(arguments):
                        return await tool_class.execute(arguments)
                    handler = classmethod_wrapper
                else:
                    # 使用類別的execute方法（需要實例化）
                    async def instance_wrapper(arguments):
                        instance = tool_class()
                        return await instance.execute(arguments)
                    handler = instance_wrapper

            # 創建工具實例，包含metadata
            tool = Tool(
                name=definition["name"],
                description=definition["description"],
                inputSchema=definition["inputSchema"],
                handler=handler,
                metadata=definition.get("metadata", {})
            )

            return tool

        except Exception as e:
            logger.error(f"從類別創建工具失敗 {tool_class.__name__}: {e}")
            return None

    def _create_tool_from_instance(self, tool_instance: Any, definition: Dict[str, Any]) -> Optional[Tool]:
        """從工具實例創建標準化工具"""
        try:
            # 檢查實例是否是標準化的MCPTool
            if hasattr(tool_instance, 'execute_safe'):
                # 使用標準化的execute_safe方法
                async def handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
                    return await tool_instance.execute_safe(arguments)

                tool = Tool(
                    name=definition["name"],
                    description=definition["description"],
                    inputSchema=definition["inputSchema"],
                    handler=handler,
                    metadata=definition.get("metadata", {})
                )
                return tool
            else:
                # 舊式工具實例，使用傳統的execute方法
                async def handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
                    return await tool_instance.execute(arguments)

                tool = Tool(
                    name=definition["name"],
                    description=definition["description"],
                    inputSchema=definition["inputSchema"],
                    handler=handler,
                    metadata=definition.get("metadata", {})
                )
                return tool

        except Exception as e:
            logger.error(f"從實例創建工具失敗 {tool_instance.__class__.__name__}: {e}")
            return None

    def _create_tool_from_config(self, tool_name: str, tool_info: Dict[str, Any]) -> Optional[Tool]:
        """從配置創建工具"""
        try:
            module_path = tool_info.get("module")
            class_name = tool_info.get("class")

            if not module_path or not class_name:
                logger.error(f"配置中缺少 module 或 class 路徑: {tool_name}")
                return None

            # 動態導入模組
            module = importlib.import_module(module_path)

            # 獲取工具類別
            tool_class = getattr(module, class_name, None)
            if not tool_class:
                logger.error(f"在模組 {module_path} 中找不到類別 {class_name}")
                return None

            # 創建工具實例
            tool_instance = tool_class()

            # 獲取工具定義
            definition = tool_class.get_definition()

            # 創建標準化工具
            tool = self._create_tool_from_instance(tool_instance, definition)

            if tool:
                logger.info(f"從配置成功創建工具: {tool_name} ({module_path}.{class_name})")
                return tool
            else:
                logger.error(f"從實例創建工具失敗: {tool_name}")
                return None

        except Exception as e:
            logger.error(f"從配置創建工具失敗 {tool_name}: {e}")
            return None

    def _create_placeholder_tool(self, tool_name: str, tool_info: Dict[str, Any]) -> Optional[Tool]:
        """創建系統工具占位符"""
        try:
            name = tool_info.get("name", tool_name)
            description = tool_info.get("description", "")
            category = tool_info.get("category", "system")
            examples = tool_info.get("examples", [])

            # 系統工具的基本輸入模式（空參數）
            input_schema = {
                "type": "object",
                "properties": {},
                "required": []
            }

            # 系統工具的 metadata
            metadata = {
                "category": category,
                "examples": examples,
                "is_system_tool": True,  # 標記為系統工具
                "source": "config_placeholder"
            }

            # 創建占位符處理器（會被 FeaturesMCPServer 替換）
            async def placeholder_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
                return {
                    "success": False,
                    "error": f"系統工具 {name} 的處理邏輯尚未初始化，請聯繫管理員"
                }

            tool = Tool(
                name=name,
                description=description,
                inputSchema=input_schema,
                handler=placeholder_handler,
                metadata=metadata
            )

            logger.info(f"創建系統工具占位符: {name}")
            return tool

        except Exception as e:
            logger.error(f"創建系統工具占位符失敗 {tool_name}: {e}")
            return None

    def auto_discover(self,
                     scan_directories: bool = True,
                     scan_config: bool = True,
                     scan_external: bool = True) -> List[Tool]:
        """自動發現所有工具"""
        all_tools = []

        if scan_directories:
            dir_tools = self.discover_tools_from_directory()
            all_tools.extend(dir_tools)

        if scan_config:
            config_tools = self.discover_tools_from_config()
            all_tools.extend(config_tools)

        if scan_external:
            # 發現外部服務器
            external_servers = self.discover_external_servers()
            if external_servers:
                logger.info(f"發現外部 MCP 服務器: {', '.join(external_servers)}")

                # 獲取外部工具
                external_tools = list(self.client_manager.get_all_tools().values())
                all_tools.extend(external_tools)
                logger.info(f"從外部服務器獲取 {len(external_tools)} 個工具")

        # 去重 (基於工具名稱)
        unique_tools = {}
        for tool in all_tools:
            if tool.name not in unique_tools:
                unique_tools[tool.name] = tool
            else:
                logger.warning(f"工具名稱重複，跳過: {tool.name}")

        final_tools = list(unique_tools.values())
        logger.info(f"自動發現完成，總計 {len(final_tools)} 個工具")

        return final_tools

    async def auto_discover_async(self,
                     scan_directories: bool = True,
                     scan_config: bool = True,
                     scan_external: bool = True) -> List[Tool]:
        """異步自動發現所有工具"""
        all_tools = []

        if scan_directories:
            dir_tools = self.discover_tools_from_directory()
            all_tools.extend(dir_tools)

        if scan_config:
            config_tools = self.discover_tools_from_config()
            all_tools.extend(config_tools)

        if scan_external:
            # 發現外部服務器
            external_servers = self.discover_external_servers()
            if external_servers:
                logger.info(f"發現外部 MCP 服務器: {', '.join(external_servers)}")

                # 外部工具已經在register_external_mcp_server中註冊到client_manager
                # 這裡不需要額外處理，因為工具會在客戶端啟動時自動發現

        # 去重 (基於工具名稱，配置文件優先)
        unique_tools = {}
        for tool in all_tools:
            if tool.name not in unique_tools:
                unique_tools[tool.name] = tool
            else:
                # 如果是重複的，保留配置文件中的版本（通常在列表後面）
                current_tool = unique_tools[tool.name]
                if hasattr(current_tool, 'metadata') and current_tool.metadata:
                    if current_tool.metadata.get('source') == 'config_placeholder':
                        # 當前工具是系統占位符，替換為實際工具
                        unique_tools[tool.name] = tool
                        logger.debug(f"替換系統占位符工具: {tool.name}")
                    else:
                        logger.debug(f"保留現有工具定義: {tool.name}")
                else:
                    logger.debug(f"保留現有工具定義: {tool.name}")

        # 添加外部工具
        external_tools = self.client_manager.get_all_tools()
        for tool_name, tool in external_tools.items():
            if tool_name not in unique_tools:
                unique_tools[tool_name] = tool
            else:
                logger.debug(f"外部工具已存在，跳過: {tool_name}")

        final_tools = list(unique_tools.values())
        logger.info(f"自動發現完成，總計 {len(final_tools)} 個工具")

        return final_tools

    def register_external_mcp_server(self, server_name: str, server_config: Dict[str, Any]) -> bool:
        """註冊外部 MCP 服務器 (如 Playwright) - 僅記錄配置"""
        try:
            # 檢查是否啟用
            if not server_config.get("enabled", False):
                logger.debug(f"外部 MCP 服務器 {server_name} 被禁用")
                return False

            # 記錄配置，稍後由應用啟動
            if not hasattr(self, '_external_servers'):
                self._external_servers = {}
            self._external_servers[server_name] = server_config

            logger.info(f"註冊外部 MCP 服務器配置: {server_name}")
            return True

        except Exception as e:
            logger.error(f"註冊外部 MCP 服務器失敗 {server_name}: {e}")
            return False

    async def start_external_servers(self):
        """啟動所有已註冊的外部服務器"""
        if not hasattr(self, '_external_servers'):
            return

        for server_name, server_config in self._external_servers.items():
            try:
                logger.info(f"啟動外部 MCP 服務器: {server_name}")
                success = await self.client_manager.start_client(server_name, server_config)
                if success:
                    logger.info(f"外部 MCP 服務器 {server_name} 啟動成功")
                else:
                    logger.error(f"外部 MCP 服務器 {server_name} 啟動失敗")
            except Exception as e:
                logger.error(f"啟動外部 MCP 服務器 {server_name} 時發生錯誤: {e}")

    def get_external_servers(self) -> Dict[str, Dict[str, Any]]:
        """獲取已註冊的外部服務器配置"""
        return getattr(self, '_external_servers', {})

    def discover_external_servers(self) -> List[str]:
        """發現外部 MCP 服務器"""
        external_servers = []

        mcp_servers = self.config.get("mcpServers", {})

        for server_name, server_config in mcp_servers.items():
            if server_name != "features-server":  # 跳過自己
                # 檢查是否啟用
                if not server_config.get("enabled", False):
                    logger.debug(f"外部 MCP 服務器 {server_name} 被禁用，跳過")
                    continue

                success = self.register_external_mcp_server(server_name, server_config)
                if success:
                    external_servers.append(server_name)

        return external_servers

    async def cleanup(self):
        """清理資源，停止所有外部客戶端"""
        await self.client_manager.stop_all()
        logger.info("MCP 自動註冊器清理完成")
