"""
標準化 MCP 工具基類
定義統一的輸入輸出格式和錯誤處理
"""

import json
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from datetime import datetime

try:
    import jsonschema
except ImportError:
    jsonschema = None

logger = logging.getLogger("mcp.tools.base")


class ToolError(Exception):
    """工具錯誤基類"""
    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


class ValidationError(ToolError):
    """參數驗證錯誤"""
    def __init__(self, field: str, message: str):
        super().__init__(
            code="VALIDATION_ERROR",
            message=f"參數 '{field}' 驗證失敗: {message}",
            details={"field": field}
        )


class ExecutionError(ToolError):
    """執行錯誤"""
    def __init__(self, message: str, cause: Optional[Exception] = None):
        super().__init__(
            code="EXECUTION_ERROR",
            message=message,
            details={"cause": str(cause) if cause else None}
        )


class MCPTool(ABC):
    """標準化 MCP 工具基類"""

    # 工具基本信息
    NAME: str = ""
    DESCRIPTION: str = ""
    DESCRIPTION_SHORT: str = ""  # 簡短描述（用於 Intent Detection，10-20 tokens）
    CATEGORY: str = "general"
    TAGS: List[str] = []
    KEYWORDS: List[str] = []  # 用於快速意圖匹配的關鍵字
    USAGE_TIPS: List[str] = []
    IS_COMPLEX: bool = False  # 標記是否為複雜工具（需要兩階段參數填充）

    @classmethod
    def get_summary(cls) -> Dict[str, Any]:
        """獲取工具摘要（用於 Intent Detection，減少 token 消耗）"""
        # 自動生成簡短描述（截取前 50 字元或使用自訂）
        short_desc = cls.DESCRIPTION_SHORT or (
            cls.DESCRIPTION[:47] + "..." if len(cls.DESCRIPTION) > 50 else cls.DESCRIPTION
        )
        
        summary = {
            "name": cls.NAME,
            "description": short_desc,
            "category": cls.CATEGORY,
            "keywords": cls.KEYWORDS,
            "is_complex": cls.IS_COMPLEX
        }
        
        # 簡單工具：提供簡化參數列表（只有參數名，不含詳細 schema）
        if not cls.IS_COMPLEX:
            try:
                schema = cls.get_input_schema()
                summary["params"] = list(schema.get("properties", {}).keys())
            except:
                summary["params"] = []
        
        return summary
    
    @classmethod
    def get_full_definition(cls) -> Dict[str, Any]:
        """獲取完整工具定義（用於實際調用，包含完整 schema）"""
        return {
            "name": cls.NAME,
            "description": cls.DESCRIPTION,
            "metadata": {
                "category": cls.CATEGORY,
                "tags": cls.TAGS,
                "keywords": cls.KEYWORDS,
                "is_complex": cls.IS_COMPLEX,
                "usage_tips": cls.USAGE_TIPS
            },
            "inputSchema": cls.get_input_schema(),
            "outputSchema": cls.get_output_schema()
        }

    @classmethod
    def get_definition(cls) -> Dict[str, Any]:
        """獲取工具定義（向後兼容，使用完整定義）"""
        return cls.get_full_definition()

    @classmethod
    @abstractmethod
    def get_input_schema(cls) -> Dict[str, Any]:
        """獲取輸入參數模式"""
        pass

    @classmethod
    @abstractmethod
    def get_output_schema(cls) -> Dict[str, Any]:
        """獲取輸出結果模式"""
        pass

    @classmethod
    def validate_input(cls, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """驗證和標準化輸入參數"""
        try:
            # 使用 JSON Schema 進行驗證
            import jsonschema

            schema = cls.get_input_schema()
            jsonschema.validate(arguments, schema)

            # 應用默認值
            validated_args = cls._apply_defaults(arguments, schema)

            return validated_args

        except jsonschema.ValidationError as e:
            raise ValidationError(e.absolute_path[0] if e.absolute_path else "unknown", str(e))
        except Exception as e:
            raise ValidationError("unknown", f"輸入驗證失敗: {str(e)}")

    @classmethod
    def _apply_defaults(cls, arguments: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
        """應用默認值"""
        result = arguments.copy()
        properties = schema.get("properties", {})

        for prop_name, prop_schema in properties.items():
            if prop_name not in result and "default" in prop_schema:
                result[prop_name] = prop_schema["default"]

        return result

    @classmethod
    async def execute_safe(cls, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """安全執行工具，包含錯誤處理"""
        try:
            # 驗證輸入
            validated_args = cls.validate_input(arguments)

            # 執行工具
            start_time = datetime.now()
            result = await cls.execute(validated_args)
            end_time = datetime.now()

            # 驗證輸出
            validated_result = cls.validate_output(result)

            # 添加元數據
            validated_result["metadata"] = validated_result.get("metadata", {})
            validated_result["metadata"].update({
                "tool_name": cls.NAME,
                "execution_time": (end_time - start_time).total_seconds(),
                "timestamp": end_time.isoformat()
            })

            return validated_result

        except ToolError:
            raise  # 重新拋出工具錯誤
        except Exception as e:
            logger.error(f"工具 {cls.NAME} 執行失敗: {e}")
            raise ExecutionError(f"工具執行失敗: {str(e)}", e)

    @classmethod
    def validate_output(cls, result: Dict[str, Any]) -> Dict[str, Any]:
        """驗證輸出結果"""
        if jsonschema is None:
            logger.warning(f"jsonschema 未安裝，跳過輸出驗證")
            return result

        try:
            schema = cls.get_output_schema()
            jsonschema.validate(result, schema)

            return result

        except jsonschema.ValidationError as e:
            logger.warning(f"工具 {cls.NAME} 輸出格式不符合規範: {e}")
            # 不拋出錯誤，只記錄警告，允許繼續執行
            return result
        except Exception as e:
            logger.warning(f"工具 {cls.NAME} 輸出驗證失敗: {e}")
            return result

    @classmethod
    @abstractmethod
    async def execute(cls, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """執行工具邏輯"""
        pass

    @classmethod
    def create_success_response(cls, content: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """創建成功的回應"""
        response = {
            "success": True,
            "content": content,
            "metadata": {
                "tool_name": cls.NAME,
                "category": cls.CATEGORY
            }
        }

        if data:
            response.update(data)

        return response

    @classmethod
    def create_error_response(cls, error: str, code: str = "UNKNOWN_ERROR") -> Dict[str, Any]:
        """創建錯誤的回應"""
        return {
            "success": False,
            "error": error,
            "error_code": code,
            "metadata": {
                "tool_name": cls.NAME,
                "category": cls.CATEGORY
            }
        }


class StandardToolSchemas:
    """標準工具模式定義"""

    @staticmethod
    def create_input_schema(properties: Dict[str, Any], required: Optional[List[str]] = None) -> Dict[str, Any]:
        """創建標準輸入模式"""
        schema = {
            "type": "object",
            "properties": properties
        }

        if required:
            schema["required"] = required

        return schema

    @staticmethod
    def create_output_schema() -> Dict[str, Any]:
        """創建標準輸出模式"""
        return {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "content": {"type": "string"},
                "error": {"type": ["string", "null"]},
                "error_code": {"type": ["string", "null"]},
                "metadata": {
                    "type": "object",
                    "properties": {
                        "tool_name": {"type": "string"},
                        "category": {"type": "string"},
                        "execution_time": {"type": "number"},
                        "timestamp": {"type": "string"}
                    }
                }
            },
            "required": ["success"]
        }