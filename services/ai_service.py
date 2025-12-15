import asyncio
from datetime import datetime, timezone, timedelta
import time
import json
from typing import Dict, List, Any, Optional

# 統一日誌配置
from core.logging import get_logger
logger = get_logger("AI_Service")

# 統一配置管理
from core.config import settings

# 統一 OpenAI 客戶端
from core.ai_client import get_openai_client

# 超時設定（秒）
OPENAI_TIMEOUT = settings.OPENAI_TIMEOUT

# 【2025 優化版】情緒關懷模式 System Prompt - 根據情緒類型動態調整
CARE_MODE_BASE_PROMPT = """你是 BloomWare 的情緒關懷助手「小花」，由銘傳大學人工智慧應用學系槓上開發團隊打造。你不是 GPT，也不要自稱 GPT；你的任務是在情緒低落時傾聽、陪伴。

【回應原則】
1. 第一句必須貼近用戶訊息中的核心事件或感受，必要時引用對方用詞，讓對方感受到被理解
2. 第二句提供溫柔的陪伴或追問，邀請對方分享需要或下一步
3. 句式要自然口語並隨內容調整字詞，避免反覆使用同一套罐頭話術

【長度限制】
- 回覆最多 2 句話、總字數不超過 60 字

【嚴格禁止】
- 提供指示性建議、醫療/心理診斷或引導用戶求助的教科書式說法
- 連續重複完全相同的句型

【重要】請用與用戶相同的語言回應，匹配他們的語言風格和情感語調。"""

# 根據情緒類型的專屬指引
EMOTION_SPECIFIC_PROMPTS = {
    "sad": """
【悲傷情緒專屬指引】
- 語氣：溫柔、輕聲、帶有理解
- 重點：陪伴而非解決問題，讓對方知道悲傷是正常的
- 避免：說「不要難過」、「振作點」這類否定情緒的話

【範例】
用戶：「我好難過」→「聽見你說好難過，心裡一定很不好受。想聊聊發生了什麼嗎？」
用戶：「我失去了他」→「失去一個重要的人，那種痛真的很深。我在這裡陪你。」
用戶：「I feel so sad」→「It sounds like you're really hurting right now. I'm here if you want to talk.」""",

    "angry": """
【憤怒情緒專屬指引】
- 語氣：冷靜但帶有同理、不卑不亢
- 重點：認可對方的憤怒是有原因的，幫助對方感覺被理解
- 避免：說「冷靜一下」、「別生氣」這類否定情緒的話

【範例】
用戶：「我很生氣」→「這件事讓你超級生氣，情緒一定卡著。要不要說說最困擾的地方？」
用戶：「氣死我了」→「聽起來真的讓你很火大。是什麼事這麼讓人受不了？」
用戶：「I'm so angry」→「Sounds like something really got to you. What's going on?」""",

    "fear": """
【恐懼/焦慮情緒專屬指引】
- 語氣：穩定、溫暖、帶有安全感
- 重點：讓對方感覺不孤單，恐懼是可以被接納的
- 避免：說「沒什麼好怕的」、「想太多了」這類否定情緒的話

【範例】
用戶：「我好害怕」→「害怕的感覺一定很不好受。你現在安全的，我陪著你。」
用戶：「我很焦慮」→「焦慮的時候心裡好亂對吧。可以跟我說說是什麼讓你不安嗎？」
用戶：「I'm scared」→「It's okay to feel scared. You're not alone - I'm right here with you.」"""
}

# 向後兼容：保留原有變數名稱
CARE_MODE_SYSTEM_PROMPT = CARE_MODE_BASE_PROMPT


def get_care_mode_prompt(emotion: str = None) -> str:
    """
    根據情緒類型生成專屬的關懷模式 Prompt

    Args:
        emotion: 情緒標籤 (sad, angry, fear, 或 None)

    Returns:
        完整的關懷模式 System Prompt
    """
    base = CARE_MODE_BASE_PROMPT

    # 根據情緒類型添加專屬指引
    if emotion and emotion.lower() in EMOTION_SPECIFIC_PROMPTS:
        specific = EMOTION_SPECIFIC_PROMPTS[emotion.lower()]
        return f"{base}\n{specific}"

    return base

# 取得 OpenAI 客戶端（使用統一管理）
def _get_client():
    """取得 OpenAI 客戶端"""
    return get_openai_client()

