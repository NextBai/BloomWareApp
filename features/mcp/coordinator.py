import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from .tool_models import ToolMetadata, ToolResult

logger = logging.getLogger(__name__)

EnvProvider = Callable[[Optional[str]], Awaitable[Dict[str, Any]]]
ResultFormatter = Callable[[str, str, Dict[str, Any], str], Awaitable[str]]
ToolHandler = Callable[[Dict[str, Any]], Awaitable[Any]]


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
        failure_handlers: Optional[Dict[str, Callable[[Dict[str, Any], Exception], ToolResult]]] = None,
    ) -> None:
        self._env_provider = env_provider
        self._tool_lookup = tool_lookup
        self._formatter = formatter
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
                    if merged.get(field) is not None:
                        continue
                    env_value = env_ctx.get(field)
                    # 只注入非 None 的值，避免覆蓋工具的預設值或觸發 schema 驗證錯誤
                    if env_value is not None:
                        merged[field] = env_value
                        logger.info(f"📦 [Coordinator] 注入環境變數: {field}={env_value}")
        elif not user_id:
            logger.warning(f"⚠️ [Coordinator] user_id 為 None，無法注入環境變數")

        logger.info(f"📦 [Coordinator] 最終參數: {merged}")
        return merged

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
                    return result
                return {"success": True, "content": str(result)}
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning("工具 %s 執行失敗 (attempt=%s): %s", tool_name, attempt, exc)
                await asyncio.sleep(delay)
        handler = self._failure_handlers.get(tool_name)
        if handler and last_exc:
            return handler(arguments, last_exc)  # type: ignore[arg-type]
        raise RuntimeError(f"工具 {tool_name} 執行失敗：{last_exc}")  # type: ignore[arg-type]

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
