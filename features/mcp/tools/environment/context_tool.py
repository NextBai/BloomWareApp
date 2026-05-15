import json
from ..base_tool import MCPTool, StandardToolSchemas, ExecutionError

class EnvironmentContextTool(MCPTool):
    NAME = "environment_context"
    DESCRIPTION = (
        "Return the latest injected environment context for the current user. "
        "The main agent receives this context every turn; use this tool only "
        "when a workflow explicitly needs the raw environment payload."
    )
    CATEGORY = "environment"
    TAGS = ["environment", "context", "location", "timezone", "locale"]
    KEYWORDS = ["environment", "context", "location", "timezone", "locale", "環境", "位置", "時區"]

    @classmethod
    def get_input_schema(cls) -> dict:
        return {
            "type": "object",
            "properties": {
                "_user_id": {
                    "type": "string",
                    "description": "Injected by the server-side tool coordinator."
                }
            },
            "required": [],
            "additionalProperties": True
        }

    @classmethod
    def get_output_schema(cls) -> dict:
        schema = StandardToolSchemas.create_output_schema()
        schema["properties"].update({
            "data": {"type": "object"}
        })
        return schema

    @classmethod
    def get_definition(cls) -> dict:
        return {
            "name": cls.NAME,
            "description": cls.DESCRIPTION,
            "inputSchema": cls.get_input_schema(),
            "outputSchema": cls.get_output_schema(),
        }

    @classmethod
    async def execute(cls, arguments: dict) -> dict:
        try:
            user_id = (arguments or {}).get("_user_id")
            if not user_id:
                return {
                    "success": False,
                    "error": "environment_context requires an injected _user_id"
                }

            from core.database import get_user_env_current

            env_res = await get_user_env_current(user_id)
            if not env_res.get("success"):
                return {
                    "success": False,
                    "error": env_res.get("error") or "environment context is unavailable"
                }

            context = env_res.get("context") or {}
            return {
                "success": True,
                "content": json.dumps(context, ensure_ascii=False),
                "data": context,
            }
        except Exception as e:
            raise ExecutionError(str(e))
