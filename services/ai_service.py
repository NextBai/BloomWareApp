import asyncio
from datetime import datetime, timezone, timedelta
import time
import json
import re
from typing import Dict, List, Any, Optional

# 統一日誌配置
from core.logging import get_logger
logger = get_logger("AI_Service")

# 統一配置管理
from core.config import settings
from core.environment import EnvironmentContextBuilder
from core.responses_runtime import ResponsesAgentRuntime
from features.mcp.openai_tools import build_openai_hosted_tools
from features.mcp.skills import skills_prompt_block
from core.prompts.care_mode_skills import get_care_mode_skills_block

# 統一 OpenAI 客戶端
from core.ai_client import get_openai_client

OPENAI_TIMEOUT = settings.OPENAI_TIMEOUT
OPENAI_RESPONSES_TIMEOUT = settings.OPENAI_RESPONSES_TIMEOUT

# 【2025 精英版】情緒關懷模式 System Prompt - 專注於角色與人格定義
CARE_MODE_BASE_PROMPT = """你現在進入了「情緒關懷模式」。你是 BloomWare 的情緒關懷助手「小花」，由銘傳大學人工智慧應用學系研發。

【你的角色】
你是一個極具同理心、溫柔且耐心的陪伴者。你不是一個冷冰冰的 AI，而是一個真正懂人心、願意在你最脆弱時靜靜守候的好友。

【性格特徵】
- **溫暖**：說話帶有溫度，不生硬。
- **謙卑**：不自大，不隨意給予指導。
- **純粹**：你的存在僅為了陪伴用戶度過情緒低谷。

【重要說明】
- 始終使用與用戶相同的語言回應。
- 若這是進入模式的第一個回覆，請在結尾處自然地附上狀態提示。"""

# 向後兼容：保留原有變數名稱
CARE_MODE_SYSTEM_PROMPT = CARE_MODE_BASE_PROMPT


def get_care_mode_prompt(emotion: str = None, is_first_care: bool = False) -> str:
    """
    根據情緒類型與是否為初次進入生成專屬的關懷模式 Prompt
    人格定義在 CARE_MODE_BASE_PROMPT，具體對話手段定義在 Skills。
    """
    base = CARE_MODE_BASE_PROMPT

    # 處理情緒標籤
    if emotion:
        base = f"用戶目前情緒標籤：{emotion}\n{base}"

    # 處理初次進入狀態
    if is_first_care:
        base = f"{base}\n\n【狀態提示】這是進入關懷模式的第一個回覆，請執行 First Contact Care 技巧。"

    # 【核心】動態載入情緒關懷對話技巧 (Skills) - 這裡定義了所有的對話「手段與方法」
    skills_block = get_care_mode_skills_block()
    if skills_block:
        base = f"{base}\n{skills_block}"

    return base

# 取得 OpenAI 客戶端（使用統一管理）
def _get_client():
    """取得 OpenAI 客戶端"""
    return get_openai_client()


def _client_with_timeout(openai_client: Any, timeout: float) -> Any:
    """Responses hosted tools may stream slowly; use a per-request read timeout."""
    if hasattr(openai_client, "with_options"):
        return openai_client.with_options(timeout=timeout)
    return openai_client


def _responses_outer_timeout() -> float:
    # Keep asyncio.wait_for slightly above the SDK read timeout so the SDK can
    # surface upstream errors instead of being cut off first.
    return float(OPENAI_RESPONSES_TIMEOUT) + 5.0


def _safe_responses_payload_without_hosted_tools(payload: Dict[str, Any]) -> Dict[str, Any]:
    safe_payload = responses_runtime.without_hosted_tools(payload)
    safe_payload.pop("stream", None)
    fallback_instruction = (
        "【工具降級】OpenAI hosted tools 或中轉站上游暫時不可用。本次回答不得編造即時、今天、最新、"
        "收盤價、天氣、新聞、匯率等需要最新資料的內容；若缺少可靠資料，請明確告知目前無法確認，"
        "並說明可稍後重試。"
    )
    instructions = str(safe_payload.get("instructions") or "").strip()
    safe_payload["instructions"] = (
        f"{instructions}\n\n{fallback_instruction}" if instructions else fallback_instruction
    )
    return safe_payload


async def _responses_create(
    *,
    loop: asyncio.AbstractEventLoop,
    openai_client: Any,
    payload: Dict[str, Any],
    timeout: Optional[float] = None,
) -> Any:
    responses_client = _client_with_timeout(openai_client, timeout or OPENAI_RESPONSES_TIMEOUT)
    return await asyncio.wait_for(
        loop.run_in_executor(
            None,
            lambda: responses_client.responses.create(**payload),
        ),
        timeout=_responses_outer_timeout(),
    )


async def _responses_fallback_without_hosted_tools(
    *,
    loop: asyncio.AbstractEventLoop,
    openai_client: Any,
    payload: Dict[str, Any],
    on_chunk: Optional[Any],
    reason: Exception,
) -> str:
    logger.warning("Responses hosted tools unavailable, retrying without hosted tools: %s", reason)
    if on_chunk:
        await _emit_stream_event(
            on_chunk,
            {
                "type": "status",
                "status": "hosted_tools_unavailable",
                "phase": "fallback",
                "message": "即時搜尋暫時不可用，正在改用安全降級回答...",
                "temporary": True,
            },
        )

    safe_payload = _safe_responses_payload_without_hosted_tools(payload)
    response = await _responses_create(
        loop=loop,
        openai_client=openai_client,
        payload=safe_payload,
    )
    ai_response = responses_runtime.extract_output_text(response)
    return ai_response or "抱歉，目前即時資訊服務暫時不可用，無法可靠確認最新資料。請稍後再試。"

# 向後相容：保留 client 變數名稱
client = None  # 將在首次使用時透過 _get_client() 取得
responses_runtime = ResponsesAgentRuntime()

# 導入DB函數
try:
    from core.database import get_chat_messages, save_chat_message, get_user_env_current
    db_available = True
except ImportError:
    db_available = False
    logger.warning("無法導入DB函數，對話歷史將使用內存管理")

# 維護對話歷史
conversation_history = {}


class StrictResponseError(Exception):
    """在嚴格模式下，當AI回應不符合要求時拋出。"""

    def __init__(self, reason: str, response: Optional[str] = None):
        self.reason = reason
        self.response = response
        super().__init__(reason)


