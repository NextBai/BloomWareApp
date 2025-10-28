import os
import sys
import logging
import asyncio
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
import time
import json
from typing import Dict, List, Any, Optional

# 設置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("AI_Service")
# 將終端日誌級別設置為ERROR
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.ERROR)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)
logger.propagate = False  # 防止日誌重複輸出

# 載入環境變數
load_dotenv()

# 統一配置管理
from core.config import settings

# 超時設定（秒）
OPENAI_TIMEOUT = settings.OPENAI_TIMEOUT  # 關懷模式 reasoning model 需要更長時間

# 情緒關懷模式 System Prompt（新增）
CARE_MODE_SYSTEM_PROMPT = """你是富有同理心的 AI 助手，用戶情緒不佳需要支持。

**極簡短回應規則（必須嚴格遵守）**：
- 最多 1-2 句話（總共不超過 30 字）
- 語氣溫和、關懷
- 使用「我聽到了」、「我理解」、「我在這裡陪你」等同理語句
- 允許用戶表達負面情緒

**嚴格禁止**：
- 提供任何建議、練習、資源
- 超過 2 句話的回應
- 說教或過度正面的語氣

**範例**：
用戶：「我好難過」 → 你：「我聽到了，我在這裡陪你。」
用戶：「我很生氣」 → 你：「我理解，想聊聊嗎？」
用戶：「講笑話給我聽」 → 你：「好的，想先讓你開心一點。」"""

# 導入時間服務模組
# from features.daily_life.time_service import get_current_time_data, format_time_for_messages  # 已整合到 MCPAgentBridge

# 嘗試導入 OpenAI
try:
    import openai
    from openai import OpenAI
    client = OpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        timeout=30.0,  # 增加超時時間
        max_retries=3   # 添加重試次數
    )
except Exception as e:
    logger.error(f"初始化 OpenAI 客戶端失敗: {e}")
    client = None