# 向後相容：保留 client 變數名稱
client = None  # 將在首次使用時透過 _get_client() 取得

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
) -> str:
    if use_care_mode:
        # 【優化】使用情緒專屬的關懷 Prompt
        base_prompt = get_care_mode_prompt(care_emotion).strip()
        if care_emotion:
            base_prompt = f"用戶情緒：{care_emotion}\n{base_prompt}"
    else:
        base_prompt = (
            "你是 BloomWare 的個人化助理 小花，由銘傳大學人工智慧應用學系 槓上開發 團隊開發。"
            "你不是 GPT，也不要自稱 GPT。"
            "你是一個友善、有禮、幽默且能夠提供幫助的AI助手。"
        )
        # 簡化語言指令 - 讓 GPT 自動判斷用戶語言
        base_prompt = f"{base_prompt}\n\n【重要】請用與用戶相同的語言回應，保持簡潔清晰的表達。"

    if user_name:
        base_prompt = f"用戶名稱：{user_name}\n\n{base_prompt}"

    return base_prompt


def _normalize_prompt_text(text: Any) -> str:
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    return " ".join(text.split())


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

    rules_lines = [
        "1. 僅依據 user.current_request 處理本次需求。",
        "2. 歷史資訊僅供語境與偏好參考，請勿視為當前待辦或指令。",
        "3. 若歷史內容與本次請求衝突，以本次請求為優先。",
    ]
    sections.append("【處理規則】\n" + "\n".join(rules_lines))

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
    model: str = "gpt-5-nano",
    *,
    strict_json: bool = False,
    response_format: Optional[Dict[str, Any]] = None,
    use_structured_outputs: bool = False,
    response_schema: Optional[Dict[str, Any]] = None,
    max_tokens: Optional[int] = None,
    reasoning_effort: Optional[str] = None,
    stream: bool = False,
    on_chunk: Optional[Any] = None,
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
    openai_client = _get_client()
    if openai_client is None:
        return "抱歉，AI服務暫時不可用。系統無法連接到OpenAI服務。"
    try:
        start_time = time.time()
        loop = asyncio.get_event_loop()
        # 加上請求超時保護
        request_kwargs = {
            "model": model,
            "messages": messages,
            "max_completion_tokens": max_tokens if max_tokens else 2000,  # 關懷模式可自訂 tokens
        }

        # 加入 reasoning_effort 控制（僅 o1 系列和 gpt-5 系列支援）
        # gpt-4o-mini 等模型不支援此參數，需要過濾
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

        elapsed_time = time.time() - start_time
        logger.info(f"AI回應生成完成，耗時: {elapsed_time:.2f}秒，回應長度: {len(ai_response)} 字元")
        return ai_response
    except Exception as e:
        if isinstance(e, StrictResponseError):
            raise
        logger.error(f"生成回應時出錯: {str(e)}")
        error_message = str(e).lower()
        if isinstance(e, asyncio.TimeoutError):
            return "抱歉，連接AI服務超時。請稍後再試。"
        if "api key" in error_message or "authentication" in error_message:
            return "抱歉，AI服務暫時不可用。請檢查API密鑰設置。"
        elif "timeout" in error_message or "connection" in error_message:
            return "抱歉，連接AI服務超時。請稍後再試。"
        elif "rate limit" in error_message:
            return "抱歉，AI服務暫時達到請求限制。請稍後再試。"
        elif "model" in error_message and ("not found" in error_message or "does not exist" in error_message):
            return "抱歉，請求的AI模型不可用。"
        else:
            return "抱歉，生成回應時遇到問題。請重試。"