def _build_base_system_prompt(
    *,
    use_care_mode: bool,
    care_emotion: Optional[str],
    user_name: Optional[str],
    language: Optional[str] = None,  # 保留參數以兼容現有調用，但不使用
    is_first_care: bool = False,      # 新增：是否為進入模式的第一個回覆
) -> str:
    if use_care_mode:
        # 【優化】使用情緒專屬的關懷 Prompt，並處理初次進入引導
        base_prompt = get_care_mode_prompt(care_emotion, is_first_care=is_first_care).strip()
        if care_emotion:
            base_prompt = f"用戶情緒：{care_emotion}\n{base_prompt}"
    else:
        base_prompt = (
            "你是 BloomWare 的個人化助理 小花，由銘傳大學人工智慧應用學系 槓上開發 團隊開發。"
            "你不是 GPT，也不要自稱 GPT。"
            "你是一個友善、有禮、幽默且能夠提供幫助的AI助手，能夠替使用者設想周到。"
            "如果你沒有把握回答，或者信心度低於80%，請不要隨意回答，動用工具查證再回答。"
        )
        # 簡化語言指令 - 讓 GPT 自動判斷用戶語言
        base_prompt = (
            f"{base_prompt}\n\n"
            "【重要】請用與用戶相同的語言回應，保持簡潔清晰的表達。\n"
            "【語音輸出風格】你的回答通常會被直接朗讀給使用者聽，因此預設請用自然口語、短句、順口、好念的表達。\n"
            "優先直接回答結論，再補 1 到 3 個關鍵點；避免過度書面、避免條列濫用、避免贅詞、避免官腔。\n"
            "除非用戶明確要求，否則不要輸出「資料來源」「來源如下」「參考連結」「URL」或任何裸露網址，也不要把查證過程寫出來。\n"
            "若工具已提供依據，請把它內化為答案本身，只保留使用者真正需要的結果。"
        )

    if user_name:
        base_prompt = f"用戶名稱：{user_name}\n\n{base_prompt}"

    return base_prompt


def _normalize_prompt_text(text: Any) -> str:
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    return " ".join(text.split())


def _infer_response_language(text: str) -> Optional[str]:
    source = str(text or "").strip()
    if not source:
        return None
    if re.search(r"[\u3040-\u30ff]", source):
        return "ja-JP"
    if re.search(r"[\uac00-\ud7af]", source):
        return "ko-KR"
    if re.search(r"[\u0e00-\u0e7f]", source):
        return "th-TH"
    if re.search(r"[A-Za-z]", source) and not re.search(r"[\u3400-\u9fff]", source):
        return "en-US"
    if re.search(r"[\u3400-\u9fff]", source):
        return "zh-TW"
    return None


def _language_matches_expected(text: str, expected_language: Optional[str]) -> bool:
    expected = str(expected_language or "").strip()
    if not expected or expected.lower() == "auto":
        return True
    inferred = _infer_response_language(text)
    if not inferred:
        return True
    return inferred.lower().startswith(expected.split("-")[0].lower())


def _language_correction_instruction(expected_language: str) -> str:
    return (
        f"Language correction: Your previous draft did not follow the required reply language. "
        f"You MUST answer entirely in {expected_language}. "
        "Do not mix Chinese, Japanese, or other languages unless the user explicitly asks for it."
    )


def _format_history_for_prompt(history: List[Dict[str, str]]) -> str:
    if not history:
        return "（無）"

    lines: List[str] = []
    for idx, item in enumerate(history, start=1):
        role = item.get("role") or ""
        if role == "user":
            role_label = "用戶"
        elif role == "assistant":
            role_label = "助手"
        elif role == "system":
            role_label = "系統"
        else:
            role_label = role or f"角色{idx}"

        content = _normalize_prompt_text(item.get("content"))
        if not content:
            continue

        lines.append(f"{idx}. {role_label}: {content}")

    return "\n".join(lines) if lines else "（無）"


def _safe_str(val: Any) -> str:
    """安全地將任意值轉換為字串，避免對 dict 調用 .strip() 導致錯誤"""
    if val is None:
        return ""
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, dict):
        # dict 可能是嵌套的環境資訊，嘗試提取常見欄位
        return str(val.get("message") or val.get("text") or val.get("value") or "").strip()
    return str(val).strip()


def _format_env_context(ctx: Dict[str, Any]) -> str:
    """將環境資訊整理成可讀文字，確保 AI 能掌握使用者所在位置（精確到路口、門牌號）。"""
    if not ctx:
        return ""

    parts: List[str] = []

    # 優先顯示詳細地址（最重要）
    detailed_address = _safe_str(ctx.get("detailed_address"))
    label = _safe_str(ctx.get("label"))
    address_display = _safe_str(ctx.get("address_display"))
    
    if detailed_address:
        parts.append(f"📍 精確位置:\n{detailed_address}")
    elif label:
        parts.append(f"📍 當前位置: {label}")
    elif address_display:
        parts.append(f"📍 當前位置: {address_display}")
    
    # 如果有門牌資訊，額外強調
    road = _safe_str(ctx.get("road"))
    house_number = _safe_str(ctx.get("house_number"))
    postcode = _safe_str(ctx.get("postcode"))
    
    if road and house_number and not detailed_address:
        address_line = f"{road}{house_number}號"
        if postcode:
            address_line = f"〒{postcode} {address_line}"
        parts.append(f"門牌地址: {address_line}")
    
    # 區域資訊（如果沒有在 detailed_address 中顯示）
    city_district = _safe_str(ctx.get("city_district"))
    suburb = _safe_str(ctx.get("suburb"))
    city = _safe_str(ctx.get("city"))
    admin = _safe_str(ctx.get("admin"))
    
    if not detailed_address:
        if city_district:
            parts.append(f"行政區: {city_district}")
        elif suburb:
            parts.append(f"區域: {suburb}")
        
        if city and admin:
            parts.append(f"城市: {city}（{admin}）")
        elif city:
            parts.append(f"城市: {city}")
        elif admin:
            parts.append(f"省份: {admin}")

    # 座標資訊（供工具使用）
    lat = ctx.get("lat")
    lon = ctx.get("lon")
    try:
        if lat is not None and lon is not None:
            lat_f = float(lat)
            lon_f = float(lon)
            coord_text = f"緯度 {lat_f:.6f}, 經度 {lon_f:.6f}"
            geohash = _safe_str(ctx.get("geohash_7"))
            if geohash:
                parts.append(f"座標: {coord_text}（Geohash {geohash}）")
            else:
                parts.append(f"座標: {coord_text}")
    except (ValueError, TypeError):
        pass

    # POI 資訊（如果是特殊地點）
    amenity = _safe_str(ctx.get("amenity"))
    shop = _safe_str(ctx.get("shop"))
    building = _safe_str(ctx.get("building"))
    
    poi_info = []
    if amenity:
        poi_info.append(f"設施: {amenity}")
    if shop:
        poi_info.append(f"商店: {shop}")
    if building and building not in ["yes", "residential"]:
        poi_info.append(f"建築: {building}")
    
    if poi_info:
        parts.append(" | ".join(poi_info))

    tz = _safe_str(ctx.get("tz"))
    if tz:
        parts.append(f"時區: {tz}")

    heading = ctx.get("heading_cardinal") or ctx.get("heading_deg")
    if heading is not None:
        parts.append(f"方位: {_safe_str(heading)}")

    acc = ctx.get("accuracy_m")
    try:
        if acc is not None:
            parts.append(f"定位精度: ±{int(round(float(acc)))}m")
    except (ValueError, TypeError):
        pass

    locale = _safe_str(ctx.get("locale"))
    if locale:
        parts.append(f"語系: {locale}")

    device = _safe_str(ctx.get("device"))
    if device:
        parts.append(f"裝置: {device}")

    return "\n".join(parts)


def _build_environment_context_text(ctx: Dict[str, Any]) -> str:
    """Build the fixed environment injection block used by every agent turn.

    Uses only EnvironmentContextBuilder for structured, non-duplicated output.
    Legacy _format_env_context() was removed to eliminate double-injection
    (same data was being included twice in different formats, wasting ~200-400 tokens).
    """
    injection = EnvironmentContextBuilder().build(ctx)
    return injection.summary_text