# 導入DB函數
try:
    from core.database import get_chat, save_chat_message
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
) -> str:
    if use_care_mode:
        base_prompt = CARE_MODE_SYSTEM_PROMPT.strip()
        if care_emotion:
            base_prompt = f"用戶情緒：{care_emotion}\n{base_prompt}"
    else:
        base_prompt = (
            "你是一個友善、有禮、幽默且能夠提供幫助的AI助手。"
            "請使用繁體中文回覆，保持簡潔清晰的表達。"
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


def _compose_messages_with_context(
    *,
    base_prompt: str,
    history_entries: List[Dict[str, str]],
    memory_context: str,
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

    sections.append(f"【歷史對話摘要】\n{history_text}")

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
    """初始化OpenAI客戶端"""
    global client
    api_key = settings.OPENAI_API_KEY
    if not api_key:
        logger.error("OpenAI API密鑰未設置，請在.env文件中設置OPENAI_API_KEY環境變數")
        print("\n❌ 錯誤: OpenAI API密鑰未設置！請在.env文件中設置OPENAI_API_KEY\n")
        return False
    try:
        logger.info("正在初始化OpenAI客戶端...")
        client = OpenAI(api_key=api_key)
        logger.info("OpenAI 客戶端初始化完成")
        return True
    except Exception as e:
        logger.error(f"初始化OpenAI客戶端失敗: {e}")
        print(f"\n❌ OpenAI API連接失敗: {e}\n")
        return False

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
    if client is None and not initialize_openai():
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

        # 加入 reasoning_effort 控制（GPT-5 系列）
        if reasoning_effort:
            request_kwargs["reasoning_effort"] = reasoning_effort
            logger.info(f"🧠 設定 reasoning_effort: {reasoning_effort}")

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
                lambda: client.chat.completions.create(**request_kwargs)
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
                    lambda: client.chat.completions.create(**request_kwargs),
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
):
    """使用DB管理對話歷史的實現"""
    try:
        if messages:
            if not any(msg.get("role") == "system" for msg in messages):
                # 根據是否為關懷模式選擇 System Prompt（新增）
                if use_care_mode:
                    emotion_text = f"（用戶情緒：{care_emotion}）" if care_emotion else ""
                    system_prompt = f"{CARE_MODE_SYSTEM_PROMPT}\n\n{emotion_text}"
                    logger.info(f"💙 使用關懷模式 System Prompt，情緒：{care_emotion}")
                else:
                    system_prompt = "你是一個友善、有禮、幽默且能夠提供幫助的AI助手。請使用繁體中文回覆，保持簡潔清晰的表達。"

                # 在系統提示前加上用戶名稱
                if user_name:
                    system_prompt = f"用戶名稱：{user_name}\n\n{system_prompt}"

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

            # 從DB加載對話歷史
            chat_history = []
            if db_available:
                try:
                    chat_result = await get_chat(chat_id)
                    if chat_result.get("success"):
                        chat_messages = chat_result["chat"].get("messages", [])

                        # 關懷模式只載入最近 5 條，一般模式載入 10 條（減少上下文）
                        history_limit = 5 if use_care_mode else 10

                        # ⚠️ 關鍵修復：排除當前用戶訊息（避免 Agent 混淆歷史對話）
                        # 只載入歷史對話，不包含剛保存的 user_message
                        historical_messages = chat_messages[:-1] if len(chat_messages) > 0 else []

                        # 轉換DB格式到OpenAI格式
                        for msg in historical_messages[-history_limit:]:
                            content = msg.get("content")
                            # 確保 content 是字串（修正）
                            if isinstance(content, dict):
                                content = content.get("message") or content.get("text") or str(content)
                            elif not isinstance(content, str):
                                content = str(content) if content else ""

                            # 過濾掉錯誤訊息（避免污染上下文）
                            if "抱歉，生成回應時遇到問題" in content or "請重試" in content:
                                continue

                            chat_history.append({
                                "role": msg.get("sender"),
                                "content": content
                            })

                        logger.debug(f"📚 載入 {len(chat_history)} 條歷史對話（排除當前訊息，確保請求隔離）")
                except Exception as e:
                    logger.warning(f"從DB加載對話歷史失敗: {e}")

            # 載入長期記憶
            memory_context = ""
            if user_id:
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

            base_prompt = _build_base_system_prompt(
                use_care_mode=use_care_mode,
                care_emotion=care_emotion,
                user_name=user_name,
            )

            messages_to_send = _compose_messages_with_context(
                base_prompt=base_prompt,
                history_entries=chat_history,
                memory_context=memory_context,
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
):
    """使用全局歷史的回退實現（向後兼容）"""
    try:
        if messages:
            if not any(msg.get("role") == "system" for msg in messages):
                # 根據是否為關懷模式選擇 System Prompt（新增）
                if use_care_mode:
                    emotion_text = f"（用戶情緒：{care_emotion}）" if care_emotion else ""
                    system_prompt = f"{CARE_MODE_SYSTEM_PROMPT}\n\n{emotion_text}"
                    logger.info(f"💙 使用關懷模式 System Prompt（全局歷史），情緒：{care_emotion}")
                else:
                    system_prompt = "你是一個友善、有禮、幽默且能夠提供幫助的AI助手。請使用繁體中文回覆，保持簡潔清晰的表達。"

                # 在系統提示前加上用戶名稱
                if user_name:
                    system_prompt = f"用戶名稱：{user_name}\n\n{system_prompt}"

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

            history_limit = 5 if use_care_mode else 10
            prior_history = conversation_history[user_id][:-1]
            if prior_history:
                prior_history = prior_history[-history_limit:]

            base_prompt = _build_base_system_prompt(
                use_care_mode=use_care_mode,
                care_emotion=care_emotion,
                user_name=user_name,
            )

            memory_context = ""
            if user_id:
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
