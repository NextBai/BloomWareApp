import asyncio
import logging
import re
from typing import Any, Awaitable, Callable, Dict, Optional

from .tool_models import ToolMetadata, ToolResult

try:
    import jsonschema
except ImportError:
    jsonschema = None

logger = logging.getLogger(__name__)

CITY_ALIASES = {
    "台北市": "台北",
    "臺北市": "臺北",
    "新北市": "新北",
    "桃園市": "桃園",
    "台中市": "台中",
    "臺中市": "臺中",
    "台南市": "台南",
    "臺南市": "臺南",
    "高雄市": "高雄",
    "新竹市": "新竹",
}

EnvProvider = Callable[[Optional[str]], Awaitable[Dict[str, Any]]]
ResultFormatter = Callable[[str, str, Dict[str, Any], str], Awaitable[str]]
ToolHandler = Callable[[Dict[str, Any]], Awaitable[Any]]
OutputSchemaProvider = Callable[[str], Optional[Dict[str, Any]]]


class ToolOutputValidationError(RuntimeError):
    """Raised when a tool result violates its declared outputSchema."""


class ToolCoordinator:
    """
    統一管理 MCP 工具調用：
    - 依 ToolMetadata 注入環境/預設值
    - 處理特殊流程（導航）
    - 統一結果格式
    """

    def __init__(
        self,
        *,
        env_provider: EnvProvider,
        tool_lookup: Callable[[str], Optional[ToolHandler]],
        formatter: ResultFormatter,
        output_schema_provider: Optional[OutputSchemaProvider] = None,
        failure_handlers: Optional[Dict[str, Callable[[Dict[str, Any], Exception], ToolResult]]] = None,
    ) -> None:
        self._env_provider = env_provider
        self._tool_lookup = tool_lookup
        self._formatter = formatter
        self._output_schema_provider = output_schema_provider
        self._metadata: Dict[str, ToolMetadata] = {}
        self._failure_handlers = failure_handlers or {}

    # ------------------------------------------------------------------ #
    def register(self, metadata: ToolMetadata) -> None:
        self._metadata[metadata.name] = metadata

    def get_metadata(self, name: str) -> Optional[ToolMetadata]:
        return self._metadata.get(name)

    # ------------------------------------------------------------------ #
    async def invoke(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        *,
        user_id: Optional[str],
        original_message: str,
    ) -> ToolResult:
        metadata = self._metadata.get(tool_name, ToolMetadata(name=tool_name))

        if metadata.flow == "navigation":
            return await self._handle_navigation(arguments, user_id, original_message, metadata)

        prepared_args = await self._prepare_arguments(arguments, metadata, user_id)
        raw_result = await self._execute(tool_name, prepared_args)
        return await self._format_result(tool_name, raw_result, metadata, original_message)

    async def _prepare_arguments(
        self,
        arguments: Dict[str, Any],
        metadata: ToolMetadata,
        user_id: Optional[str],
    ) -> Dict[str, Any]:
        merged = dict(metadata.defaults)
        merged.update(arguments or {})
        
        # 注入 user_id 到參數中，讓工具可以從 arguments 中讀取
        if user_id:
            merged["_user_id"] = user_id

        logger.info(f"📦 [Coordinator] 準備參數: tool={metadata.name}, user_id={user_id}, requires_env={metadata.requires_env}")

        if metadata.requires_env and user_id:
            env_ctx = await self._env_provider(user_id)
            logger.info(f"📦 [Coordinator] 環境資訊: {env_ctx}")
            if env_ctx:
                for field in metadata.requires_env:
                    val = merged.get(field)
                    # 如果參數已有值且不是預設佔位符（如 0 或空字串），則跳過注入
                    # 這是為了解決 GPT 可能會填入 0 作為座標佔位符的問題
                    if val is not None and val != 0 and val != "":
                        continue
                    env_value = env_ctx.get(field)
                    # 主欄位為 None 時，嘗試 fallback 欄位
                    if env_value is None and metadata.env_fallbacks.get(field):
                        for fallback_key in metadata.env_fallbacks[field]:
                            env_value = env_ctx.get(fallback_key)
                            if env_value is not None:
                                logger.info(f"📦 [Coordinator] 使用 fallback 注入: {field} ← {fallback_key}={env_value}")
                                break
                    # 只注入非 None 的值，避免覆蓋工具的預設值或觸發 schema 驗證錯誤
                    if env_value is not None:
                        env_value = self._normalize_env_value(field, env_value)
                        merged[field] = env_value
                        logger.info(f"📦 [Coordinator] 注入環境變數: {field}={env_value}")
        elif not user_id:
            logger.warning(f"⚠️ [Coordinator] user_id 為 None，無法注入環境變數")

        logger.info(f"📦 [Coordinator] 最終參數: {merged}")
        return merged

    @staticmethod
    def _normalize_env_value(field: str, value: Any) -> Any:
        if field != "city" or not isinstance(value, str):
            return value

        normalized = value.strip()
        if not normalized:
            return value

        if normalized in CITY_ALIASES:
            return CITY_ALIASES[normalized]

        exact_match = re.match(r"^(台北|臺北|新北|桃園|台中|臺中|台南|臺南|高雄|新竹)(?:市|縣)?$", normalized)
        if exact_match:
            return exact_match.group(1)

        return normalized

    async def _execute(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        handler = self._tool_lookup(tool_name)
        if not handler:
            raise RuntimeError(f"工具 {tool_name} 無可用 handler")

        retry_delays = [1, 2, 5]
        last_exc: Optional[BaseException] = None
        for attempt, delay in enumerate(retry_delays, start=1):
            try:
                result = await asyncio.wait_for(handler(arguments), timeout=30.0)
                if isinstance(result, dict):
                    self._validate_output(tool_name, result)
                    return result
                wrapped = {"success": True, "content": str(result)}
                self._validate_output(tool_name, wrapped)
                return wrapped
            except ToolOutputValidationError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning("工具 %s 執行失敗 (attempt=%s): %s", tool_name, attempt, exc)
                await asyncio.sleep(delay)
        handler = self._failure_handlers.get(tool_name)
        if handler and last_exc:
            return handler(arguments, last_exc)  # type: ignore[arg-type]
        raise RuntimeError(f"工具 {tool_name} 執行失敗：{last_exc}")  # type: ignore[arg-type]

    def _validate_output(self, tool_name: str, result: Dict[str, Any]) -> None:
        if not self._output_schema_provider or jsonschema is None:
            return

        schema = self._output_schema_provider(tool_name)
        if not schema:
            return

        try:
            jsonschema.validate(result, schema)
        except jsonschema.ValidationError as exc:
            field_path = ".".join(str(part) for part in exc.absolute_path)
            detail = f"{field_path}: {exc.message}" if field_path else exc.message
            raise ToolOutputValidationError(f"工具 {tool_name} 輸出格式不符合契約: {detail}") from exc

    async def _format_result(
        self,
        tool_name: str,
        result: Dict[str, Any],
        metadata: ToolMetadata,
        original_message: str,
    ) -> ToolResult:
        if isinstance(result, ToolResult):
            return result

        if result.get("success") and result.get("content"):
            message = str(result.get("content"))
        elif result.get("success"):
            message = "操作完成，但無額外內容。"
        else:
            raise RuntimeError(result.get("error") or f"{tool_name} 執行失敗")

        payload = {k: v for k, v in result.items() if k not in {"success", "content", "error"}}

        if metadata.enable_reformat:
            try:
                message = await self._formatter(tool_name, message, payload, original_message)
            except Exception as exc:  # noqa: BLE001
                logger.warning("AI 格式化失敗，改用原訊息：%s", exc)

        return ToolResult(
            name=tool_name,
            message=message,
            data=payload or None,
            raw=result,
        )

    # ------------------------------------------------------------------ #
    async def _handle_navigation(
        self,
        arguments: Dict[str, Any],
        user_id: Optional[str],
        original_message: str,
        metadata: ToolMetadata,
    ) -> ToolResult:
        geo_result = await self._execute(metadata.name, arguments or {})
        if not geo_result.get("success"):
            raise RuntimeError(geo_result.get("error") or "地點查詢失敗")

        data = geo_result.get("data") or {}
        best_match = data.get("best_match") or {}
        dest_lat = best_match.get("lat")
        dest_lon = best_match.get("lon")
        if dest_lat is None or dest_lon is None:
            return ToolResult(
                name=metadata.name,
                message=str(geo_result.get("content") or "找不到合適的目的地"),
                data=data,
                raw=geo_result,
            )

        env_ctx = await self._env_provider(user_id) if user_id else {}
        origin_lat = env_ctx.get("lat")
        origin_lon = env_ctx.get("lon")
        if origin_lat is None or origin_lon is None:
            return ToolResult(
                name=metadata.name,
                message=str(geo_result.get("content") or "取得目的地座標成功"),
                data=data,
                raw=geo_result,
                metadata={"note": "缺少目前位置，僅返回地點資訊"},
            )

        directions_args = {
            "origin_lat": float(origin_lat),
            "origin_lon": float(origin_lon),
            "dest_lat": float(dest_lat),
            "dest_lon": float(dest_lon),
            "origin_label": env_ctx.get("label") or env_ctx.get("address_display") or "目前位置",
            "dest_label": best_match.get("label") or arguments.get("query"),
            "mode": "foot-walking",
        }

        directions_meta = self._metadata.get("directions", ToolMetadata(name="directions"))
        prepared = await self._prepare_arguments(directions_args, directions_meta, user_id)
        directions_result = await self._execute("directions", prepared)
        return await self._format_result("directions", directions_result, directions_meta, original_message)