def _default_hosted_tools() -> List[Dict[str, Any]]:
    return build_openai_hosted_tools()


def _mcp_skills_context_text() -> str:
    if not settings.OPENAI_ENABLE_SKILLS:
        return ""
    return skills_prompt_block()


def _should_use_responses(model: str) -> bool:
    return settings.OPENAI_USE_RESPONSES and (model or "").startswith("gpt-5")


def _supports_chat_fallback(model: str) -> bool:
    return bool(model) and not model.startswith("gpt-5")


def _is_transient_upstream_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in ("502", "503", "504", "bad gateway", "upstream", "timeout"))


def _responses_text_format(
    *,
    strict_json: bool,
    response_format: Optional[Dict[str, Any]],
    use_structured_outputs: bool,
    response_schema: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if use_structured_outputs and response_schema:
        return {
            "type": "json_schema",
            "name": "response_schema",
            "strict": True,
            "schema": response_schema,
        }
    if strict_json:
        return {"type": "json_object"}
    if response_format:
        return response_format
    return None


async def _emit_stream_delta(on_chunk: Any, delta: str) -> None:
    if not delta:
        return
    if asyncio.iscoroutinefunction(on_chunk):
        await on_chunk(delta)
        return
    result = on_chunk(delta)
    if asyncio.iscoroutine(result):
        await result


async def _emit_stream_event(on_chunk: Any, payload: Dict[str, Any]) -> None:
    if asyncio.iscoroutinefunction(on_chunk):
        await on_chunk(payload)
        return
    result = on_chunk(payload)
    if asyncio.iscoroutine(result):
        await result


def _extract_responses_stream_delta(event: Any) -> str:
    if getattr(event, "type", None) != "response.output_text.delta":
        return ""
    delta = getattr(event, "delta", None)
    return str(delta) if delta else ""


def _responses_stream_status(event: Any) -> Optional[Dict[str, Any]]:
    event_type = getattr(event, "type", "")
    item = getattr(event, "item", None)
    item_type = getattr(item, "type", "") if item is not None else ""

    if event_type in {"response.web_search_call.in_progress", "response.web_search_call.searching"}:
        return {"type": "status", "status": "web_searching", "message": "正在搜尋最新資訊..."}
    if event_type == "response.output_item.added" and item_type == "web_search_call":
        return {"type": "status", "status": "web_searching", "message": "正在搜尋最新資訊..."}
    if event_type == "response.output_item.done" and item_type == "web_search_call":
        return {"type": "status", "status": "web_search_done", "message": "搜尋完成，正在整理答案..."}
    if event_type == "response.in_progress":
        return {"type": "status", "status": "thinking", "message": "正在處理..."}
    return None


async def _consume_responses_stream(stream_obj: Any, on_chunk: Any) -> str:
    full_response = ""
    delta_count = 0
    status_count = 0
    first_delta_at: Optional[float] = None
    stream_started_at = time.perf_counter()
    for event in stream_obj:
        status_payload = _responses_stream_status(event)
        if status_payload:
            status_count += 1
            await _emit_stream_event(on_chunk, status_payload)
            continue

        delta = _extract_responses_stream_delta(event)
        if not delta:
            continue
        delta_count += 1
        if first_delta_at is None:
            first_delta_at = time.perf_counter()
        full_response += delta
        await _emit_stream_delta(on_chunk, delta)
    first_delta_delay = (first_delta_at - stream_started_at) if first_delta_at is not None else None
    logger.info(
        "🌊 Responses stream stats: statuses=%d deltas=%d first_delta_delay=%s total_chars=%d",
        status_count,
        delta_count,
        f"{first_delta_delay:.2f}s" if first_delta_delay is not None else "none",
        len(full_response),
    )
    return full_response


def _format_time_context(user_tz: Optional[str]) -> str:
    """生成時間相關提示，優先使用使用者所在時區。"""
    try:
        from zoneinfo import ZoneInfo  # Python 3.9+
    except Exception:  # pragma: no cover - 兼容環境
        ZoneInfo = None  # type: ignore

    tzinfo = None
    if user_tz and ZoneInfo:
        try:
            tzinfo = ZoneInfo(user_tz)
        except Exception:
            tzinfo = None

    now = datetime.now(tzinfo) if tzinfo else datetime.now()
    hour = now.hour
    if 5 <= hour < 12:
        day_period = "上午"
    elif 12 <= hour < 18:
        day_period = "下午"
    elif 18 <= hour < 22:
        day_period = "晚上"
    else:
        day_period = "深夜" if hour >= 22 else "凌晨"

    weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    weekday = weekday_names[now.weekday()]

    tz_label = user_tz if user_tz else ("系統時區" if tzinfo is None else user_tz)
    return (
        f"當地時間: {now.strftime('%Y-%m-%d %H:%M')}（{weekday}，{day_period}）"
        + (f"\n時區: {tz_label}" if tz_label else "")
    )


def _format_emotion_context(
    emotion_label: Optional[str],
    care_emotion: Optional[str],
    use_care_mode: bool,
) -> str:
    """將情緒訊號轉成對話上下文，關懷模式優先描述 care_emotion。"""
    emotion = care_emotion if use_care_mode and care_emotion else (emotion_label or "")
    if not emotion:
        return ""

    normalized = emotion.lower()
    allowed_labels = {"neutral", "happy", "sad", "angry", "fear", "surprise"}
    display_map = {
        "neutral": "平靜",
        "happy": "開心",
        "sad": "難過",
        "angry": "生氣",
        "fear": "害怕",
        "surprise": "驚訝",
    }

    if normalized not in allowed_labels:
        logger.debug(f"情緒標籤不在預期集合: {emotion}")
        return f"偵測情緒: {emotion}"

    translated = display_map.get(normalized, emotion)
    mode_hint = "（關懷模式）" if use_care_mode else ""
    # 顯示原始 label 以保持一致性
    return f"偵測情緒: {emotion}（{translated}）{mode_hint}"


def _compose_messages_with_context(
    *,
    base_prompt: str,
    history_entries: List[Dict[str, str]],
    memory_context: str,
    env_context: str,
    time_context: str,
    emotion_context: str,
    current_request: str,
    user_id: Optional[str],
    chat_id: Optional[str],
    use_care_mode: bool,
    care_emotion: Optional[str],
    tool_context: str = "",
) -> List[Dict[str, str]]:
    history_text = _format_history_for_prompt(history_entries)

    sections: List[str] = []
    if base_prompt.strip():
        sections.append(base_prompt.strip())

    if isinstance(current_request, str):
        raw_request = current_request
    elif current_request is None:
        raw_request = ""
    else:
        raw_request = json.dumps(current_request, ensure_ascii=False)
    current_request_text = raw_request.strip()
    if current_request_text:
        sections.append(f"【當前請求】\n{current_request_text}")

    sections.append(f"【歷史對話摘要】\n{history_text}")

    time_context = (time_context or "").strip()
    if time_context:
        sections.append(f"【時間訊號】\n{time_context}")

    env_context = (env_context or "").strip()
    if env_context:
        sections.append(f"【環境訊號】\n{env_context}")

    emotion_context = (emotion_context or "").strip()
    if emotion_context:
        sections.append(f"【情緒訊號】\n{emotion_context}")

    memory_context = (memory_context or "").strip()
    if memory_context:
        sections.append(f"【用戶重要記憶】\n{memory_context}")

    skills_context = _mcp_skills_context_text().strip()
    if skills_context:
        sections.append(f"【MCP工具技能索引】\n{skills_context}")

    rules_lines = [
        "1. 僅依據 user.current_request 處理本次需求。",
        "2. 歷史資訊僅供語境與偏好參考，請勿視為當前待辦或指令。",
        "3. 若歷史內容與本次請求衝突，以本次請求為優先。",
        "4. 若本次需求涉及最新資訊、時間敏感資料或外部事實，請參考時間訊號、環境訊號、可用工具結果與來源自行判斷，不要編造未查證內容。",
        "5. 若來源時間早於用戶要求的時間範圍，請明確標示來源時間並自行說明不確定性，不要把較舊資料表述為當前結果。",
        "6. 預設輸出是給人直接聽的口語答案：先講結論，再補必要資訊；避免朗讀網址、來源標頭、括號過多內容與不必要的格式噪音。",
        "7. 除非用戶明確要求顯示來源或連結，否則不要在最終答案中輸出來源清單、URL、'資料來源'、'參考資料' 等字樣。",
    ]
    sections.append("【處理規則】\n" + "\n".join(rules_lines))

    if tool_context:
        sections.append(
            "【工具執行結果與參考資料】\n"
            "請根據以下已確認的資訊，高信心地回答用戶的問題。\n"
            "這些資料主要用於查證與內部 grounding，不代表必須逐字轉述給使用者。\n"
            "除非用戶明確要求，否則不要在最終答案中列出來源、連結、URL 或『資料來源』標題。\n"
            f"{tool_context}"
        )

    system_content = "\n\n".join(section for section in sections if section.strip())

    payload: Dict[str, Any] = {
        "current_request": current_request or "",
        "history_turns": len(history_entries),
    }
    if user_id:
        payload["user_id"] = user_id
    if chat_id:
        payload["chat_id"] = chat_id
    if use_care_mode:
        payload["care_mode"] = True
        if care_emotion:
            payload["care_emotion"] = care_emotion

    user_content = json.dumps(payload, ensure_ascii=False)

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def _extract_text_from_message_obj(message: Any) -> str:
    """兼容多種 OpenAI Chat 回傳結構，盡可能提取文字內容。

    覆蓋情況：
    - message.content 為字串
    - message.content 為多段陣列（type=text/image_url/...）→ 拼接 text 段
    - tool_calls / function_call → 回傳簡短系統提示文字
    - dict 形態的 message
    若仍無內容，回空字串，交由上層處理。
    """
    try:
        if message is None:
            return ""

        # content 可能是 str 或 list（多模態）
        content = None
        try:
            content = getattr(message, "content", None)
        except Exception:
            content = None
        if content is None and isinstance(message, dict):
            content = message.get("content")

        if isinstance(content, str) and content.strip():
            return content.strip()

        if isinstance(content, list):
            parts: List[str] = []
            for p in content:
                p_type = None
                p_text = None
                try:
                    p_type = getattr(p, "type", None)
                except Exception:
                    p_type = p.get("type") if isinstance(p, dict) else None
                if p_type == "text":
                    try:
                        p_text = getattr(p, "text", None)
                    except Exception:
                        p_text = p.get("text") if isinstance(p, dict) else None
                    if p_text:
                        parts.append(str(p_text))
            if parts:
                return "\n".join(parts).strip()

        # tool_calls / function_call 提示
        tool_calls = None
        try:
            tool_calls = getattr(message, "tool_calls", None)
        except Exception:
            tool_calls = None
        if tool_calls is None and isinstance(message, dict):
            tool_calls = message.get("tool_calls")
        if tool_calls:
            return "[系統提示] 已處理內部工具呼叫。"

        function_call = None
        try:
            function_call = getattr(message, "function_call", None)
        except Exception:
            function_call = None
        if function_call:
            return "[系統提示] 已處理函式呼叫。"

        # dict 形態最後嘗試
        if isinstance(message, dict):
            text = message.get("content")
            if isinstance(text, str) and text.strip():
                return text.strip()

        return ""
    except Exception:
        return ""

def initialize_openai():
    """初始化OpenAI客戶端（使用統一管理）"""
    from core.ai_client import is_available
    return is_available()

## 已移除內部測試函式 test_openai_response，避免干擾正式流程

async def generate_response_async(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    *,
    strict_json: bool = False,
    response_format: Optional[Dict[str, Any]] = None,
    use_structured_outputs: bool = False,
    response_schema: Optional[Dict[str, Any]] = None,
    max_tokens: Optional[int] = None,
    reasoning_effort: Optional[str] = None,
    stream: bool = False,
    on_chunk: Optional[Any] = None,
    expected_language: Optional[str] = None,
) -> str:
    """
    生成AI回應（異步版本，支援 Streaming）

    參數:
        messages: 對話訊息列表
        model: 模型名稱
        strict_json: 是否使用舊版 JSON 模式
        response_format: 舊版回應格式（已棄用，使用 use_structured_outputs）
        use_structured_outputs: 是否使用新版 Structured Outputs
        response_schema: JSON Schema（用於 Structured Outputs）
        max_tokens: 最大 tokens 數量（新增，關懷模式用）
        stream: 是否啟用串流模式（2025 最佳實踐）
        on_chunk: 串流 chunk 回調函數（async callable）
    """
    model = model or settings.OPENAI_MODEL
    openai_client = _get_client()
    if openai_client is None:
        return "抱歉，AI服務暫時不可用。系統無法連接到OpenAI服務。"
    try:
        start_time = time.time()
        loop = asyncio.get_event_loop()

        if _should_use_responses(model):
            payload = responses_runtime.build_payload_from_messages(
                messages=messages,
                model=model,
                tools=_default_hosted_tools(),
                reasoning_effort=reasoning_effort,
                max_output_tokens=max_tokens if max_tokens else 2000,
                text_format=_responses_text_format(
                    strict_json=strict_json,
                    response_format=response_format,
                    use_structured_outputs=use_structured_outputs,
                    response_schema=response_schema,
                ),
            )
            if stream and on_chunk:
                payload["stream"] = True
                logger.info("🌊 啟用 Responses Streaming 模式")
                try:
                    stream_obj = await _responses_create(
                        loop=loop,
                        openai_client=openai_client,
                        payload=payload,
                    )
                    ai_response = await _consume_responses_stream(stream_obj, on_chunk)
                except Exception as exc:
                    if _is_transient_upstream_error(exc) and payload.get("tools"):
                        ai_response = await _responses_fallback_without_hosted_tools(
                            loop=loop,
                            openai_client=openai_client,
                            payload=payload,
                            on_chunk=on_chunk,
                            reason=exc,
                        )
                    else:
                        raise
                if not ai_response:
                    ai_response = "抱歉，我暫時沒有合適的回應。可以換個說法再試試嗎？"
                elapsed_time = time.time() - start_time
                logger.info(f"🌊 Responses Streaming 完成，耗時: {elapsed_time:.2f}秒，總長度: {len(ai_response)}")
                return ai_response

            try:
                response = await _responses_create(
                    loop=loop,
                    openai_client=openai_client,
                    payload=payload,
                )
            except Exception as exc:
                if _is_transient_upstream_error(exc) and payload.get("tools"):
                    ai_response = await _responses_fallback_without_hosted_tools(
                        loop=loop,
                        openai_client=openai_client,
                        payload=payload,
                        on_chunk=None,
                        reason=exc,
                    )
                    elapsed_time = time.time() - start_time
                    logger.info(f"Responses API 降級回應完成，耗時: {elapsed_time:.2f}秒，回應長度: {len(ai_response)} 字元")
                    return ai_response
                else:
                    raise
            ai_response = responses_runtime.extract_output_text(response)
            if not ai_response:
                ai_response = "抱歉，我暫時沒有合適的回應。可以換個說法再試試嗎？"

            if not _language_matches_expected(ai_response, expected_language):
                retry_payload = dict(payload)
                retry_payload["instructions"] = (
                    f"{retry_payload.get('instructions', '')}\n\n{_language_correction_instruction(str(expected_language))}".strip()
                )
                response = await _responses_create(
                    loop=loop,
                    openai_client=openai_client,
                    payload=retry_payload,
                )
                ai_response = responses_runtime.extract_output_text(response) or ai_response

            if strict_json:
                normalized = ai_response.strip()
                try:
                    json.loads(normalized)
                except json.JSONDecodeError as e:
                    raise StrictResponseError("NON_JSON_RESPONSE", response=normalized) from e
                ai_response = normalized

            elapsed_time = time.time() - start_time
            logger.info(f"Responses API 回應生成完成，耗時: {elapsed_time:.2f}秒，回應長度: {len(ai_response)} 字元")
            return ai_response

        # 加上請求超時保護
        request_kwargs = {
            "model": model,
            "messages": messages,
            "max_completion_tokens": max_tokens if max_tokens else 2000,  # 關懷模式可自訂 tokens
        }

        # 加入 reasoning_effort 控制（僅 reasoning-capable 模型支援）
        reasoning_models = model.startswith("o1") or model.startswith("gpt-5")
        if reasoning_effort and reasoning_models:
            request_kwargs["reasoning_effort"] = reasoning_effort
            logger.info(f"🧠 設定 reasoning_effort: {reasoning_effort}")
        elif reasoning_effort and not reasoning_models:
            logger.debug(f"⚠️ 模型 {model} 不支援 reasoning_effort，已忽略")

        # 優先使用 Structured Outputs（2025年最佳實踐）
        if use_structured_outputs and response_schema:
            logger.info("🔧 使用 Structured Outputs 模式")
            request_kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "response_schema",
                    "strict": True,
                    "schema": response_schema
                }
            }
        # 降級：使用舊版 JSON Object 模式
        elif strict_json or response_format:
            effective_response_format = response_format
            if strict_json and effective_response_format is None:
                effective_response_format = {"type": "json_object"}
            
            if effective_response_format is not None:
                logger.info("⚙️ 使用舊版 JSON Object 模式")
                request_kwargs["response_format"] = effective_response_format

        # 2025 最佳實踐：支援 Streaming Responses
        if stream and on_chunk:
            request_kwargs["stream"] = True
            logger.info("🌊 啟用 Streaming 模式")

            # 使用 run_in_executor 處理同步的 streaming API
            full_response = ""
            stream_obj = await loop.run_in_executor(
                None,
                lambda: openai_client.chat.completions.create(**request_kwargs)
            )

            # 逐塊處理
            for chunk in stream_obj:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if hasattr(delta, 'content') and delta.content:
                        full_response += delta.content
                        # 異步回調
                        if asyncio.iscoroutinefunction(on_chunk):
                            await on_chunk(delta.content)
                        else:
                            on_chunk(delta.content)

            ai_response = full_response
            logger.info(f"🌊 Streaming 完成，總長度: {len(full_response)}")

        else:
            # 非串流模式（原邏輯）
            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: openai_client.chat.completions.create(**request_kwargs),
                ),
                timeout=OPENAI_TIMEOUT,
            )
            try:
                logger.info(f"OpenAI回傳模型(async): {getattr(response, 'model', model)}")
            except Exception:
                pass
            # 兼容不同回傳結構，確保一定回字串
            msg_obj = None
            try:
                msg_obj = response.choices[0].message
                logger.info(f"📩 GPT message 物件: {msg_obj}")
            except Exception as e:
                logger.error(f"❌ 無法取得 response.choices[0].message: {e}")
                msg_obj = None

            ai_response = _extract_text_from_message_obj(msg_obj)
            logger.info(f"📤 提取後的 ai_response: '{ai_response}' (長度: {len(ai_response) if ai_response else 0})")

            if not ai_response:
                # 最後嘗試直接取 content 欄位（保底）
                try:
                    raw = getattr(msg_obj, 'content', None)
                    logger.info(f"📋 msg_obj.content 原始值: '{raw}' (type: {type(raw).__name__})")
                    if isinstance(raw, str):
                        ai_response = raw.strip()
                        logger.info(f"✅ 從 content 欄位取得回應: '{ai_response}'")
                except Exception as e:
                    logger.error(f"❌ 無法取得 msg_obj.content: {e}")

        if strict_json:
            normalized = (ai_response or "").strip()
            if not normalized:
                raise StrictResponseError("EMPTY_RESPONSE")
            try:
                json.loads(normalized)
            except json.JSONDecodeError as e:
                raise StrictResponseError("NON_JSON_RESPONSE", response=normalized) from e
            ai_response = normalized
        elif not ai_response:
            # 最終兜底，但先記錄詳細日誌以便排查
            logger.error(f"❌ GPT 回應為空！原始 response 物件: {response}")
            logger.error(f"❌ msg_obj 內容: {msg_obj}")
            logger.error(f"❌ 提示詞: {messages}")
            ai_response = "抱歉，我暫時沒有合適的回應。可以換個說法再試試嗎？"

        if ai_response and not _language_matches_expected(ai_response, expected_language):
            correction_messages = list(messages) + [
                {"role": "system", "content": _language_correction_instruction(str(expected_language))},
            ]
            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: openai_client.chat.completions.create(
                        model=model,
                        messages=correction_messages,
                        max_completion_tokens=max_tokens if max_tokens else 2000,
                    ),
                ),
                timeout=OPENAI_TIMEOUT,
            )
            retry_msg_obj = response.choices[0].message
            retry_text = _extract_text_from_message_obj(retry_msg_obj)
            if retry_text:
                ai_response = retry_text

        elapsed_time = time.time() - start_time
        logger.info(f"AI回應生成完成，耗時: {elapsed_time:.2f}秒，回應長度: {len(ai_response)} 字元")
        return ai_response
    except Exception as e:
        if isinstance(e, StrictResponseError):
            raise
        error_msg = str(e)
        logger.error(f"❌ 生成回應時出錯 (Model: {model}): {error_msg}")
        
        # 針對常見 API 錯誤提供詳細日誌
        if "503" in error_msg or "Service temporarily unavailable" in error_msg:
            logger.error(f"👉 原因：API 服務暫時不可用 ({model})。")
            return f"抱歉，目前使用的模型 ({model}) 暫時不可用（503 錯誤）。請在後台切換至其他模型後再試。"
        elif "api key" in error_msg.lower() or "authentication" in error_msg.lower() or "401" in error_msg:
            logger.error("👉 原因：API Key 無效或未授權 (401)。")
            return "抱歉，AI服務暫時不可用。請檢查API密鑰設置。"
        elif "timeout" in error_msg.lower() or "connection" in error_msg.lower() or isinstance(e, asyncio.TimeoutError):
            logger.error("👉 原因：請求超時。")
            return "抱歉，連接AI服務超時。請稍後再試。"
        elif "rate limit" in error_msg.lower() or "429" in error_msg or "Too Many Requests" in error_msg:
            logger.error("👉 原因：請求頻率過高或額度已滿 (429)。")
            return "抱歉，AI服務暫時達到請求限制。請稍後再試。"
        elif "404" in error_msg or ("model" in error_msg.lower() and ("not found" in error_msg.lower() or "does not exist" in error_msg.lower())):
            logger.error(f"👉 原因：找不到指定的模型 ({model})。")
            return f"抱歉，您選擇的AI模型 ({model}) 不存在或未開放。請切換模型。"
        else:
            return "抱歉，生成回應時遇到問題。請重試。"