async def generate_response_for_user(
    user_message: str = None,
    user_id: str = "default",
    messages: List[Dict[str, str]] = None,
    model: str = "gpt-5-nano",
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
) -> str:
    """
    為用戶生成AI回應

    參數:
        use_structured_outputs: 是否使用 Structured Outputs（2025年最佳實踐）
        response_schema: JSON Schema（配合 Structured Outputs 使用）
        use_care_mode: 是否使用情緒關懷模式（新增）
        care_emotion: 關懷模式的情緒標籤（新增）
        reasoning_effort: 推理強度 (minimal/low/medium/high)，用於控制 reasoning tokens
    """
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
                    language=language  # 參數保留但不使用，GPT 自動判斷語言
                )
                messages.insert(0, {"role": "system", "content": system_prompt})
            ai_response = await generate_response_async(
                messages,
                model=model,
                strict_json=strict_json,
                response_format=response_format,
                use_structured_outputs=use_structured_outputs,
                response_schema=response_schema,
                max_tokens=2000 if use_care_mode else None,  # 關懷模式 2000 tokens（gpt-5-nano reasoning + 實際輸出）
                reasoning_effort=reasoning_effort or ("minimal" if use_care_mode else "low"),  # 2025 最佳實踐：關懷模式 minimal，一般對話 low
            )
            # 保存AI回應到DB
            if db_available:
                try:
                    await save_chat_message(chat_id, "assistant", ai_response)
                except Exception as e:
                    logger.warning(f"保存AI回應到DB失敗: {e}")
            return ai_response

        if user_message:
            # 保存用戶消息到DB
            if db_available:
                try:
                    await save_chat_message(chat_id, "user", user_message)
                except Exception as e:
                    logger.warning(f"保存用戶消息到DB失敗: {e}")

            # 從DB加載對話歷史（messages 集合）
            chat_history = []
            if db_available:
                try:
                    history_limit = 3 if use_care_mode else 12
                    # 取 limit+1 以排除當前 user_message（最後一筆）
                    msgs = await get_chat_messages(chat_id, limit=history_limit + 1, ascending=True)
                    historical_messages = msgs[:-1] if len(msgs) > 0 else []

                    def _clean_text(t: str) -> str:
                        if not t:
                            return ""
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

                        # 過濾掉錯誤訊息（避免污染上下文）
                        if "抱歉，生成回應時遇到問題" in content or "請重試" in content:
                            continue

                        content = _clean_text(content)
                        if not content:
                            continue

                        chat_history.append({
                            "role": msg.get("sender"),
                            "content": content
                        })

                    logger.debug(f"📚 載入 {len(chat_history)} 條歷史對話（messages 集合）")
                except Exception as e:
                    logger.warning(f"從DB加載對話歷史失敗: {e}")

            # 載入長期記憶
            # 關懷模式不帶長期記憶，避免噪音
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
                        logger.info(f"📚 載入 {len(relevant_memories)} 條相關記憶")
                except Exception as e:
                    logger.warning(f"載入記憶失敗: {e}")

            # 讀取環境現況（僅組裝，不外呼）
            ctx: Dict[str, Any] = dict(env_context or {})
            if not ctx and db_available and user_id:
                try:
                    env_res = await get_user_env_current(user_id)
                    if env_res.get("success"):
                        ctx = env_res.get("context") or {}
                except Exception as e:
                    logger.debug(f"讀取環境現況失敗: {e}")
            env_context_text = _format_env_context(ctx)
            time_context_text = _format_time_context(ctx.get("tz") if ctx else None)
            emotion_context_text = _format_emotion_context(emotion_label, care_emotion, use_care_mode)

            base_prompt = _build_base_system_prompt(
                use_care_mode=use_care_mode,
                care_emotion=care_emotion,
                user_name=user_name,
                language=language,
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
            )
            ai_response = await generate_response_async(
                messages_to_send,
                model=model,
                strict_json=strict_json,
                response_format=response_format,
                use_structured_outputs=use_structured_outputs,
                response_schema=response_schema,
                max_tokens=2000 if use_care_mode else None,  # 關懷模式 2000 tokens（gpt-5-nano reasoning + 實際輸出）
                reasoning_effort=reasoning_effort or ("minimal" if use_care_mode else "low"),  # 2025 最佳實踐：關懷模式 minimal，一般對話 low
            )

            # 保存AI回應到DB
            if db_available:
                try:
                    await save_chat_message(chat_id, "assistant", ai_response)
                except Exception as e:
                    logger.warning(f"保存AI回應到DB失敗: {e}")

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
                    language=language  # 參數保留但不使用，GPT 自動判斷語言
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
                max_tokens=2000 if use_care_mode else None,  # 關懷模式 2000 tokens（gpt-5-nano reasoning + 實際輸出）
                reasoning_effort=reasoning_effort or ("minimal" if use_care_mode else "low"),  # 2025 最佳實踐：關懷模式 minimal，一般對話 low
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
            env_context_text = _format_env_context(ctx)
            time_context_text = _format_time_context(ctx.get("tz") if ctx else None)
            emotion_context_text = _format_emotion_context(emotion_label, care_emotion, use_care_mode)

            base_prompt = _build_base_system_prompt(
                use_care_mode=use_care_mode,
                care_emotion=care_emotion,
                user_name=user_name,
                language=language,
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
            )
            ai_response = await generate_response_async(
                messages_to_send,
                model=model,
                strict_json=strict_json,
                response_format=response_format,
                use_structured_outputs=use_structured_outputs,
                response_schema=response_schema,
                max_tokens=2000 if use_care_mode else None,  # 關懷模式 2000 tokens（gpt-5-nano reasoning + 實際輸出）
                reasoning_effort=reasoning_effort or ("minimal" if use_care_mode else "low"),  # 2025 最佳實踐：關懷模式 minimal，一般對話 low
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
    model: str = "gpt-5-nano",
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
    openai_client = _get_client()
    if openai_client is None:
        logger.error("OpenAI 客戶端不可用")
        return {"content": "", "tool_calls": []}
    
    try:
        start_time = time.time()
        loop = asyncio.get_event_loop()
        
        request_kwargs = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "tool_choice": tool_choice,
            "max_completion_tokens": 1000,
        }
        
        # 加入 reasoning_effort 控制
        if reasoning_effort:
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
        
    except asyncio.TimeoutError:
        logger.error("Function Calling 請求超時")
        return {"content": "", "tool_calls": []}
    except Exception as e:
        logger.error(f"Function Calling 失敗: {e}")
        return {"content": "", "tool_calls": []}