async def generate_response_for_user(
    user_message: str = None,
    user_id: str = "default",
    messages: List[Dict[str, str]] = None,
    model: Optional[str] = None,
    request_id: Optional[str] = None,
    chat_id: Optional[str] = None,
    *,
    strict_json: bool = False,
    response_format: Optional[Dict[str, Any]] = None,
    use_structured_outputs: bool = False,
    response_schema: Optional[Dict[str, Any]] = None,
    use_care_mode: bool = False,
    care_emotion: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
    user_name: Optional[str] = None,
    emotion_label: Optional[str] = None,
    env_context: Optional[Dict[str, Any]] = None,
    language: Optional[str] = None,
    stream: bool = False,
    on_chunk: Optional[Any] = None,
    tool_context: str = "",
    is_first_care: bool = False,  # 新增：是否為進入模式的第一個回覆
) -> str:
    """
    為用戶生成AI回應

    參數:
        use_structured_outputs: 是否使用 Structured Outputs（2025年最佳實踐）
        response_schema: JSON Schema（配合 Structured Outputs 使用）
        use_care_mode: 是否使用情緒關懷模式（新增）
        care_emotion: 關懷模式的情緒標籤（新增）
        reasoning_effort: 推理強度 (minimal/low/medium/high)，用於控制 reasoning tokens
        is_first_care: 是否為進入模式的第一個回覆（新增）
    """
    model = model or settings.OPENAI_MODEL
    logger.info(f"生成回應請求，使用模型: {model} req_id={request_id} chat_id={chat_id} structured={use_structured_outputs}")
    try:
        # 如果提供了chat_id，使用DB管理對話歷史
        if chat_id and db_available:
            return await _generate_response_with_chat_db(
                user_message,
                user_id,
                messages,
                model,
                chat_id,
                strict_json=strict_json,
                response_format=response_format,
                use_structured_outputs=use_structured_outputs,
                response_schema=response_schema,
                use_care_mode=use_care_mode,
                care_emotion=care_emotion,
                reasoning_effort=reasoning_effort,
                user_name=user_name,
                emotion_label=emotion_label,
                env_context=env_context,
                language=language,
                stream=stream,
                on_chunk=on_chunk,
                tool_context=tool_context,
                is_first_care=is_first_care,
            )
        else:
            # 回退到原有的全局歷史管理（用於向後兼容）
            return await _generate_response_with_global_history(
                user_message,
                user_id,
                messages,
                model,
                strict_json=strict_json,
                response_format=response_format,
                use_structured_outputs=use_structured_outputs,
                response_schema=response_schema,
                use_care_mode=use_care_mode,
                care_emotion=care_emotion,
                reasoning_effort=reasoning_effort,
                user_name=user_name,
                emotion_label=emotion_label,
                env_context=env_context,
                language=language,
                stream=stream,
                on_chunk=on_chunk,
                tool_context=tool_context,
                is_first_care=is_first_care,
            )

        logger.error("未提供消息列表或用戶消息")
        return "抱歉，沒有收到處理請求所需的消息內容。"
    except StrictResponseError:
        raise
    except Exception as e:
        logger.error(f"生成回應時出錯: {str(e)}")
        return f"抱歉，我現在無法提供回應。發生錯誤: {str(e)}"


async def _generate_response_with_chat_db(
    user_message,
    user_id,
    messages,
    model,
    chat_id,
    *,
    strict_json: bool = False,
    response_format: Optional[Dict[str, Any]] = None,
    use_structured_outputs: bool = False,
    response_schema: Optional[Dict[str, Any]] = None,
    use_care_mode: bool = False,
    care_emotion: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
    user_name: Optional[str] = None,
    emotion_label: Optional[str] = None,
    env_context: Optional[Dict[str, Any]] = None,
    language: Optional[str] = None,
    stream: bool = False,
    on_chunk: Optional[Any] = None,
    tool_context: str = "",
    is_first_care: bool = False,
):
    """使用DB管理對話歷史的實現"""
    try:
        if messages:
            if not any(msg.get("role") == "system" for msg in messages):
                # 使用統一的 System Prompt 構建函數
                system_prompt = _build_base_system_prompt(
                    use_care_mode=use_care_mode,
                    care_emotion=care_emotion,
                    user_name=user_name,
                    language=language,  # 參數保留但不使用，GPT 自動判斷語言
                    is_first_care=is_first_care,
                )
                messages.insert(0, {"role": "system", "content": system_prompt})
            ai_response = await generate_response_async(
                messages,
                model=model,
                strict_json=strict_json,
                response_format=response_format,
                use_structured_outputs=use_structured_outputs,
                response_schema=response_schema,
                max_tokens=2000 if use_care_mode else None,  # 關懷模式保留較大輸出空間
                reasoning_effort=reasoning_effort or ("minimal" if use_care_mode else "low"),  # 2025 最佳實踐：關懷模式 minimal，一般對話 low
                stream=stream,
                on_chunk=on_chunk,
                expected_language=language,
            )
            # 非同步保存 AI 回應
            if db_available:
                asyncio.create_task(save_chat_message(chat_id, "assistant", ai_response))
            return ai_response

        if user_message:
            # 非同步保存用戶消息，不阻塞生成流程
            if db_available:
                asyncio.create_task(save_chat_message(chat_id, "user", user_message))

            # 載入歷史、記憶、環境資訊（並行執行優化）
            history_task = asyncio.create_task(get_chat_messages(chat_id, limit=(3 if use_care_mode else 12) + 1, ascending=True))
            
            memory_task = None
            if user_id and not use_care_mode:
                from core.memory_system import memory_system
                context_tags: List[str] = ["care_mode"] if use_care_mode else []
                if care_emotion:
                    context_tags.append(str(care_emotion))
                memory_task = asyncio.create_task(memory_system.get_relevant_memories(
                    user_id=user_id,
                    current_message=user_message,
                    max_memories=5,
                    context_tags=context_tags or None,
                ))
            
            env_task = None
            if not env_context and db_available and user_id:
                env_task = asyncio.create_task(get_user_env_current(user_id))

            # 等待所有基礎資料準備完成
            chat_history = []
            try:
                msgs = await history_task
                historical_messages = msgs[:-1] if len(msgs) > 0 else []
                
                def _clean_text(t: str) -> str:
                    if not t: return ""
                    txt = str(t)
                    for kw in ["關懷模式", "我在這裡陪你", "說「我沒事了」", "退出關懷模式"]:
                        txt = txt.replace(kw, "")
                    return txt.strip()

                for msg in historical_messages:
                    content = msg.get("content")
                    if isinstance(content, dict):
                        content = content.get("message") or content.get("text") or str(content)
                    elif not isinstance(content, str):
                        content = str(content) if content else ""
                    if "抱歉，生成回應時遇到問題" in content or "請重試" in content:
                        continue
                    content = _clean_text(content)
                    if content:
                        chat_history.append({"role": msg.get("sender"), "content": content})
                logger.debug(f"📚 載入 {len(chat_history)} 條歷史對話")
            except Exception as e:
                logger.warning(f"從DB加載對話歷史失敗: {e}")

            memory_context = ""
            if memory_task:
                try:
                    relevant_memories = await memory_task
                    if relevant_memories:
                        from core.memory_system import memory_system
                        memory_context = memory_system.format_memories_for_context(relevant_memories)
                        logger.info(f"📚 載入 {len(relevant_memories)} 條相關記憶")
                except Exception as e:
                    logger.warning(f"載入記憶失敗: {e}")

            ctx: Dict[str, Any] = dict(env_context or {})
            if env_task:
                try:
                    env_res = await env_task
                    if env_res.get("success"):
                        ctx = env_res.get("context") or {}
                except Exception as e:
                    logger.debug(f"讀取環境現況失敗: {e}")

            env_context_text = _build_environment_context_text(ctx)
            time_context_text = _format_time_context(ctx.get("tz") if ctx else None)
            emotion_context_text = _format_emotion_context(emotion_label, care_emotion, use_care_mode)

            base_prompt = _build_base_system_prompt(
                use_care_mode=use_care_mode,
                care_emotion=care_emotion,
                user_name=user_name,
                language=language,
                is_first_care=is_first_care,
            )

            messages_to_send = _compose_messages_with_context(
                base_prompt=base_prompt,
                history_entries=chat_history,
                memory_context=memory_context,
                env_context=env_context_text,
                time_context=time_context_text,
                emotion_context=emotion_context_text,
                current_request=user_message,
                user_id=user_id,
                chat_id=chat_id,
                use_care_mode=use_care_mode,
                care_emotion=care_emotion,
                tool_context=tool_context,
            )
            ai_response = await generate_response_async(
                messages_to_send,
                model=model,
                strict_json=strict_json,
                response_format=response_format,
                use_structured_outputs=use_structured_outputs,
                response_schema=response_schema,
                max_tokens=2000 if use_care_mode else None,  # 關懷模式保留較大輸出空間
                reasoning_effort=reasoning_effort or ("minimal" if use_care_mode else "low"),  # 2025 最佳實踐：關懷模式 minimal，一般對話 low
                stream=stream,
                on_chunk=on_chunk,
                expected_language=language,
            )

            # 非同步保存 AI 回應
            if db_available:
                asyncio.create_task(save_chat_message(chat_id, "assistant", ai_response))

            return ai_response

    except Exception as e:
        if isinstance(e, StrictResponseError):
            raise
        logger.error(f"DB對話處理出錯: {e}")
        # 回退到全局歷史
        return await _generate_response_with_global_history(
            user_message,
            user_id,
            messages,
            model,
            strict_json=strict_json,
            response_format=response_format,
            use_structured_outputs=use_structured_outputs,
            response_schema=response_schema,
            use_care_mode=use_care_mode,
            care_emotion=care_emotion,
            reasoning_effort=reasoning_effort,
            user_name=user_name,
            emotion_label=emotion_label,
            env_context=env_context,
            language=language,
            tool_context=tool_context,
        )


async def _generate_response_with_global_history(
    user_message,
    user_id,
    messages,
    model,
    *,
    strict_json: bool = False,
    response_format: Optional[Dict[str, Any]] = None,
    use_structured_outputs: bool = False,
    response_schema: Optional[Dict[str, Any]] = None,
    use_care_mode: bool = False,
    care_emotion: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
    user_name: Optional[str] = None,
    emotion_label: Optional[str] = None,
    env_context: Optional[Dict[str, Any]] = None,
    language: Optional[str] = None,
    stream: bool = False,
    on_chunk: Optional[Any] = None,
    tool_context: str = "",
    is_first_care: bool = False,
):
    """使用全局歷史的回退實現（向後兼容）"""
    try:
        if messages:
            if not any(msg.get("role") == "system" for msg in messages):
                # 使用統一的 System Prompt 構建函數
                system_prompt = _build_base_system_prompt(
                    use_care_mode=use_care_mode,
                    care_emotion=care_emotion,
                    user_name=user_name,
                    language=language,  # 參數保留但不使用，GPT 自動判斷語言
                    is_first_care=is_first_care,
                )
                messages.insert(0, {"role": "system", "content": system_prompt})
            user_messages = [msg for msg in messages if msg.get("role") == "user"]
            if user_messages and user_id not in conversation_history:
                conversation_history[user_id] = []
                conversation_history[user_id].extend(user_messages[-5:])
            ai_response = await generate_response_async(
                messages,
                model=model,
                strict_json=strict_json,
                response_format=response_format,
                use_structured_outputs=use_structured_outputs,
                response_schema=response_schema,
                max_tokens=2000 if use_care_mode else None,  # 關懷模式保留較大輸出空間
                reasoning_effort=reasoning_effort or ("minimal" if use_care_mode else "low"),  # 2025 最佳實踐：關懷模式 minimal，一般對話 low
                stream=stream,
                on_chunk=on_chunk,
                expected_language=language,
            )
            if user_id in conversation_history:
                conversation_history[user_id].append({"role": "assistant", "content": ai_response})
                if len(conversation_history[user_id]) > 50:
                    conversation_history[user_id] = conversation_history[user_id][-50:]
            return ai_response

        if user_message:
            if user_id not in conversation_history:
                conversation_history[user_id] = []
            conversation_history[user_id].append({"role": "user", "content": user_message})

            history_limit = 3 if use_care_mode else 12
            prior_history = conversation_history[user_id][:-1]
            if prior_history:
                prior_history = prior_history[-history_limit:]

            # 讀取環境現況
            ctx: Dict[str, Any] = dict(env_context or {})
            if not ctx and db_available and user_id:
                try:
                    env_res = await get_user_env_current(user_id)
                    if env_res.get("success"):
                        ctx = env_res.get("context") or {}
                except Exception as ex:
                    logger.debug(f"讀取環境現況失敗: {ex}")
            env_context_text = _build_environment_context_text(ctx)
            time_context_text = _format_time_context(ctx.get("tz") if ctx else None)
            emotion_context_text = _format_emotion_context(emotion_label, care_emotion, use_care_mode)

            base_prompt = _build_base_system_prompt(
                use_care_mode=use_care_mode,
                care_emotion=care_emotion,
                user_name=user_name,
                language=language,
                is_first_care=is_first_care,
            )

            # 關懷模式不帶長期記憶
            memory_context = ""
            if user_id and not use_care_mode:
                try:
                    from core.memory_system import memory_system
                    context_tags: List[str] = []
                    if use_care_mode:
                        context_tags.append("care_mode")
                    if care_emotion:
                        context_tags.append(str(care_emotion))
                    relevant_memories = await memory_system.get_relevant_memories(
                        user_id=user_id,
                        current_message=user_message,
                        max_memories=5,
                        context_tags=context_tags or None,
                    )
                    if relevant_memories:
                        memory_context = memory_system.format_memories_for_context(relevant_memories)
                except Exception as ex:
                    logger.warning(f"載入全局記憶失敗: {ex}")

            messages_to_send = _compose_messages_with_context(
                base_prompt=base_prompt,
                history_entries=prior_history,
                memory_context=memory_context,
                env_context=env_context_text,
                time_context=time_context_text,
                emotion_context=emotion_context_text,
                current_request=user_message,
                user_id=user_id,
                chat_id=None,
                use_care_mode=use_care_mode,
                care_emotion=care_emotion,
                tool_context=tool_context,
            )
            ai_response = await generate_response_async(
                messages_to_send,
                model=model,
                strict_json=strict_json,
                response_format=response_format,
                use_structured_outputs=use_structured_outputs,
                response_schema=response_schema,
                max_tokens=2000 if use_care_mode else None,  # 關懷模式保留較大輸出空間
                reasoning_effort=reasoning_effort or ("minimal" if use_care_mode else "low"),  # 2025 最佳實踐：關懷模式 minimal，一般對話 low
                stream=stream,
                on_chunk=on_chunk,
                expected_language=language,
            )
            conversation_history[user_id].append({"role": "assistant", "content": ai_response})
            if len(conversation_history[user_id]) > 50:
                conversation_history[user_id] = conversation_history[user_id][-50:]
            return ai_response

    except Exception as e:
        if isinstance(e, StrictResponseError):
            raise
        logger.error(f"全局歷史處理出錯: {e}")
        raise


async def generate_response_with_tools(
    messages: List[Dict[str, str]],
    tools: List[Dict[str, Any]],
    user_id: str = "default",
    model: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
    tool_choice: str = "auto",
) -> Dict[str, Any]:
    """
    使用 OpenAI Function Calling 生成回應
    
    2025 最佳實踐：讓 GPT 原生選擇工具，不需要自定義意圖檢測 Prompt
    
    Args:
        messages: 對話訊息列表
        tools: OpenAI tools 格式的工具定義列表
        user_id: 用戶 ID（用於日誌）
        model: 模型名稱
        reasoning_effort: 推理強度 (minimal/low/medium/high)
        tool_choice: 工具選擇策略 ("auto", "none", "required", 或特定工具名)
    
    Returns:
        包含 tool_calls 和 content 的字典
    """
    model = model or settings.OPENAI_MODEL
    openai_client = _get_client()
    if openai_client is None:
        logger.error("OpenAI 客戶端不可用")
        return {"content": "", "tool_calls": []}
    
    try:
        start_time = time.time()
        loop = asyncio.get_event_loop()

        if _should_use_responses(model):
            request_kwargs = responses_runtime.build_payload_from_messages(
                messages=messages,
                model=model,
                tools=tools,
                reasoning_effort=reasoning_effort,
                max_output_tokens=1000,
                tool_choice=tool_choice,
            )

            logger.info(f"🔧 Responses Function Calling 請求: {len(tools)} 個工具, tool_choice={tool_choice}")
            try:
                responses_client = _client_with_timeout(openai_client, OPENAI_RESPONSES_TIMEOUT)
                response = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: responses_client.responses.create(**request_kwargs),
                    ),
                    timeout=_responses_outer_timeout(),
                )
            except Exception as exc:
                if _is_transient_upstream_error(exc):
                    logger.warning("Responses Function Calling failed, falling back to Chat Completions: %s", exc)
                else:
                    raise

            if "response" in locals():
                elapsed_time = time.time() - start_time
                logger.info(f"⏱️ Responses Function Calling 完成，耗時: {elapsed_time:.2f}秒")

                result = {
                    "content": responses_runtime.extract_output_text(response),
                    "tool_calls": responses_runtime.extract_function_calls(response),
                }
                if result["tool_calls"]:
                    logger.info(f"✅ Responses 選擇了 {len(result['tool_calls'])} 個工具")
                else:
                    logger.info("💬 Responses 未選擇任何工具（一般聊天）")
                return result
        
        request_kwargs = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "tool_choice": tool_choice,
            "max_completion_tokens": 1000,
        }
        
        # 加入 reasoning_effort 控制
        reasoning_models = model.startswith("o1") or model.startswith("gpt-5")
        if reasoning_effort and reasoning_models:
            request_kwargs["reasoning_effort"] = reasoning_effort
            logger.info(f"🧠 Function Calling 推理強度: {reasoning_effort}")
        
        logger.info(f"🔧 Function Calling 請求: {len(tools)} 個工具, tool_choice={tool_choice}")
        logger.debug(f"📤 發送的訊息: {messages}")
        
        response = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: openai_client.chat.completions.create(**request_kwargs),
            ),
            timeout=OPENAI_TIMEOUT,
        )
        
        elapsed_time = time.time() - start_time
        logger.info(f"⏱️ Function Calling 完成，耗時: {elapsed_time:.2f}秒")
        
        # 解析回應
        message = response.choices[0].message
        logger.debug(f"📥 原始 message 物件: {message}")
        
        result = {
            "content": message.content or "",
            "tool_calls": [],
        }
        
        # 提取 tool_calls
        if message.tool_calls:
            for tool_call in message.tool_calls:
                result["tool_calls"].append({
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments,
                    }
                })
            logger.info(f"✅ GPT 選擇了 {len(result['tool_calls'])} 個工具")
            for tc in result["tool_calls"]:
                logger.info(f"   🔧 工具: {tc['function']['name']}")
                logger.info(f"   📋 參數 JSON: {tc['function']['arguments']}")
                # 嘗試解析參數
                try:
                    import json
                    parsed = json.loads(tc['function']['arguments'])
                    logger.info(f"   ✅ 解析後參數: {parsed}")
                except Exception as e:
                    logger.warning(f"   ⚠️ 參數解析失敗: {e}")
        else:
            logger.info("💬 GPT 未選擇任何工具（一般聊天）")
        
        return result
        
    except asyncio.TimeoutError as e:
        logger.error(f"❌ Function Calling 請求超時 (Model: {model})")
        raise RuntimeError(f"AI 服務超時 ({model})") from e
    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ Function Calling 失敗 (Model: {model})")
        if "503" in error_msg or "Service temporarily unavailable" in error_msg:
            logger.error("👉 原因：API 服務暫時不可用，或該模型目前處於高負載/維護中。")
            logger.error(f"👉 建議：請嘗試在後台切換至其他模型（您目前使用的是 {model}）。")
        elif "429" in error_msg or "Too Many Requests" in error_msg:
            logger.error("👉 原因：請求頻率過高或 API 額度已耗盡 (429)。")
        elif "401" in error_msg or "Unauthorized" in error_msg:
            logger.error("👉 原因：API Key 無效或未授權 (401)。")
        elif "404" in error_msg:
            logger.error(f"👉 原因：找不到該模型 (404)。請確認 {model} 是一個有效的模型名稱。")
        else:
            logger.error(f"👉 原始錯誤：{e}")
            
        raise RuntimeError(f"AI 服務異常 ({model}): {e}") from e
