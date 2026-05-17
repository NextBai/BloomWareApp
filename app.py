# BloomWare Application - Confidence-Driven Agent Loop
import os
import json
import time
import base64
import mimetypes
import logging
import secrets
import jwt
import unicodedata
from datetime import datetime
from typing import List, Dict, Optional, Any

# 載入 .env 環境變數（必須在其他 import 之前）
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Request, UploadFile, File, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field
import uvicorn
from pathlib import Path
from contextlib import asynccontextmanager
import uuid
import asyncio
from google.cloud.firestore import FieldFilter

# 本專案整合版：單一 app.py 作為後端入口，前端靜態檔（index.html/app.js/style.css）放在根目錄

# 日誌設定（預設顯示 INFO，可透過 BLOOMWARE_LOG_LEVEL 調整）
LOG_LEVEL_NAME = os.getenv("BLOOMWARE_LOG_LEVEL", "INFO").upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_NAME, logging.INFO)
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # 輸出到終端
        # 可選：輸出到檔案
        # logging.FileHandler('app.log')
    ]
)
logger = logging.getLogger(__name__)
logger.setLevel(LOG_LEVEL)

# 匯入統一配置管理
from core.config import settings

# 匯入內部模組
import services.ai_service as ai_service
# 數據庫操作（整合基礎 + 優化版）
from core.database import (
    connect_to_firestore,
    firestore_db,
    create_chat,
    save_message,
    update_chat_title,
    delete_chat,
    save_chat_message,  # 寫入保持原樣
    get_user_env_current,
)
# 使用優化版數據庫函數（帶快取）
from core.database.optimized import (
    get_user_by_id,
    get_user_chats,
    get_chat,
)
from core.auth import jwt_auth, get_current_user_optional, require_auth
from features.mcp.agent_bridge import MCPAgentBridge
# from features.knowledge_base import KnowledgeBase  # 不再需要，MCP 架構已整合
# from features.daily_life.time_service import get_current_time_data, format_time_for_messages  # 已整合到 MCPAgentBridge
from services.voice_login import VoiceAuthService, VoiceLoginConfig
from services.welcome import compose_welcome
from services.audio_emotion_service import predict_emotion_from_audio
from core.pipeline import ChatPipeline, PipelineResult
from core.memory_system import memory_manager
# 環境 Context 寫入 API
from core.database import set_user_env_current, add_user_env_snapshot
from core.environment import EnvironmentContextService
from middleware import CSPMiddleware


# -----------------------------
# 工具函式
# -----------------------------
def serialize_for_json(obj: Any) -> Any:
    """
    遞迴序列化物件，將不可 JSON 序列化的型別轉換為可序列化格式
    - DatetimeWithNanoseconds → ISO 字串
    - datetime → ISO 字串
    - bytes → base64 字串
    - 其他物件 → str()
    """
    from google.cloud.firestore_v1._helpers import DatetimeWithNanoseconds
    from datetime import datetime, date
    
    if isinstance(obj, (DatetimeWithNanoseconds, datetime, date)):
        return obj.isoformat()
    elif isinstance(obj, bytes):
        return base64.b64encode(obj).decode('utf-8')
    elif isinstance(obj, dict):
        return {k: serialize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [serialize_for_json(item) for item in obj]
    elif isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    else:
        # 未知型別：嘗試轉字串
        try:
            return str(obj)
        except Exception:
            return None


def _normalize_bcp47_language_tag(tag: Optional[str]) -> Optional[str]:
    raw = str(tag or "").strip()
    if not raw:
        return None
    normalized = raw.replace("_", "-")
    parts = [part for part in normalized.split("-") if part]
    if not parts:
        return None

    language = parts[0].lower()
    rest: List[str] = []
    for part in parts[1:]:
        if len(part) == 4 and part.isalpha():
            rest.append(part.title())
        elif len(part) in {2, 3} and part.isalpha():
            rest.append(part.upper())
        else:
            rest.append(part)
    return "-".join([language, *rest])


def _preferred_language_from_text(text: str) -> Optional[str]:
    text = str(text or "").strip()
    if not text:
        return None

    try:
        from langdetect import detect
        lang = detect(text)
        
        lang_map = {
            "zh-cn": "zh-TW",
            "zh-tw": "zh-TW",
            "en": "en-US",
            "ja": "ja-JP",
            "ko": "ko-KR",
            "th": "th-TH",
            "vi": "vi-VN",
            "id": "id-ID",
            "ru": "ru-RU",
            "es": "es-ES",
            "fr": "fr-FR",
            "de": "de-DE"
        }
        if lang in lang_map:
            return lang_map[lang]
    except Exception:
        pass

    script_counts: Dict[str, int] = {}
    for ch in text:
        if ch.isspace():
            continue
        try:
            name = unicodedata.name(ch)
        except ValueError:
            continue
        for script in ("HIRAGANA", "KATAKANA", "HANGUL", "CJK UNIFIED IDEOGRAPH", "CYRILLIC", "THAI"):
            if script in name:
                script_counts[script] = script_counts.get(script, 0) + 1
                break

    if script_counts.get("HIRAGANA", 0) or script_counts.get("KATAKANA", 0):
        return "ja-JP"
    if script_counts.get("HANGUL", 0):
        return "ko-KR"
    if script_counts.get("THAI", 0):
        return "th-TH"
    if script_counts.get("CYRILLIC", 0):
        return "ru-RU"
    if script_counts.get("CJK UNIFIED IDEOGRAPH", 0):
        return "zh-TW"
    return None


def _resolve_conversation_language(
    user_message: str,
    requested_language: Optional[str],
    locale_hint: Optional[str] = None,
) -> str:
    explicit = _normalize_bcp47_language_tag(requested_language)
    if explicit and explicit.lower() != "auto":
        return explicit

    inferred = _preferred_language_from_text(user_message)
    if inferred:
        return inferred

    locale_tag = _normalize_bcp47_language_tag(locale_hint)
    if locale_tag and locale_tag.lower() != "auto":
        return locale_tag

    return "zh-TW"


# -----------------------------
# Pydantic 模型（從統一模組導入）
# -----------------------------
from models.schemas import (
    UserCreate,
    UserLogin,
    ChatCreateRequest,
    MessageCreateRequest,
    ChatTitleUpdateRequest,
    UserInfo,
    UserPublic,
    UserLoginPublicResponse,
    ChatPublic,
    MessagePublic,
    ChatDetailResponse,
    ChatSummary,
    ChatListResponse,
    FileAnalysisRequest,
    FileAnalysisResponse,
    SpeakerLabelBindRequest,
)


# -----------------------------
# FastAPI 應用與 Lifespan（取代 on_event）
# -----------------------------

# -----------------------------
# Lifespan 相關函數
# -----------------------------
async def start_external_servers_async(app: FastAPI):
    """異步啟動外部 MCP 服務器"""
    try:
        if hasattr(app.state.feature_router, 'mcp_server') and hasattr(app.state.feature_router.mcp_server, 'start_external_servers'):
            await app.state.feature_router.mcp_server.start_external_servers()
            logger.info("外部 MCP 服務器異步啟動完成")
        else:
            logger.warning("無法找到 MCP 服務器啟動方法")
    except Exception as e:
        logger.error(f"異步啟動外部 MCP 服務器失敗: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        # 設置通用快取目錄到可寫位置（移除 HuggingFace/SpeechBrain 相關）
        os.environ["XDG_CACHE_HOME"] = "/tmp/cache"
        os.environ["NUMBA_CACHE_DIR"] = "/tmp/numba_cache"
        os.environ["MPLCONFIGDIR"] = "/tmp/matplotlib"

        # 確保快取目錄存在
        cache_dirs = [
            "/tmp/cache",
            "/tmp/numba_cache",
            "/tmp/matplotlib",
            "/tmp/voice_cache",
        ]
        for cache_dir in cache_dirs:
            os.makedirs(cache_dir, mode=0o777, exist_ok=True)
            # 注意：在 Hugging Face Spaces 中無法修改 /tmp 目錄權限
            # 權限已在 Dockerfile 中設置
        
        # 確保 Firestore 在應用啟動時就已連接
        logger.info("🚀 正在初始化 Firestore 連接...")
        connect_to_firestore()

        # 驗證連接成功
        import core.database.base as db_module
        if not db_module.firestore_db:
            logger.error("❌ Firestore 連接失敗，應用可能無法正常運作")
        else:
            logger.info("✅ Firestore 已成功連接並可用")

        app.state.env_service = EnvironmentContextService(
            min_distance_m=settings.ENV_CONTEXT_DISTANCE_THRESHOLD,
            min_heading_deg=settings.ENV_CONTEXT_HEADING_THRESHOLD,
            ttl_seconds=settings.ENV_CONTEXT_TTL_SECONDS,
            env_fetcher=get_user_env_current,
            env_writer=set_user_env_current,
            snapshot_writer=add_user_env_snapshot,
        )
        await app.state.env_service.start()

        app.state.feature_router = MCPAgentBridge()
        app.state.feature_router.bind_env_provider(
            lambda user_id: app.state.env_service.get_context(user_id, allow_stale=True)
        )
        
        # 異步初始化 MCP 橋接層（發現所有工具）
        if hasattr(app.state.feature_router, 'async_initialize'):
            try:
                await app.state.feature_router.async_initialize()
                logger.info("MCP 橋接層異步初始化完成")
            except Exception as e:
                logger.error(f"MCP 橋接層異步初始化失敗: {e}")
        
        # 初始化語音登入服務（硬編參數）
        try:
            app.state.voice_auth = VoiceAuthService(config=VoiceLoginConfig(
                window_seconds=3,
                required_windows=1,
                sample_rate=16000,
                prob_threshold=0.50,  # ECAPA-TDNN 餘弦相似度 + 0.35 加成後門檻
                margin_threshold=0.05,
                min_snr_db=12.0,
            ))
        except Exception as e:
            logger.error(f"初始化語音登入服務失敗：{e}")

        # 啟動定期清理任務
        app.state.enable_background_jobs = settings.ENABLE_BACKGROUND_JOBS
        if settings.ENABLE_BACKGROUND_JOBS:
            cleanup_task = asyncio.create_task(periodic_cleanup())
            app.state.cleanup_task = cleanup_task
            logger.info("定期清理任務已啟動")

            # 啟動快取維護任務
            from core.database.cache import periodic_cache_maintenance
            cache_task = asyncio.create_task(periodic_cache_maintenance())
            app.state.cache_task = cache_task
            logger.info("✅ 快取維護任務已啟動")

            # 啟動批次任務排程器（2025 最佳實踐：Batch API）
            try:
                from services.batch_scheduler import batch_scheduler
                batch_task = asyncio.create_task(batch_scheduler.start())
                app.state.batch_task = batch_task
                logger.info("✅ 批次任務排程器已啟動（每日記憶摘要 + 週健康報告）")
            except Exception as e:
                logger.warning(f"⚠️ 批次任務排程器啟動失敗: {e}")
        else:
            logger.info("背景任務已停用（ENABLE_BACKGROUND_JOBS=false）")

        logger.info("服務器啟動完成，WebSocket路徑: /ws?token=<jwt_token>")
    except Exception as e:
        logger.error(f"啟動初始化失敗: {e}")
        raise
    try:
        yield
    finally:
        env_service = getattr(app.state, "env_service", None)
        if env_service:
            try:
                await env_service.shutdown()
            except Exception as shutdown_err:
                logger.warning(f"環境服務關閉失敗: {shutdown_err}")

        # Shutdown cleanup
        if getattr(app.state, "enable_background_jobs", False):
            try:
                cleanup_task_ref = getattr(app.state, "cleanup_task", None)
                if cleanup_task_ref and not cleanup_task_ref.cancelled():
                    cleanup_task_ref.cancel()
                    logger.info("定期清理任務已取消")

                # 停止快取維護任務
                cache_task_ref = getattr(app.state, "cache_task", None)
                if cache_task_ref and not cache_task_ref.cancelled():
                    cache_task_ref.cancel()
                    logger.info("✅ 快取維護任務已取消")

                # 停止批次任務排程器
                batch_task_ref = getattr(app.state, "batch_task", None)
                if batch_task_ref and not batch_task_ref.cancelled():
                    from services.batch_scheduler import batch_scheduler
                    await batch_scheduler.stop()
                    batch_task_ref.cancel()
                    logger.info("✅ 批次任務排程器已停止")
            except Exception as e:
                logger.error(f"關閉時發生錯誤: {e}")

async def periodic_cleanup():
    """定期清理過期的會話和數據"""
    while True:
        try:
            # 定期清理（使用配置常數）
            await asyncio.sleep(settings.CLEANUP_INTERVAL)

            # 清理過期的WebSocket會話
            await manager.cleanup_expired_sessions()

            # 清理舊的記憶數據（超過90天的）
            try:
                from core.database import cleanup_old_memories
                # 清理所有用戶的舊記憶
                # 注意：這裡需要從數據庫獲取所有用戶ID，然後逐個清理
                # 為了簡單起見，這裡只記錄日誌
                logger.info("定期清理：檢查舊記憶數據")
            except Exception as e:
                logger.warning(f"清理舊記憶時發生錯誤: {e}")

            # 清理過期的臨時數據
            current_time = datetime.now()
            logger.info(f"定期清理完成: {current_time}")

        except Exception as e:
            logger.error(f"定期清理任務出錯: {e}")
            # 即使出錯也要繼續運行
            await asyncio.sleep(60)  # 1分鐘後重試

app = FastAPI(title="聊天機器人API（整合版）", lifespan=lifespan)

# CORS 設定（從環境變數讀取，生產環境應設定具體來源）
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CSP Middleware（允許內嵌 script 用於語音沉浸式前端）
app.add_middleware(CSPMiddleware)

# 掛載靜態檔案目錄（語音沉浸式前端）
static_dir = Path("static/frontend")
login_dir = Path("bloom-ware-login/out")  # 直接使用 Next.js 專案的輸出目錄

if static_dir.exists() and static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(static_dir), html=True), name="frontend")
    logger.info(f"✅ 已掛載語音沉浸式前端: /static → {static_dir}")
else:
    logger.warning("⚠️ 未找到 static/frontend/ 目錄")

# 掛載登入頁面 (Next.js build 產出)
# 使用 html=True 自動處理 index.html，訪問 /login/ 會自動載入 index.html
if login_dir.exists() and login_dir.is_dir():
    app.mount("/login", StaticFiles(directory=str(login_dir), html=True), name="login_static")
    logger.info(f"✅ 已掛載登入頁面: /login → {login_dir}")
else:
    logger.warning(f"⚠️ 未找到 {login_dir} 目錄，請先執行: cd bloom-ware-login && npm run build")

# 環境設定
app.state.intent_model = settings.OPENAI_MODEL

# 簡易登入失敗封鎖機制（記憶體內）
FAILED_LOGIN_THRESHOLD = int(os.getenv("FAILED_LOGIN_THRESHOLD", "3"))  # 可保持原樣，非敏感配置
failed_login_counts: Dict[str, int] = {}
blocked_ips: Dict[str, bool] = {}

def get_client_ip(request: Request) -> str:
    # 優先取 X-Forwarded-For，否則用連線來源
    xff = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
    if xff:
        ip = xff.split(",")[0].strip()
        if ip:
            return ip
    return request.client.host if request.client else "unknown"

# 注意：CORS 已在上方配置，此處移除重複配置

# -----------------------------
# WebSocket 連線管理（從統一模組導入）
# -----------------------------
from websocket import manager

# -----------------------------
# 語音綁定狀態管理器（從統一模組導入）
# -----------------------------
from services.voice_binding import voice_binding_fsm


# -----------------------------
# 統一 WebSocket 端點（JWT認證）
# -----------------------------
@app.websocket("/ws")
async def websocket_endpoint_with_jwt(
    websocket: WebSocket, 
    token: str = Query(None),
    emotion: str = Query("")
):
    """JWT認證的WebSocket端點（支援語音登入匿名連線）"""
    logger.info(f"WebSocket連接請求 - JWT認證 (emotion={emotion})")

    # 特殊處理：語音登入匿名連線
    is_voice_login_mode = token == "anonymous_voice_login"

    if is_voice_login_mode:
        logger.info("🎙️ 語音登入模式：允許匿名連線")
        # 為語音登入生成臨時 user_id
        user_id = f"voice_login_{secrets.token_urlsafe(8)}"
        user_info = {"name": "訪客", "email": "", "id": user_id}
        user_payload = {"email": "", "name": "訪客"}

    else:
        # 正常 JWT 驗證流程
        if not token:
            logger.warning("❌ WebSocket 連接被拒絕：缺少認證令牌")
            await websocket.close(code=1008, reason="缺少認證令牌")
            return

        user_payload = jwt_auth.verify_token(token)
        if not user_payload:
            logger.warning(f"❌ WebSocket 連接被拒絕：無效的認證令牌 (token前20字元: {token[:20]}...)")
            await websocket.close(code=1008, reason="無效的認證令牌")
            return

        user_id = user_payload.get("sub")
        if not user_id:
            logger.warning("❌ WebSocket 連接被拒絕：令牌中缺少用戶ID")
            await websocket.close(code=1008, reason="令牌中缺少用戶ID")
            return

        logger.info(f"✅ JWT 驗證成功，用戶ID: {user_id}, email: {user_payload.get('email')}")

        # 驗證用戶是否存在
        user_info = await get_user_by_id(user_id)
        if not user_info:
            logger.warning(f"❌ WebSocket 連接被拒絕：用戶不存在 (user_id: {user_id})")
            await websocket.close(code=1008, reason="用戶不存在")
            return

    try:
        # 建立連接
        user_session = {
            "user_id": user_id,
            "email": user_payload.get("email"),
            "name": user_payload.get("name"),
            "last_activity": datetime.now(),
            "connected_at": datetime.now()
        }

        await manager.connect(websocket, user_id, user_session)

        # 獲取或創建用戶的 chat_id
        current_chat_id = None
        try:
            user_chats_result = await get_user_chats(user_id)
            if user_chats_result["success"] and user_chats_result["chats"]:
                latest_chat = user_chats_result["chats"][0]
                current_chat_id = latest_chat["chat_id"]
                logger.info(f"用戶 {user_id} 已有對話，使用最新對話: {current_chat_id}")
            else:
                chat_title = f"對話 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                chat_result = await create_chat(user_id, chat_title)
                if chat_result["success"]:
                    current_chat_id = chat_result["chat"]["chat_id"]
                    logger.info(f"為用戶 {user_id} 創建初始對話: {current_chat_id}")
                else:
                    logger.error(f"自動創建對話失敗: {chat_result}")
        except Exception as e:
            logger.error(f"初始化對話時出錯: {str(e)}")

        # 注意：chat_id 會在下面的歡迎訊息中一起發送，不需要額外發送 chat_ready

        # 發送個性化歡迎消息（語音登入模式跳過）
        if not is_voice_login_mode:
            try:
                tz_hint = None
                try:
                    env_res = await get_user_env_current(user_id)
                    if env_res.get("success"):
                        tz_hint = (env_res.get("context") or {}).get("tz")
                except Exception as tz_err:
                    logger.debug(f"讀取使用者時區失敗: {tz_err}")

                td = app.state.feature_router.get_current_time_data()
                # 使用語音登入傳遞的情緒（如果有）
                
                # 如果登入情緒是極端情緒，自動啟動關懷模式
                is_care_active = False
                if emotion in ["sad", "angry", "fear"]:
                    from core.emotion_care_manager import EmotionCareManager
                    # 使用 force=True 確保從登入情緒直接進入，不需等待連續偵測
                    is_care_active = EmotionCareManager.check_and_enter_care_mode(
                        user_id, emotion, chat_id=current_chat_id, force=True
                    )
                    if is_care_active:
                        logger.info(f"💙 偵測到登入情緒 [{emotion}]，自動啟動關懷模式 (user_id={user_id})")

                welcome_msg = compose_welcome(
                    user_name=user_info.get('name'),
                    time_data=td,
                    emotion_label=emotion,
                    timezone=tz_hint,
                )
            except Exception as e:
                logger.warning(f"生成歡迎訊息失敗: {e}")
                welcome_msg = f"歡迎回來，{user_info['name']}！"

            # 發送歡迎訊息，並附帶 chat_id
            # 通知前端當前情緒與關懷模式狀態
            await websocket.send_json({
                "type": "emotion_detected",
                "emotion": emotion or "neutral",
                "care_mode": is_care_active if 'is_care_active' in locals() else False
            })

            await websocket.send_json({
                "type": "system",
                "message": welcome_msg,
                "chat_id": current_chat_id,
                "care_mode": is_care_active if 'is_care_active' in locals() else False
            })

        while True:
            try:
                # 🎯 2026 穩定性優化：加入 WebSocket 心跳 (Ping) 機制，防止長思考工具調用導致連線中斷
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                try:
                    await websocket.send_json({"type": "ping", "timestamp": time.time()})
                    continue
                except Exception:
                    break # 連線已失效
            
            try:
                message_data = json.loads(data)
                message_type_raw = message_data.get("type", "")
                message_type = (message_type_raw or "").strip().lower()
                # 更新最後活動時間
                manager.user_sessions[user_id]["last_activity"] = datetime.now()

                if message_type in ("user_message", "message"):
                    user_message = message_data.get("message") or message_data.get("content", "")
                    if not user_message:
                        await manager.send_message("收到空消息", user_id, "error")
                        continue
                    message_language = message_data.get("language") or "auto"

                    chat_id = message_data.get("chat_id", None)

                    # 如果沒有chat_id，自動創建一個新的對話
                    new_chat_info = None
                    if not chat_id:
                        try:
                            user_chats_result = await get_user_chats(user_id)
                            if user_chats_result["success"] and user_chats_result["chats"]:
                                latest_chat = user_chats_result["chats"][0]
                                chat_id = latest_chat["chat_id"]
                                logger.info(f"用戶 {user_id} 已有對話，使用最新對話: {chat_id}")
                            else:
                                chat_title = f"對話 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                                chat_result = await create_chat(user_id, chat_title)
                                if chat_result["success"]:
                                    chat_id = chat_result["chat"]["chat_id"]
                                    logger.info(f"為用戶 {user_id} 創建新對話: {chat_id}")
                                    new_chat_info = {"chat_id": chat_id, "title": chat_title}
                                else:
                                    logger.error(f"自動創建對話失敗: {chat_result}")
                                    await manager.send_message("無法創建新對話，請稍後再試", user_id, "error")
                                    continue
                        except Exception as e:
                            logger.error(f"檢查用戶對話時出錯: {str(e)}")
                            await manager.send_message("檢查對話時發生錯誤", user_id, "error")
                            continue

                    # === 語音綁定攔截器（關鍵字匹配，無 GPT） ===
                    binding_handled = await voice_binding_fsm.handle_binding_flow(
                        user_id, user_message, websocket, app.state.voice_auth if hasattr(app.state, "voice_auth") else None
                    )
                    if binding_handled:
                        # 已被語音綁定流程處理，不繼續到 Agent
                        continue

                    # typing 提示
                    await manager.send_message("thinking", user_id, "typing")

                    # 處理消息
                    messages_for_handler = [
                        {
                            "role": "system",
                            "content": (
                                "你是一個友善、有禮且能夠提供幫助的AI助手。\n\n"
                                "【重要】語言使用規範：\n"
                                "- 回覆用戶時：必須使用對應的語言，保持簡潔清晰的表達\n"
                                "- 調用工具時：所有參數必須使用英文（城市名、國家名、貨幣代碼等）\n\n"
                            ),
                        },
                        {"role": "user", "content": user_message},
                    ]

                    request_id = uuid.uuid4().hex[:12]
                    logger.info(f"處理用戶消息 req_id={request_id} user_id={user_id} chat_id={chat_id}")

                    async def _do_process_and_send():
                        try:
                            logger.info(f"🚀 開始處理訊息: user_id={user_id}, chat_id={chat_id}")
                            
                            async def _on_text_emotion(em: str, cm: bool, payload: Optional[Dict[str, Any]] = None):
                                if em == "__bot_delta__" and payload:
                                    await websocket.send_json({
                                        "type": "bot_delta",
                                        "message_id": payload.get("message_id"),
                                        "delta": payload.get("delta", ""),
                                        "text": payload.get("text", ""),
                                        "language": payload.get("language"),
                                        "temporary": True,
                                        "phase": payload.get("phase", "answering"),
                                        "timestamp": time.time(),
                                    })
                                    return
                                if em == "__bot_status__" and payload:
                                    await websocket.send_json({
                                        "type": "bot_status",
                                        "status": payload.get("status", "processing"),
                                        "message": payload.get("message", "正在處理..."),
                                        "temporary": True,
                                        "phase": payload.get("phase", payload.get("status", "processing")),
                                        "timestamp": time.time(),
                                    })
                                    return
                                logger.info(f"📤 [即時回調] 發送 text emotion_detected: {em}, care_mode={cm}")
                                await websocket.send_json({
                                    "type": "emotion_detected",
                                    "emotion": em,
                                    "care_mode": cm
                                })

                            response = await handle_message(user_message, user_id, chat_id, messages_for_handler, request_id=request_id, language=message_language, emotion_callback=_on_text_emotion)
                            logger.info(f"📥 handle_message 返回: type={type(response)}, response={response}")

                            # 【優化】處理空回應：轉換為帶情緒的 dict 格式
                            if not response or (isinstance(response, str) and not response.strip()):
                                logger.warning("AI回應為空，使用後備提示")
                                response = {
                                    'message': "抱歉，我暫時沒有合適的回應。可以換個說法再試試嗎？",
                                    'emotion': 'neutral',
                                    'care_mode': False
                                }

                            # 【優化】統一轉換為 dict 格式（處理舊版兼容）
                            if isinstance(response, str):
                                logger.info(f"⚠️ response 是字串，轉換為 dict")
                                response = {
                                    'message': response,
                                    'emotion': 'neutral',
                                    'care_mode': False
                                }

                            # 提取資訊
                            tool_name = response.get('tool_name')
                            tool_data = response.get('tool_data')
                            message_text = response.get('message', response.get('content', ''))
                            emotion = response.get('emotion', 'neutral')  # 預設 neutral
                            care_mode = response.get('care_mode', False)
                            resp_language = response.get('language')

                            logger.info(f"🎭 提取的情緒: emotion={emotion}, care_mode={care_mode}, language={resp_language}")

                            if care_mode:
                                tool_name = None
                                tool_data = None

                            # 序列化 tool_data（避免 DatetimeWithNanoseconds 等不可序列化物件）
                            if tool_data is not None:
                                tool_data = serialize_for_json(tool_data)

                            # 【關鍵】總是發送情緒資訊，確保前端即時更新
                            emotion_payload = {
                                "type": "emotion_detected",
                                "emotion": emotion,
                                "care_mode": care_mode
                            }
                            logger.info(f"📤 準備發送 emotion_detected: {emotion_payload}")
                            await websocket.send_json(emotion_payload)
                            logger.info(f"✅ emotion_detected 已發送: {emotion}, care_mode={care_mode}")

                            # 發送擴充格式的 bot_message
                            bot_payload = {
                                "type": "bot_message",
                                "message": message_text,
                                "timestamp": time.time(),
                                "tool_name": tool_name,
                                "tool_data": tool_data,
                                "care_mode": care_mode,
                                "emotion": emotion,
                                "language": resp_language,
                            }
                            logger.info(f"📤 準備發送 bot_message")
                            await websocket.send_json(bot_payload)
                            logger.info(f"✅ bot_message 已發送")

                            if new_chat_info:
                                await websocket.send_json({
                                    "type": "new_chat_created",
                                    "chat_id": new_chat_info["chat_id"],
                                    "title": new_chat_info["title"]
                                })

                            # 保存訊息（只儲存文字內容）
                            await save_message_to_db(user_id, chat_id, "user", user_message)
                            # 如果 response 是 dict，只保存 message 欄位
                            message_to_save = response.get('message', response) if isinstance(response, dict) else response
                            await save_message_to_db(user_id, chat_id, "assistant", message_to_save)
                        except Exception as e:
                            logger.exception(f"❌ _do_process_and_send 發生異常: {e}")

                    asyncio.create_task(_do_process_and_send())

                elif message_type == "env_snapshot":
                    try:
                        env_service: EnvironmentContextService = app.state.env_service

                        async def _reverse_geocode(lat: float, lon: float):
                            feature_router: MCPAgentBridge = app.state.feature_router
                            tool = feature_router.mcp_server.tools.get("reverse_geocode")
                            if not tool or not tool.handler:
                                return None
                            try:
                                result = await tool.handler({"lat": lat, "lon": lon})
                            except Exception as geo_exc:
                                logger.debug(f"反地理查詢失敗: {geo_exc}")
                                return None
                            if not isinstance(result, dict) or not result.get("success"):
                                return None
                            payload = result.get("data") or result
                            enriched = {
                                "city": payload.get("city"),
                                "admin": payload.get("admin"),
                                "country_code": payload.get("country_code"),
                                "address_display": payload.get("label") or payload.get("display_name"),
                                "detailed_address": payload.get("detailed_address"),
                                "label": payload.get("label"),
                                "road": payload.get("road"),
                                "house_number": payload.get("house_number"),
                                "suburb": payload.get("suburb"),
                                "city_district": payload.get("city_district"),
                                "postcode": payload.get("postcode"),
                                "amenity": payload.get("amenity"),
                                "shop": payload.get("shop"),
                                "building": payload.get("building"),
                                "office": payload.get("office"),
                                "leisure": payload.get("leisure"),
                                "tourism": payload.get("tourism"),
                                "name": payload.get("name"),
                            }
                            return {k: v for k, v in enriched.items() if v is not None}

                        geocode_provider = _reverse_geocode if app.state.feature_router else None
                        ack = await env_service.ingest_snapshot(
                            user_id,
                            message_data,
                            geocode_provider=geocode_provider,
                        )
                        ctx = await env_service.get_context(user_id, allow_stale=True)
                        if ctx:
                            manager.last_env[user_id] = ctx
                            info = manager.get_client_info(user_id) or {}
                            info["env_context"] = ctx
                            manager.set_client_info(user_id, info)
                        await websocket.send_json({"type": "env_ack", **ack})
                    except Exception as e:
                        logger.error(f"處理 env_snapshot 失敗: {e}")
                        await websocket.send_json({"type": "env_ack", "success": False, "error": str(e)})
                elif message_type == "chat_focus":
                    try:
                        cid = message_data.get("chat_id")
                        if cid:
                            info = manager.get_client_info(user_id) or {}
                            info["chat_id"] = cid
                            manager.set_client_info(user_id, info)
                            await websocket.send_json({"type": "chat_focus_ack", "chat_id": cid})
                    except Exception as e:
                        await websocket.send_json({"type": "error", "message": f"CHAT_FOCUS_ERROR: {str(e)}"})

                elif message_type == "audio_start":
                    # 語音處理邏輯（支援多種模式）
                    mode = message_data.get("mode", "voice_login")

                    try:
                        sr = int(message_data.get("sample_rate", 16000))
                    except Exception:
                        sr = 16000

                    if mode == "realtime_chat":
                        # 🎯 中斷 Barge-in：如果正在處理上一個回覆，立即取消
                        await manager.cancel_user_tasks(user_id)
                        
                        # 🎯 2026 穩定性優化：每次開始對話時清除上一次的音頻緩衝與轉錄，防止「語音殘留」污染下一次識別
                        client_info = manager.get_client_info(user_id) or {}
                        client_info["audio_buffer"] = b""
                        client_info["realtime_transcript"] = ""
                        manager.set_client_info(user_id, client_info)
                        
                        # === 即時轉錄模式（使用 Google Speech-to-Text）===
                        try:
                            from services.realtime_stt_service import RealtimeSTTService

                            logger.info(f"🎙️ 啟動即時轉錄模式，用戶 {user_id}")

                            # 建立 Realtime STT 服務實例
                            realtime_stt = RealtimeSTTService()

                            # 定義轉錄回調函數
                            async def on_transcript_delta(delta_text: str):
                                """接收部分轉錄結果並即時發送給前端"""
                                await websocket.send_json({
                                    "type": "stt_delta",
                                    "text": delta_text,
                                    "timestamp": time.time()
                                })
                                logger.debug(f"📤 STT Delta: {delta_text}")

                            async def on_transcript_done(full_text: str):
                                """接收完整轉錄結果"""
                                await websocket.send_json({
                                    "type": "stt_final",
                                    "text": full_text,
                                    "timestamp": time.time()
                                })
                                logger.info(f"✅ STT Final: {full_text}")

                                # 儲存轉錄文字到 client_info，供 audio_stop 使用
                                client_info = manager.get_client_info(user_id) or {}
                                client_info["realtime_transcript"] = full_text
                                manager.set_client_info(user_id, client_info)

                            async def on_vad_committed(status: str):
                                """VAD 偵測到語音狀態變化"""
                                if status == "error":
                                    await websocket.send_json({
                                        "type": "error",
                                        "message": "語音識別服務異常 (Stream Timeout)，正在自動重置環境..."
                                    })
                                else:
                                    await websocket.send_json({
                                        "type": "stt_status",
                                        "status": status,
                                        "timestamp": time.time()
                                    })
                                logger.debug(f"🎤 VAD Status: {status}")

                            # 從前端獲取語言設定（支援：zh, en, id, ja, vi，或 auto 自動檢測）
                            language = message_data.get("language", "auto")
                            logger.info(f"🌐 語言設定: {language}")

                            # 連線到 Google Speech-to-Text 服務
                            success = await realtime_stt.connect(
                                on_transcript_delta=on_transcript_delta,
                                on_transcript_done=on_transcript_done,
                                on_vad_committed=on_vad_committed,
                                language=language,
                                sample_rate=sr
                            )

                            if success:
                                # 儲存 Realtime STT 實例和語言設定到 client info
                                client_info = manager.get_client_info(user_id) or {}
                                client_info["realtime_stt"] = realtime_stt
                                client_info["language"] = language  # 儲存語言設定
                                manager.set_client_info(user_id, client_info)

                                await websocket.send_json({
                                    "type": "realtime_stt_status",
                                    "status": "connected",
                                    "message": "即時轉錄已啟動",
                                    "language": language,
                                })
                                logger.info(f"✅ 用戶 {user_id} 即時轉錄已啟動")
                            else:
                                raise Exception("無法連接到 Google Speech-to-Text")

                        except Exception as e:
                            logger.error(f"❌ 啟動即時轉錄失敗: {e}")
                            await websocket.send_json({
                                "type": "error",
                                "message": f"即時轉錄啟動失敗: {str(e)}"
                            })

                    else:
                        # === 傳統模式（語音登入或語音綁定）===
                        try:
                            if hasattr(app.state, "voice_auth") and app.state.voice_auth:
                                app.state.voice_auth.start_session(user_id, sr)
                                await websocket.send_json({"type": "voice_login_status", "message": "recording_started"})
                            else:
                                await websocket.send_json({"type": "voice_login_result", "success": False, "error": "VOICE_AUTH_NOT_AVAILABLE"})
                        except Exception as e:
                            await websocket.send_json({"type": "voice_login_result", "success": False, "error": f"START_ERROR: {str(e)}"})

                elif message_type == "audio_chunk":
                    try:
                        b64 = message_data.get("pcm16_base64", "")

                        # 檢查是否為即時轉錄模式
                        client_info = manager.get_client_info(user_id) or {}
                        realtime_stt = client_info.get("realtime_stt")

                        if realtime_stt and b64:
                        # === 即時轉錄模式：轉發到 Google Speech-to-Text 緩衝 ===
                            try:
                                import base64
                                audio_bytes = base64.b64decode(b64)
                                await realtime_stt.send_audio_chunk(audio_bytes)
                                logger.debug(f"🎤 轉發音頻到 Google STT: {len(audio_bytes)} bytes")
                                
                                # 同時儲存到本地緩衝（用於音頻情緒辨識）
                                # 🎯 效能與記憶體優化：實施滑動窗口（Sliding Window），僅保留最近 15 秒音頻
                                # 16000Hz * 2bytes/sample * 15s = 480,000 bytes
                                MAX_BUFFER_SIZE = 480000 
                                audio_buffer = client_info.get("audio_buffer", b"")
                                audio_buffer += audio_bytes
                                if len(audio_buffer) > MAX_BUFFER_SIZE:
                                    audio_buffer = audio_buffer[-MAX_BUFFER_SIZE:]
                                    
                                client_info["audio_buffer"] = audio_buffer
                                manager.set_client_info(user_id, client_info)
                                
                            except Exception as e:
                                logger.error(f"❌ 轉發音頻失敗: {e}")

                        elif b64 and hasattr(app.state, "voice_auth") and app.state.voice_auth:
                            # === 傳統模式：存到 buffer ===
                            app.state.voice_auth.append_chunk_base64(user_id, b64)
                            # 添加調試日誌
                            current_buffer_size = len(app.state.voice_auth._buffers.get(user_id, b""))
                            logger.info(f"🎤 收到音頻chunk，用戶 {user_id}，當前緩衝區大小: {current_buffer_size} bytes")

                    except Exception as e:
                        await websocket.send_json({"type": "voice_login_result", "success": False, "error": f"CHUNK_ERROR: {str(e)}"})

                elif message_type == "audio_stop":
                    # 支援三種模式：voice_login（語音登入）、chat（對話）、binding（綁定）
                    mode = message_data.get("mode", "voice_login")

                    if mode == "binding":
                        # === 語音綁定模式：識別語音並綁定到當前用戶 ===
                        logger.info(f"🎙️ 用戶 {user_id} 執行語音綁定")
                        
                        # 檢查是否在綁定等待狀態
                        user_session = manager.get_client_info(user_id) or {}
                        if not user_session.get("voice_binding_pending"):
                            await websocket.send_json({
                                "type": "error",
                                "message": "請先說「綁定語音」來啟動綁定流程"
                            })
                            continue
                        
                        try:
                            if hasattr(app.state, "voice_auth") and app.state.voice_auth:
                                buffer_size = len(app.state.voice_auth._buffers.get(user_id, b""))
                                logger.info(f"🎤 語音綁定，用戶 {user_id}，音頻大小: {buffer_size} bytes")
                                
                                # 執行語音識別（獲取 speaker_label）
                                result = app.state.voice_auth.stop_and_authenticate(user_id)
                            else:
                                result = {"success": False, "error": "VOICE_AUTH_NOT_AVAILABLE"}
                        except Exception as e:
                            logger.error(f"❌ 語音綁定識別失敗: {e}")
                            result = {"success": False, "error": f"BINDING_ERROR: {str(e)}"}
                        
                        # 清理音頻緩衝
                        try:
                            if hasattr(app.state, "voice_auth") and app.state.voice_auth:
                                app.state.voice_auth.clear_session(user_id)
                        except Exception:
                            pass
                        
                        if result.get("success"):
                            # 獲取識別到的 speaker_label
                            speaker_label = result.get("label")
                            logger.info(f"🎙️ 識別到 speaker_label: {speaker_label}")
                            
                            # 檢查這個 speaker_label 是否已被其他用戶綁定
                            from core.database import get_user_by_speaker_label, set_user_speaker_label
                            
                            existing_user = await get_user_by_speaker_label(speaker_label)
                            if existing_user and existing_user.get("id") != user_id:
                                # 已被其他用戶綁定
                                await websocket.send_json({
                                    "type": "bot_message",
                                    "message": f"這個聲紋已被其他用戶綁定。請確保使用你自己的聲音進行綁定。",
                                    "timestamp": time.time()
                                })
                            else:
                                # 綁定到當前用戶
                                bind_result = await set_user_speaker_label(user_id, speaker_label)
                                
                                if bind_result.get("success"):
                                    logger.info(f"✅ 用戶 {user_id} 成功綁定 speaker_label: {speaker_label}")
                                    await websocket.send_json({
                                        "type": "bot_message",
                                        "message": f"綁定成功！你的聲紋已成功建立，現在可以使用語音登入了！",
                                        "timestamp": time.time()
                                    })
                                    await websocket.send_json({
                                        "type": "voice_binding_success",
                                        "speaker_label": speaker_label
                                    })
                                else:
                                    logger.error(f"❌ 綁定失敗: {bind_result.get('error')}")
                                    await websocket.send_json({
                                        "type": "bot_message",
                                        "message": "綁定失敗，請稍後再試。",
                                        "timestamp": time.time()
                                    })
                        else:
                            # 識別失敗
                            error_msg = result.get("error", "UNKNOWN_ERROR")
                            logger.error(f"❌ 語音識別失敗: {error_msg}")
                            await websocket.send_json({
                                "type": "bot_message",
                                "message": "語音識別失敗，請重新錄製。建議說一段完整的句子（3-5秒）。",
                                "timestamp": time.time()
                            })
                        
                        # 清理綁定狀態
                        user_session.pop("voice_binding_pending", None)
                        user_session.pop("voice_binding_started_at", None)
                        manager.set_client_info(user_id, user_session)
                        
                        # 清理 FSM 狀態
                        voice_binding_fsm.clear_state(user_id)
                        
                    elif mode == "voice_login":
                        # === 原有的語音登入邏輯 ===
                        try:
                            if hasattr(app.state, "voice_auth") and app.state.voice_auth:
                                # 添加調試日誌
                                buffer_size = len(app.state.voice_auth._buffers.get(user_id, b""))
                                logger.info(f"🎤 語音登入驗證，用戶 {user_id}，總音頻數據大小: {buffer_size} bytes")
                                result = app.state.voice_auth.stop_and_authenticate(user_id)
                            else:
                                result = {"success": False, "error": "VOICE_AUTH_NOT_AVAILABLE"}
                        except Exception as e:
                            result = {"success": False, "error": f"STOP_ERROR: {str(e)}"}
                        try:
                            if hasattr(app.state, "voice_auth") and app.state.voice_auth:
                                app.state.voice_auth.clear_session(user_id)
                        except Exception:
                            pass

                        if result.get("success"):
                            try:
                                from core.database import get_user_by_speaker_label
                                label = result.get("label")
                                user = await get_user_by_speaker_label(label)
                            except Exception as _e:
                                user = None
                            if user:
                                try:
                                    created_at = user.get("created_at")
                                    if hasattr(created_at, "isoformat"):
                                        user["created_at"] = created_at.isoformat()
                                except Exception:
                                    pass
                                try:
                                    td = app.state.feature_router.get_current_time_data()
                                    name = user.get("name") or "用戶"
                                    emo = result.get("emotion") or {}
                                    emo_label = str(emo.get("label") or "neutral")
                                    # 🎯 使用原始標籤（包含中文）來生成歡迎詞，確保「心情低落」等詞彙能正確匹配
                                    raw_emo_label = str(emo.get("raw_label") or emo_label)
                                    
                                    tz_hint = None
                                    try:
                                        env_res = await get_user_env_current(user_id)
                                        if env_res.get("success"):
                                            tz_hint = (env_res.get("context") or {}).get("tz")
                                    except Exception as tz_err:
                                        logger.debug(f"讀取使用者時區失敗: {tz_err}")
                                    welcome = compose_welcome(
                                        user_name=name,
                                        time_data=td,
                                        emotion_label=raw_emo_label,
                                        timezone=tz_hint,
                                    )
                                except Exception:
                                    welcome = None

                                # 生成 JWT token 讓前端可以登入
                                try:
                                    access_token = jwt_auth.create_access_token(
                                        data={
                                            "sub": user["id"],
                                            "email": user.get("email", ""),
                                            "name": user.get("name", "")
                                        }
                                    )
                                except Exception as e:
                                    logger.error(f"生成 JWT token 失敗: {e}")
                                    access_token = None

                                await websocket.send_json({
                                    "type": "emotion_detected",
                                    "emotion": emo_label,
                                    "care_mode": False,
                                    "source": "voice_login"
                                })

                                await websocket.send_json({
                                    "type": "voice_login_result",
                                    "success": True,
                                    "user": user,
                                    "label": label,
                                    "avg_prob": result.get("avg_prob", 0.0),
                                    "emotion": result.get("emotion"),
                                    "welcome": welcome,
                                    "token": access_token,  # 🎯 新增 JWT token
                                })
                            else:
                                # 語音匹配成功但未綁定 - 存儲 speaker_label 供後續綁定使用
                                logger.warning(f"🎙️ 用戶語音匹配成功但未綁定: speaker_label={result.get('label')}")
                                
                                # 將 speaker_label 存儲到用戶 session，供後續綁定流程使用
                                user_session = manager.get_client_info(user_id) or {}
                                user_session["pending_speaker_label"] = result.get("label")
                                user_session["pending_speaker_timestamp"] = datetime.now()
                                manager.set_client_info(user_id, user_session)
                                
                                await websocket.send_json({
                                    "type": "voice_login_result",
                                    "success": False,
                                    "error": "USER_NOT_BOUND",
                                    "label": result.get("label"),
                                    "avg_prob": result.get("avg_prob", 0.0),
                                    "windows": result.get("windows", []),
                                })
                        else:
                            await websocket.send_json({
                                "type": "voice_login_result",
                                "success": False,
                                "error": result.get("error", "UNKNOWN_ERROR"),
                                "detail": {k: v for k, v in result.items() if k not in {"success"}},
                            })

                    elif mode == "realtime_chat":
                        # === 即時轉錄模式：提交 Google STT 並處理轉錄結果 ===
                        try:
                            client_info = manager.get_client_info(user_id) or {}
                            realtime_stt = client_info.get("realtime_stt")
                            transcription = client_info.get("realtime_transcript", "")
                            audio_buffer = client_info.get("audio_buffer", b"")

                            if realtime_stt:
                                await websocket.send_json({
                                    "type": "stt_status",
                                    "status": "transcribing",
                                    "timestamp": time.time()
                                })
                                logger.info(f"📝 等待即時轉錄 final，用戶 {user_id}")
                                final_transcript = await realtime_stt.wait_for_final_transcript(timeout=3.5)
                                if final_transcript and final_transcript != client_info.get("realtime_transcript"):
                                    transcription = final_transcript
                                    client_info["realtime_transcript"] = final_transcript
                                    await websocket.send_json({
                                        "type": "stt_final",
                                        "text": final_transcript,
                                        "timestamp": time.time()
                                    })
                                elif final_transcript:
                                    transcription = final_transcript

                                logger.info(f"🔌 關閉即時轉錄連線，用戶 {user_id}")
                                await realtime_stt.disconnect()

                                # 清理 client info
                                client_info.pop("realtime_stt", None)
                                client_info.pop("realtime_transcript", None)
                                manager.set_client_info(user_id, client_info)

                                await websocket.send_json({
                                    "type": "realtime_stt_status",
                                    "status": "disconnected",
                                    "message": "即時轉錄已結束"
                                })
                                logger.info(f"✅ 用戶 {user_id} 即時轉錄已結束")
                            else:
                                logger.warning(f"⚠️ 找不到 realtime_stt 實例，用戶 {user_id}")

                            # 如果有轉錄文字，送給 AI Agent 處理
                            if transcription:
                                logger.info(f"🤖 處理即時轉錄結果: {transcription}")
                                
                                # 立即通知前端開始思考，提升即時響應感
                                await websocket.send_json({"type": "typing", "message": "thinking"})

                                # === 優化：並行處理語音情緒辨識與 Agent 邏輯 ===
                                async def _get_audio_emotion():
                                    if audio_buffer and len(audio_buffer) >= 16000 * 1.5:  # 至少 1.5 秒
                                        try:
                                            logger.info(f"🎭 [Parallel] 開始語音情緒辨識，長度: {len(audio_buffer)} bytes")
                                            res = await predict_emotion_from_audio(audio_buffer, sample_rate=16000)
                                            if res.get("success"):
                                                # 簡單過濾低信心度
                                                if res.get("confidence", 0) > 0.4:
                                                    res["source"] = "realtime_voice"
                                                    return res
                                        except Exception as e:
                                            logger.error(f"❌ 語音情緒辨識異常: {e}")
                                    return {"success": False, "source": "realtime_voice"}

                                # 定義一個內部函數來處理整個流程，稍後將其作為 Task 執行
                                async def _process_full_request():
                                    # 啟動並行任務
                                    emotion_task = asyncio.create_task(_get_audio_emotion())
                                    
                                    # 同步準備對話 ID 等基礎工作 (這些很快，不需額外 Task)
                                    chat_id = message_data.get("chat_id")
                                    if not chat_id:
                                        try:
                                            user_chats_result = await get_user_chats(user_id)
                                            if user_chats_result["success"] and user_chats_result["chats"]:
                                                chat_id = user_chats_result["chats"][0]["chat_id"]
                                            else:
                                                chat_title = f"語音對話 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                                                chat_res = await create_chat(user_id, chat_title)
                                                if chat_res["success"]:
                                                    chat_id = chat_res["chat"]["chat_id"]
                                        except Exception as e:
                                            logger.error(f"準備對話時出錯: {e}")
                                    
                                    # 保存用戶訊息（異步）
                                    if chat_id:
                                        asyncio.create_task(save_message_to_db(user_id, chat_id, "user", transcription))

                                    # 等待情緒分析結果（如果還沒出的話，這邊會稍微等一下，但通常會與 GPT 意圖偵測並行）
                                    # 為了讓意圖偵測儘早開始，我們甚至可以在 handle_message 內部去 await emotion_task
                                    # 但這裡我們採取簡單策略：先啟動 handle_message，並傳入 task 或稍後合併
                                    
                                    # 實際上，handle_message 內部會做 GPT 意圖偵測，這耗時最久。
                                    # 我們讓 handle_message 帶入 emotion_task
                                    
                                    language = client_info.get("language", "auto")
                                    
                                    async def _on_emotion_detected(em: str, cm: bool, payload: Optional[Dict[str, Any]] = None):
                                        # ... (原有回調邏輯)
                                        if em.startswith("__bot_"): # 狀態回調
                                            await websocket.send_json({"type": em.replace("__", ""), **(payload or {})})
                                            return
                                        await websocket.send_json({"type": "emotion_detected", "emotion": em, "care_mode": cm})

                                    # 等待情緒完成，或者設定超時
                                    try:
                                        audio_emotion_res = await asyncio.wait_for(emotion_task, timeout=2.0)
                                    except asyncio.TimeoutError:
                                        logger.warning("⚠️ 語音情緒辨識超時，回退至文字分析")
                                        audio_emotion_res = {"success": False}

                                    # 執行 Agent 邏輯
                                    response = await handle_message(
                                        transcription,
                                        user_id,
                                        chat_id,
                                        [],
                                        audio_emotion=audio_emotion_res,
                                        language=language,
                                        emotion_callback=_on_emotion_detected
                                    )

                                    # 發送結果
                                    if isinstance(response, PipelineResult):
                                        await websocket.send_json({
                                            "type": "bot_message",
                                            "message": response.text,
                                            "timestamp": time.time(),
                                            "emotion": response.meta.get("emotion") if response.meta else "neutral",
                                            "care_mode": response.meta.get("care_mode", False) if response.meta else False,
                                            "language": language,
                                        })
                                        # 保存 AI 訊息
                                        if chat_id:
                                            asyncio.create_task(save_message_to_db(user_id, chat_id, "assistant", response.text))
                                    elif isinstance(response, dict):
                                        await websocket.send_json({
                                            "type": "bot_message",
                                            "message": response.get("message", response.get("content", "")),
                                            "timestamp": time.time(),
                                            "tool_name": response.get("tool_name"),
                                            "tool_data": response.get("tool_data"),
                                            "emotion": response.get("emotion", "neutral"),
                                            "care_mode": response.get("care_mode", False),
                                            "language": response.get("language", language),
                                        })
                                        if chat_id:
                                            asyncio.create_task(save_message_to_db(user_id, chat_id, "assistant", str(response.get("message", ""))))
                                    else:
                                        # 字串回應
                                        await websocket.send_json({
                                            "type": "bot_message",
                                            "message": str(response),
                                            "timestamp": time.time(),
                                            "language": language
                                        })
                                        if chat_id:
                                            asyncio.create_task(save_message_to_db(user_id, chat_id, "assistant", str(response)))

                                # 啟動整體處理任務
                                # 🎯 註冊任務，以便支援 Barge-in 中斷
                                task = asyncio.create_task(_process_full_request())
                                manager.register_task(user_id, task)

                                # 清理緩衝區並直接返回循環，讓連線保持暢通
                                if audio_buffer:
                                    client_info.pop("audio_buffer", None)
                                    manager.set_client_info(user_id, client_info)

                            else:
                                logger.debug(f"沒有轉錄文字，返回待機狀態")
                                await websocket.send_json({"type": "stt_status", "status": "idle"})

                        except Exception as e:
                            logger.error(f"❌ 關閉即時轉錄失敗: {e}")
                            await websocket.send_json({
                                "type": "error",
                                "message": f"關閉即時轉錄失敗: {str(e)}"
                            })

                                            
            except json.JSONDecodeError:
                await manager.send_message("消息格式錯誤，無法解析", user_id, "error")
            except Exception as e:
                logger.error(f"處理消息時出錯: {str(e)}")
                await manager.send_message(f"處理消息時出錯: {str(e)}", user_id, "error")

    except WebSocketDisconnect:
        logger.info(f"用戶 {user_id} 的WebSocket連接中斷")
        manager.disconnect(user_id)
    except Exception as e:
        logger.error(f"WebSocket連接時出錯: {str(e)}")
        manager.disconnect(user_id)


# -----------------------------
# 消息處理與AI
# -----------------------------
async def handle_message(user_message, user_id, chat_id, messages, request_id: str = None, audio_emotion: dict = None, language: str = None, emotion_callback=None):
    user_message = (user_message or "").strip()
    logger.info(f"📥 handle_message: 收到訊息='{user_message}', user_id={user_id}, audio_emotion={audio_emotion}, language={language}")
    resolved_language = _resolve_conversation_language(user_message, language)
    
    if not user_message:
        logger.info(f"🚫 攔截到空請求，中斷交由 Agent 處理。")
        return "不好意思，我剛剛沒有聽清楚或是沒收到內容，可以請您再說一次嗎？"

    # 指令優先，避免進入管線造成不必要延遲
    if user_message.startswith("/"):
        cmd = await handle_command(user_message, user_id)
        if cmd:
            return cmd

    feature_router:MCPAgentBridge  = app.state.feature_router

    async def _detect(msg: str, tool_context: str = "", language: str = None, **kwargs):
        logger.info(f"🎯 Pipeline: 開始意圖偵測，訊息='{msg}'")
        try:
            result = await feature_router.detect_intent(msg, tool_context=tool_context, language=language or resolved_language)
            logger.info(f"🎯 Pipeline: 意圖偵測結果={result}")
            return result
        except Exception as e:
            logger.exception(f"🎯 Pipeline: 意圖偵測異常={e}")
            raise

    async def _process_feature(intent, _uid, original, _cid):
        logger.info(f"🔧 Pipeline: 處理功能，intent={intent}, user_id={_uid}")
        # 續接待補槽優先
        cont = await feature_router.continue_pending(_uid, original, chat_id=_cid)
        if isinstance(cont, str) and cont:
            logger.info(f"🔧 Pipeline: 續接補槽回應='{cont}'")
            return cont
        result = await feature_router.process_intent(intent, user_id=_uid, original_message=original, chat_id=_cid)
        logger.info(f"🔧 Pipeline: 功能處理結果='{result}'")
        return result

    stream_message_id = request_id or f"stream_{int(time.time() * 1000)}"
    stream_accumulator = {"text": ""}

    async def _emit_bot_status(status: str, message: str, phase: Optional[str] = None):
        if emotion_callback is None:
            return
        try:
            await emotion_callback(
                "__bot_status__",
                False,
                {
                    "status": status,
                    "message": message,
                    "phase": phase or status,
                    "temporary": True,
                },
            )
        except TypeError:
            return

    async def _on_ai_chunk(delta: Any):
        if not delta or emotion_callback is None:
            return
        if isinstance(delta, dict):
            delta.setdefault("temporary", True)
            delta.setdefault("phase", delta.get("status", "processing"))
            try:
                await emotion_callback("__bot_status__", False, delta)
            except TypeError:
                return
            return

        stream_accumulator["text"] += str(delta)
        try:
            await emotion_callback(
                "__bot_delta__",
                False,
                {
                    "message_id": stream_message_id,
                    "delta": str(delta),
                    "text": stream_accumulator["text"],
                    "language": _preferred_language_from_text(stream_accumulator["text"]) or resolved_language,
                    "phase": "answering",
                    "temporary": True,
                },
            )
        except TypeError:
            return

    async def _ai(messages_in, cid, model, rid, chat_id, use_care_mode=False, care_emotion=None, emotion_label=None, language=None, tool_context: str = "", is_first_care: bool = False):
        # 【效能優化】立即通知前端進入 AI 生成階段，這會刷新思考超時
        await _emit_bot_status("generating", "正在組織語言回答您...", "thinking")
        
        env_context = {}
        env_service = getattr(app.state, 'env_service', None)
        if env_service:
            try:
                env_context = await env_service.get_context(cid, allow_stale=True)
            except Exception as env_err:
                logger.debug(f'讀取環境快取失敗: {env_err}')

        # 取得用戶名稱（優先順序：Google 名稱 > 語音 label > "用戶"）
        user_name = "用戶"
        try:
            user_data = await get_user_by_id(cid)
            if user_data and user_data.get("name"):
                user_name = user_data["name"]
        except Exception as e:
            logger.debug(f"無法取得用戶名稱，使用預設值: {e}")

        # 使用傳入的 language 參數（優先）或閉包捕獲的外部變數
        lang = language if language is not None else resolved_language

        # 兼容：如果傳入字串，視為 user_message；如果傳入 list，視為 messages
        try:
            if isinstance(messages_in, str):
                return await ai_service.generate_response_for_user(
                    user_message=messages_in,
                    user_id=cid,
                    model=model,
                    request_id=rid,
                    chat_id=chat_id,
                    use_care_mode=use_care_mode,
                    care_emotion=care_emotion,
                    user_name=user_name,
                    emotion_label=emotion_label,
                    env_context=env_context,
                    language=lang,
                    stream=bool(emotion_callback),
                    on_chunk=_on_ai_chunk if emotion_callback else None,
                    tool_context=tool_context,
                    is_first_care=is_first_care,
                )
            else:
                return await ai_service.generate_response_for_user(
                    messages=messages_in,
                    user_id=cid,
                    model=model,
                    request_id=rid,
                    chat_id=chat_id,
                    use_care_mode=use_care_mode,
                    care_emotion=care_emotion,
                    user_name=user_name,
                    emotion_label=emotion_label,
                    env_context=env_context,
                    language=lang,
                    stream=bool(emotion_callback),
                    on_chunk=_on_ai_chunk if emotion_callback else None,
                    tool_context=tool_context,
                    is_first_care=is_first_care,
                )
        except Exception as e:
            logger.error(f"AI 生成過程出錯: {e}")
            raise

    model = settings.OPENAI_MODEL
    # 簡化 Pipeline：移除未使用的記憶管理和摘要決策
    # 長期記憶由 memory_system 在 Pipeline 外處理
    pipeline = ChatPipeline(
        _detect,
        _process_feature,
        _ai,
        model=model,
        detect_timeout=25.0,  # 意圖檢測超時：保留 Agent 自主工具判斷空間
        feature_timeout=30.0,  # 功能處理超時 (15 → 30，新聞摘要生成需要更長時間)
        ai_timeout=60.0,  # AI回應超時：hosted WebSearch/工具階段可能先無文字 delta
    )
    logger.info(f"⚙️ 準備調用 ChatPipeline.process，user_message='{user_message}', audio_emotion={audio_emotion}, language={resolved_language}")
    await _emit_bot_status("planning", "已收到，正在規劃處理方式...", "planning")
    res: PipelineResult = await pipeline.process(user_message, user_id=user_id, chat_id=chat_id, request_id=request_id, audio_emotion=audio_emotion, language=resolved_language, emotion_callback=emotion_callback)
    logger.info(f"⚙️ ChatPipeline.process 完成，結果='{res.text}', is_fallback={res.is_fallback}, reason={res.reason}")
    
    # 檢查是否有工具元數據
    tool_name = None
    tool_data = None
    if res.meta:
        tool_name = res.meta.get('tool_name')
        tool_data = res.meta.get('tool_data')
        logger.info(f"🔧 檢測到工具調用: tool_name={tool_name}, tool_data={tool_data}")
    
    # 後台處理長期記憶（真正不阻塞）
    async def _process_memory_background():
        try:
            # 獲取對話歷史用於記憶分析
            conversation_history = []
            if chat_id:
                chat_result = await get_chat(chat_id)
                if chat_result["success"]:
                    messages = chat_result["chat"].get("messages", [])
                    for msg in messages[-6:]:  # 最近6條消息
                        conversation_history.append({
                            "role": msg.get("sender", "user"),
                            "content": msg.get("content", "")
                        })

            # 處理記憶提取和存儲
            memory_result = await memory_manager.process_conversation(
                user_id=user_id,
                user_message=user_message,
                assistant_response=res.text,
                conversation_history=conversation_history
            )
            logger.info(f"✅ 記憶處理完成（後台）: 提取 {memory_result['extracted_memories']} 條，保存 {memory_result['saved_memories']} 條")
        except Exception as e:
            logger.warning(f"⚠️ 記憶處理失敗（後台）: {e}")

    # 啟動後台任務，不等待完成
    asyncio.create_task(_process_memory_background())

    # 提取情緒與關懷模式資訊（新增）
    emotion = res.meta.get('emotion') if res.meta else None
    care_mode = res.meta.get('care_mode', False) if res.meta else False
    final_language = _preferred_language_from_text(res.text) or _normalize_bcp47_language_tag(language) or "zh-TW"
    
    logger.info(f"🎭 handle_message 情緒: emotion={emotion}, care_mode={care_mode}, meta={res.meta}")

    # 【優化】總是返回 dict 格式，確保前端一定收到情緒資訊
    # 即使沒有工具調用，也要包含 emotion（預設 neutral）
    final_emotion = emotion if emotion else "neutral"
    logger.info(f"📤 返回 dict 格式: emotion={final_emotion}, care_mode={care_mode}")
    return {
        'message': res.text,
        'tool_name': tool_name,
        'tool_data': tool_data,
        'emotion': final_emotion,
        'care_mode': care_mode,
        'language': final_language,
    }


async def save_message_to_db(user_id, chat_id, role, content, background: bool = True):
    """
    保存消息到數據庫

    Args:
        background: True=後台非阻塞寫入（推薦），False=同步阻塞寫入
    """
    async def _save():
        try:
            if chat_id:
                await save_chat_message(chat_id, role, content)
            else:
                await save_message(user_id, content, role == "assistant")
            logger.debug(f"✅ 消息已保存: chat_id={chat_id}, role={role}")
        except Exception as e:
            logger.error(f"❌ 保存消息失敗: {str(e)}")

    if background:
        # 後台非阻塞寫入（不等待完成）
        asyncio.create_task(_save())
        return True
    else:
        # 同步阻塞寫入（等待完成）
        try:
            await _save()
            return True
        except Exception:
            return False


async def handle_command(command, user_id):
    if command in ("/help", "/幫助"):
        return """可用命令：
/help 或 /幫助 - 顯示此幫助信息
/clear 或 /清除 - 清除聊天歷史
/features 或 /功能 - 列出可用功能"""
    elif command in ("/clear", "/清除"):
        return "您的聊天歷史已清除。"
    elif command in ("/features", "/功能"):
        return app.state.feature_router.get_feature_list()
    else:
        if command.startswith("/"):
            return f"未知命令：{command}。輸入 /help 或 /幫助 獲取可用命令列表。"
        return None


# -----------------------------
# API：基本、狀態、切換
# -----------------------------
@app.get("/")
async def root():
    """根路徑導向登入頁面"""
    return RedirectResponse(url="/login/", status_code=307)


@app.get("/status")
async def get_status():
    return {
        "success": True,
        "status": "running",
        "connections": len(manager.active_connections),
        "model": app.state.intent_model,
    }


# -----------------------------
# 用戶/聊天 API
# Google OAuth 2.0 認證 (Authorization Code Flow + PKCE)
# -----------------------------

from core.auth import google_oauth as oauth_manager
from core.database import create_or_login_google_user

class GoogleOAuthRequest(BaseModel):
    credential: str  # Google JWT token (向後兼容)

class GoogleAuthCodeRequest(BaseModel):
    code: str
    code_verifier: str
    state: Optional[str] = None

@app.get("/auth/google/url")
async def get_google_auth_url(request: Request, redirect_uri: Optional[str] = None):
    """
    獲取Google授權URL (包含PKCE)
    
    支援動態回調地址：
    - 如果提供 redirect_uri 參數，使用該地址
    - 否則根據請求來源自動選擇 (localhost 或局域網 IP)
    """
    try:
        # 如果沒有指定 redirect_uri，根據請求來源自動選擇
        if not redirect_uri:
            # 獲取請求的 Host
            host = request.headers.get("host", "localhost:8080")
            # 判斷協議：生產環境使用 https，本地開發使用 http
            scheme = "https" if "onrender.com" in host or request.headers.get("x-forwarded-proto") == "https" else "http"
            # 構建回調 URL（使用正確的 callback endpoint）
            redirect_uri = f"{scheme}://{host}/auth/google/callback"
            logger.info(f"🔄 自動選擇回調地址: {redirect_uri}")
        
        # 臨時覆蓋 oauth_manager 的 redirect_uri
        original_redirect_uri = oauth_manager.redirect_uri
        oauth_manager.redirect_uri = redirect_uri
        
        # 生成PKCE pair
        pkce_pair = oauth_manager.generate_pkce_pair()

        # 生成state參數防止CSRF
        state = secrets.token_urlsafe(32)

        # 生成授權URL
        auth_url = oauth_manager.get_authorization_url(
            state=state,
            code_challenge=pkce_pair["code_challenge"]
        )
        
        # 恢復原始 redirect_uri
        oauth_manager.redirect_uri = original_redirect_uri

        return {
            "success": True,
            "auth_url": auth_url,
            "state": state,
            "code_verifier": pkce_pair["code_verifier"],
            "redirect_uri": redirect_uri  # 返回使用的回調地址供前端參考
        }

    except Exception as e:
        logger.error(f"生成Google授權URL失敗: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": "OAUTH_CONFIG_ERROR"})

@app.get("/auth/callback")
async def google_oauth_legacy_callback(
    code: str = None,
    state: str = None,
    error: str = None,
    scope: str = None,
    authuser: str = None,
    prompt: str = None
):
    """
    Google OAuth 2.0 舊版回調端點 - 重定向到新端點
    處理用戶在Google Cloud Console中配置的 /auth/callback URI
    """
    if error:
        # 如果有錯誤，直接重定向到前端處理錯誤
        error_params = f"?error={error}"
        if state:
            error_params += f"&state={state}"
        return RedirectResponse(url=f"/login?{error_params}", status_code=302)

    if not code:
        return JSONResponse(status_code=400, content={"success": False, "error": "NO_AUTHORIZATION_CODE"})

    # 構造新的URL參數並重定向到正確的端點
    redirect_url = f"/auth/google/callback?code={code}"
    if state:
        redirect_url += f"&state={state}"
    if scope:
        redirect_url += f"&scope={scope}"
    if authuser:
        redirect_url += f"&authuser={authuser}"
    if prompt:
        redirect_url += f"&prompt={prompt}"

    logger.info(f"重定向舊版回調到新端點: {redirect_url}")
    return RedirectResponse(url=redirect_url, status_code=302)

@app.get("/auth/google/callback")
async def google_oauth_callback_get(
    code: str = None,
    state: str = None,
    error: str = None,
    scope: str = None,
    authuser: str = None,
    prompt: str = None
):
    """
    Google OAuth 2.0 回調端點 (GET) - 處理來自Google的重定向
    """
    logger.info(f"🔍 Google OAuth GET 回調開始")
    logger.info(f"🔍 GET 參數: code={code[:10] if code else None}..., state={state}, error={error}")

    try:
        if error:
            # 如果有錯誤，重定向到前端顯示錯誤
            return RedirectResponse(
                url=f"/login?error={error}&state={state or ''}",
                status_code=302
            )

        if not code:
            return JSONResponse(status_code=400, content={"success": False, "error": "NO_AUTHORIZATION_CODE"})

        # 構造前端處理的URL
        frontend_url = f"/login?code={code}&state={state or ''}&scope={scope or ''}"
        return RedirectResponse(url=frontend_url, status_code=302)

    except Exception as e:
        logger.error(f"Google OAuth GET 回調處理失敗: {e}")
        return RedirectResponse(url="/login?error=callback_error", status_code=302)

@app.post("/auth/google/callback")
async def google_oauth_callback_post(auth_request: GoogleAuthCodeRequest):
    """
    Google OAuth 2.0 回調端點 (POST) - 處理來自前端的授權碼
    """
    logger.info(f"🔍 Google OAuth POST 回調開始")
    logger.info(f"🔍 POST 參數: code={auth_request.code[:10] if auth_request.code else None}..., state={auth_request.state}")

    try:
        # 驗證state參數防止CSRF攻擊
        if auth_request.state:
            expected_state = auth_request.state
            received_state = auth_request.state
            if received_state != expected_state:
                logger.warning(
                    "⚠️ State 不匹配 (frontend_state=%s, received_state=%s)，允許流程繼續但需提防CSRF",
                    expected_state,
                    received_state,
                )
            else:
                logger.info(f"驗證state參數: {expected_state}")

        # 交換授權碼為tokens
        logger.info(f"📤 開始交換授權碼為tokens...")
        token_data = await oauth_manager.exchange_code_for_tokens(
            auth_request.code,
            auth_request.code_verifier
        )
        logger.info(f"✅ Token交換成功，獲得access_token")

        # 獲取用戶信息
        logger.info(f"📤 使用access_token獲取用戶信息...")
        user_info = await oauth_manager.get_user_info(token_data["access_token"])
        logger.info(f"✅ 用戶信息獲取成功: {user_info.get('email', 'unknown')}")

        # 創建或登入用戶
        logger.info(f"📤 創建或登入用戶...")
        result = await create_or_login_google_user(user_info)
        logger.info(f"✅ 用戶處理結果: success={result.get('success')}, is_new={result.get('is_new_user')}")

        if result["success"]:
            # 生成JWT token
            user_data = result["user"]
            access_token = jwt_auth.create_access_token(
                data={
                    "sub": user_data["id"],
                    "email": user_data["email"],
                    "name": user_data["name"]
                }
            )
            logger.info(f"✅ Google OAuth 完整流程成功: {result['user']['email']}")
            logger.info(f"🔑 JWT token已生成，長度: {len(access_token)}")

            response_data = {
                "success": True,
                "user": user_data,
                "access_token": access_token,
                "token_type": "bearer",
                "is_new_user": result.get("is_new_user", False)
            }
            logger.info(f"📤 返回回應數據: success={response_data['success']}, user_id={user_data.get('id')}")
            return response_data
        else:
            logger.error(f"Google OAuth 用戶創建/登入失敗: {result.get('error')}")
            return JSONResponse(status_code=400, content=result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Google OAuth POST 回調處理失敗: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": "OAUTH_CALLBACK_ERROR"})

@app.post("/auth/refresh")
async def refresh_token(current_user: Dict[str, Any] = Depends(require_auth)):
    """刷新訪問令牌"""
    try:
        user_id = current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=400, detail="無效的用戶信息")

        # 從數據庫獲取用戶信息
        user_result = await get_user_by_id(user_id)
        if not user_result:
            raise HTTPException(status_code=404, detail="用戶不存在")

        # 生成新的訪問令牌
        access_token = jwt_auth.create_access_token(
            data={
                "sub": user_result["id"],
                "email": user_result["email"],
                "name": user_result["name"]
            }
        )

        return {
            "success": True,
            "access_token": access_token,
            "token_type": "bearer"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"刷新令牌時發生錯誤: {e}")
        raise HTTPException(status_code=500, detail="令牌刷新失敗")

@app.post("/auth/logout")
async def logout():
    """登出端點（前端清除 token 即可，後端無需處理）"""
    return {
        "success": True,
        "message": "登出成功"
    }


# -----------------------------
# 語音登入 API
# -----------------------------
class VoiceLoginRequest(BaseModel):
    """語音登入請求"""
    audio_base64: str  # base64 編碼的 PCM16 音訊
    sample_rate: int = 16000


@app.post("/auth/voice/login")
async def voice_login(request: VoiceLoginRequest):
    """
    語音登入 API
    
    流程：
    1. 接收 base64 編碼的音訊
    2. 執行身份辨識 + 情緒辨識
    3. 查詢 speaker_label 對應的用戶
    4. 生成 JWT token
    5. 回傳 token + 情緒
    """
    import base64
    
    try:
        # 取得 VoiceAuthService 實例
        voice_auth = getattr(app.state, "voice_auth", None)
        if not voice_auth:
            logger.error("❌ VoiceAuthService 未初始化")
            return JSONResponse(status_code=503, content={
                "success": False,
                "error": "語音辨識服務未就緒，請稍後再試"
            })
        
        # 解碼音訊
        try:
            audio_bytes = base64.b64decode(request.audio_base64)
        except Exception as e:
            logger.error(f"❌ 音訊解碼失敗: {e}")
            return JSONResponse(status_code=400, content={
                "success": False,
                "error": "音訊格式錯誤"
            })
        
        logger.info(f"🎙️ 收到語音登入請求，音訊大小: {len(audio_bytes)} bytes")
        
        # 建立臨時 session 並處理音訊
        temp_user_id = f"voice_login_{datetime.now().timestamp()}"
        voice_auth.start_session(temp_user_id, request.sample_rate)
        voice_auth._buffers[temp_user_id] = bytearray(audio_bytes)
        
        # 執行辨識
        result = voice_auth.stop_and_authenticate(temp_user_id)
        
        # 清理 session
        voice_auth.clear_session(temp_user_id)
        
        if not result.get("success"):
            error_code = result.get("error", "UNKNOWN_ERROR")
            quality_warnings = result.get("quality_warnings") or []
            error_messages = {
                "NO_AUDIO": "沒有收到音訊資料",
                "AUDIO_TOO_SHORT": "音訊太短，請錄製至少 3 秒",
                "LOW_SNR": "環境太吵，請在安靜的地方重試",
                "INCONSISTENT_WINDOWS": "無法確認身份，請重試",
                "THRESHOLD_NOT_MET": "無法確認身份，請重試",
                "MODEL_ERROR": "辨識系統錯誤，請稍後重試",
            }
            logger.warning(f"🎙️ 語音辨識失敗: {error_code} quality_warnings={quality_warnings}")
            return JSONResponse(content={
                "success": False,
                "error": error_messages.get(error_code, f"辨識失敗：{error_code}")
            })

        quality_warnings = result.get("quality_warnings") or []
        if quality_warnings:
            logger.warning(f"🎙️ 語音登入品質警告（未阻擋）: {quality_warnings}")
        
        # 取得辨識結果
        speaker_label = result.get("label")
        emotion = result.get("emotion", {})
        emotion_label = emotion.get("label", "neutral") if isinstance(emotion, dict) else "neutral"
        
        logger.info(f"🎙️ 語音辨識成功: speaker={speaker_label}, emotion={emotion_label}")
        
        # 查詢對應的用戶
        from core.database import get_user_by_speaker_label
        user = await get_user_by_speaker_label(speaker_label)
        
        if not user:
            logger.warning(f"🎙️ 找不到綁定的帳號: speaker_label={speaker_label}")
            return JSONResponse(content={
                "success": False,
                "error": f"找不到綁定的帳號。請先使用 Google 登入並綁定語音。"
            })
        
        # 生成 JWT token
        user_id = user.get("id")
        user_name = user.get("name", "用戶")
        user_email = user.get("email", "")
        
        payload = {
            "sub": user_id,
            "name": user_name,
            "email": user_email,
            "iat": datetime.utcnow(),
            "exp": datetime.utcnow() + timedelta(days=7),
            "login_method": "voice",
            "emotion": emotion_label,
        }
        
        token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")
        
        logger.info(f"✅ 語音登入成功: user={user_name}, emotion={emotion_label}")
        
        return {
            "success": True,
            "access_token": token,
            "user": {
                "id": user_id,
                "name": user_name,
                "email": user_email,
            },
            "emotion": emotion_label,
        }
        
    except Exception as e:
        logger.exception(f"❌ 語音登入失敗: {e}")
        return JSONResponse(status_code=500, content={
            "success": False,
            "error": f"系統錯誤：{str(e)}"
        })

    """
    Google OAuth 2.0 登入端點 (向後兼容)
    接收前端傳來的 Google JWT token，驗證後創建或登入用戶
    """
    try:
        # 驗證 Google JWT token (原有實現，保持向後兼容)
        from google.oauth2 import id_token
        from google.auth.transport import requests
        import os

        # Google OAuth Client ID (從統一配置讀取)
        GOOGLE_CLIENT_ID = settings.GOOGLE_CLIENT_ID
        if not GOOGLE_CLIENT_ID:
            logger.error("GOOGLE_CLIENT_ID 環境變數未設定")
            return JSONResponse(status_code=500, content={"success": False, "error": "SERVER_CONFIG_ERROR"})

        # 驗證 Google token
        idinfo = id_token.verify_oauth2_token(
            oauth_request.credential,
            requests.Request(),
            GOOGLE_CLIENT_ID
        )

        # 創建或登入用戶
        result = await create_or_login_google_user(idinfo)

        if result["success"]:
            # 生成JWT token
            user_data = result["user"]
            access_token = jwt_auth.create_access_token(
                data={
                    "sub": user_data["id"],
                    "email": user_data["email"],
                    "name": user_data["name"]
                }
            )

            logger.info(f"Google OAuth 登入成功: {result['user']['email']}")
            return {
                "success": True,
                "user": user_data,
                "access_token": access_token,
                "token_type": "bearer",
                "is_new_user": result.get("is_new_user", False)
            }
        else:
            logger.error(f"Google OAuth 登入失敗: {result.get('error')}")
            return JSONResponse(status_code=400, content=result)

    except ValueError as e:
        # 無效的 token
        logger.warning(f"Google OAuth token 驗證失敗: {e}")
        return JSONResponse(status_code=401, content={"success": False, "error": "INVALID_TOKEN"})
    except Exception as e:
        logger.error(f"Google OAuth 認證時發生錯誤: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": "OAUTH_ERROR"})


@app.post("/api/chats", response_model=ChatPublic)
async def new_chat(chat_data: ChatCreateRequest):
    result = await create_chat(chat_data.user_id, chat_data.title)
    if result["success"]:
        return result["chat"]
    return JSONResponse(status_code=400, content=result)


@app.get("/api/chats/{user_id}", response_model=ChatListResponse)
async def list_chats(user_id: str):
    result = await get_user_chats(user_id)
    if result["success"]:
        return {"chats": result["chats"]}
    return JSONResponse(status_code=400, content=result)


@app.get("/api/chats/detail/{chat_id}", response_model=ChatDetailResponse)
async def get_chat_detail_api(chat_id: str):
    result = await get_chat(chat_id)
    if result["success"]:
        return result["chat"]
    return JSONResponse(status_code=404, content=result)


@app.post("/api/chats/{chat_id}/messages", response_model=MessagePublic)
async def add_message_api(chat_id: str, message_data: MessageCreateRequest):
    result = await save_chat_message(chat_id, message_data.sender, message_data.content)
    if result["success"]:
        # 僅回傳訊息物件以符合 MessagePublic schema
        msg = result.get("message")
        if isinstance(msg, dict):
            return msg
        # 後備：若無 message 字段，組一個最小結構
        return {
            "sender": message_data.sender,
            "content": message_data.content,
            "timestamp": datetime.now(),
        }
    return JSONResponse(status_code=404 if result.get("error") == "對話不存在" else 400, content=result)


@app.put("/api/chats/{chat_id}/title", response_model=ChatPublic)
async def update_title_api(chat_id: str, title_data: ChatTitleUpdateRequest):
    result = await update_chat_title(chat_id, title_data.title)
    if result["success"]:
        # 取回最新 chat
        chat = await get_chat(chat_id)
        if chat.get("success"):
            return chat["chat"]
        return JSONResponse(status_code=200, content=result)
    return JSONResponse(status_code=404 if result.get("error") == "對話不存在" else 400, content=result)


@app.delete("/api/chats/{chat_id}")
async def remove_chat_api(chat_id: str):
    result = await delete_chat(chat_id)
    if result["success"]:
        return result
    return JSONResponse(status_code=404 if result.get("error") == "對話不存在" else 400, content=result)


# -----------------------------
# 語音登入：綁定說話者標籤到使用者
# -----------------------------
@app.post("/api/users/{user_id}/speaker_label")
async def bind_speaker_label(user_id: str, req: SpeakerLabelBindRequest):
    try:
        from core.database import set_user_speaker_label
        result = await set_user_speaker_label(user_id, req.speaker_label)
        if result.get("success"):
            return {"success": True}
        return JSONResponse(status_code=400, content=result)
    except Exception as e:
        logger.error(f"綁定說話者標籤失敗: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

# -----------------------------
# 檔案上傳/分析 API
# -----------------------------
@app.post("/api/upload-file", response_model=FileAnalysisResponse)
async def upload_and_analyze_file(file: UploadFile = File(...), user_prompt: str = "請分析這個檔案的內容"):
    try:
        MAX_FILE_SIZE = 10 * 1024 * 1024
        contents = await file.read()
        if len(contents) > MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail="檔案大小超過10MB限制")

        allowed_types = [
            'text/plain', 'text/csv', 'text/markdown', 'text/html', 'text/css', 'text/javascript',
            'application/json', 'application/pdf', 'application/xml', 'text/xml',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/bmp', 'image/tiff',
            'text/x-python', 'application/x-python-code'
        ]
        file_type = file.content_type or mimetypes.guess_type(file.filename)[0]
        allowed_extensions = ['.txt', '.csv', '.json', '.md', '.html', '.css', '.js', '.py', '.xml', '.log',
                              '.pdf', '.docx', '.xlsx', '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff']
        is_allowed_type = (file_type and file_type in allowed_types) or (file.filename and any(file.filename.lower().endswith(ext) for ext in allowed_extensions))
        if not is_allowed_type:
            raise HTTPException(status_code=400, detail=f"不支援的檔案類型: {file_type or '未知'}")

        analysis_result = await analyze_file_content(
            filename=file.filename,
            content=contents,
            mime_type=file_type or 'application/octet-stream',
            user_prompt=user_prompt,
        )
        return FileAnalysisResponse(success=True, filename=file.filename, analysis=analysis_result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"分析檔案時發生錯誤: {str(e)}")
        return FileAnalysisResponse(success=False, filename=file.filename or "unknown", error=str(e))


@app.post("/api/analyze-file-base64", response_model=FileAnalysisResponse)
async def analyze_file_from_base64(request: FileAnalysisRequest):
    try:
        file_content = base64.b64decode(request.content)
        MAX_FILE_SIZE = 10 * 1024 * 1024
        if len(file_content) > MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail="檔案大小超過10MB限制")

        analysis_result = await analyze_file_content(
            filename=request.filename,
            content=file_content,
            mime_type=request.mime_type,
            user_prompt=request.user_prompt,
        )
        return FileAnalysisResponse(success=True, filename=request.filename, analysis=analysis_result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"分析base64檔案時發生錯誤: {str(e)}")
        return FileAnalysisResponse(success=False, filename=request.filename, error=str(e))


async def analyze_file_content(filename: str, content: bytes, mime_type: str, user_prompt: str) -> str:
    try:
        if mime_type.startswith('text/'):
            try:
                text_content = content.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    text_content = content.decode('gbk')
                except UnicodeDecodeError:
                    text_content = content.decode('utf-8', errors='ignore')

            max_length = 8000
            if len(text_content) > max_length:
                text_content = text_content[:max_length] + "\n... (檔案內容過長，已截取前8000字符)"

            analysis_prompt = f"""
請詳細分析以下檔案內容（檔案名稱: {filename}，檔案類型: {mime_type}）：

用戶需求：{user_prompt}

檔案內容：
{text_content}

請用繁體中文回答，提供專業且實用的分析結果。
"""

        elif mime_type.startswith('image/'):
            image_base64 = base64.b64encode(content).decode('utf-8')
            return await analyze_image_with_gpt_vision(filename, image_base64, mime_type, user_prompt)

        elif mime_type == 'application/json':
            import json as json_module
            text_content = content.decode('utf-8')
            json_data = json_module.loads(text_content)
            formatted_json = json_module.dumps(json_data, indent=2, ensure_ascii=False)
            analysis_prompt = f"""
請詳細分析以下JSON檔案（檔案名稱: {filename}）：

用戶需求：{user_prompt}

JSON內容：
{formatted_json}

請用繁體中文回答，提供專業的JSON資料分析。
"""

        elif mime_type == 'application/pdf':
            return await analyze_pdf_content(filename, content, user_prompt)
        else:
            return f"檔案類型 {mime_type} 暫時不支援詳細分析，但已成功上傳檔案 {filename}。檔案大小: {len(content)} bytes"

        messages = [
            {"role": "system", "content": "你是一個專業的檔案分析助手，能夠分析各種檔案內容並提供有價值的洞察。"},
            {"role": "user", "content": analysis_prompt},
        ]
        try:
            response = await ai_service.generate_response_for_user(messages=messages, user_id="file_analysis", chat_id=None)
            return response
        except Exception as e:
            logger.error(f"GPT分析時發生錯誤: {str(e)}")
            return f"檔案分析時發生錯誤: {str(e)}"
    except Exception as e:
        logger.error(f"處理檔案內容時發生錯誤: {str(e)}")
        return f"處理檔案時發生錯誤: {str(e)}"


async def analyze_image_with_gpt_vision(filename: str, image_base64: str, mime_type: str, user_prompt: str) -> str:
    try:
        if not hasattr(ai_service, 'client') or ai_service.client is None:
            return f"圖片 {filename} 已上傳成功，但GPT Vision功能暫時不可用。檔案類型: {mime_type}"

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"請分析圖片（{filename}）。用戶需求：{user_prompt}"},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_base64}"}},
                ],
            }
        ]
        try:
            analysis = await ai_service.generate_response_for_user(
                messages=messages,
                user_id="image_analysis",
                chat_id=None,
                max_tokens=1500,
                reasoning_effort="medium",
            )
            return analysis
        except Exception as e:
            logger.error(f"GPT Vision分析錯誤: {str(e)}")
            return f"圖片 {filename} 已上傳成功，但分析時發生錯誤: {str(e)}"
    except Exception as e:
        logger.error(f"圖片分析處理錯誤: {str(e)}")
        return f"圖片分析時發生錯誤: {str(e)}"


async def analyze_pdf_content(filename: str, content: bytes, user_prompt: str) -> str:
    try:
        pdf_text = ""
        try:
            import PyPDF2, io
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(content))
            for page in pdf_reader.pages:
                pdf_text += page.extract_text() + "\n"
        except Exception:
            try:
                import pdfplumber, io
                with pdfplumber.open(io.BytesIO(content)) as pdf:
                    for page in pdf.pages:
                        page_text = page.extract_text()
                        if page_text:
                            pdf_text += page_text + "\n"
            except Exception:
                return await analyze_pdf_with_vision(filename, content, user_prompt)

        if pdf_text.strip():
            max_length = 8000
            if len(pdf_text) > max_length:
                pdf_text = pdf_text[:max_length] + "\n... (PDF內容過長，已截取前8000字符)"
            analysis_prompt = f"""
請詳細分析以下PDF檔案內容（檔案名稱: {filename}）：

用戶需求：{user_prompt}

PDF文字內容：
{pdf_text}

請用繁體中文回答，提供專業且實用的PDF文件分析。
"""
            messages = [
                {"role": "system", "content": "你是一個專業的PDF文件分析助手。"},
                {"role": "user", "content": analysis_prompt},
            ]
            try:
                response = await ai_service.generate_response_for_user(messages=messages, user_id="pdf_analysis", chat_id=None)
                return response
            except Exception as e:
                logger.error(f"GPT分析PDF文字時發生錯誤: {str(e)}")
                return f"PDF文字提取成功，但分析時發生錯誤: {str(e)}\n\n提取的文字內容：\n{pdf_text[:1000]}..."
        else:
            return await analyze_pdf_with_vision(filename, content, user_prompt)
    except Exception as e:
        logger.error(f"PDF分析錯誤: {str(e)}")
        return f"PDF檔案 {filename} 分析遇到問題：{str(e)}"


async def analyze_pdf_with_vision(filename: str, content: bytes, user_prompt: str) -> str:
    try:
        return (
            f"""PDF檔案 {filename} 分析結果：\n\n"
            f"無法直接提取PDF中的文字內容，可能為掃描檔或缺少依賴。\n"
            f"建議：1) 將PDF轉換為文字或圖片；2) 使用OCR；3) 安裝 PyPDF2/pdfplumber。\n"""
        )
    except Exception as e:
        logger.error(f"PDF Vision分析錯誤: {str(e)}")
        return f"PDF分析時發生錯誤: {str(e)}"


# -----------------------------
# 健康數據 API
# -----------------------------
from enum import Enum
from datetime import timedelta

class MetricType(str, Enum):
    HEART_RATE = "heart_rate"
    STEP_COUNT = "step_count"
    OXYGEN_LEVEL = "oxygen_level"
    RESPIRATORY_RATE = "respiratory_rate"
    SLEEP_ANALYSIS = "sleep_analysis"

class HealthDataPoint(BaseModel):
    metric_type: MetricType
    value: float
    unit: str
    timestamp: datetime
    source: Optional[str] = "Apple Health"
    metadata: Optional[Dict[str, Any]] = {}

class HealthSyncRequest(BaseModel):
    device_id: str
    data_points: List[HealthDataPoint]
    sync_timestamp: datetime = Field(default_factory=datetime.utcnow)

class DeviceBindRequest(BaseModel):
    device_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    device_name: str
    device_model: str
    os_version: str
    app_version: str

@app.post("/api/health/device/bind")
async def bind_device(
    request: DeviceBindRequest,
    current_user: dict = Depends(get_current_user_optional)
):
    """綁定設備到用戶帳號"""
    if not current_user:
        return JSONResponse(status_code=401, content={"error": "未授權"})
    
    try:
        if not firestore_db:
            return JSONResponse(status_code=500, content={"error": "Firestore數據庫未連接"})
        
        device_bindings = firestore_db.collection('device_bindings')
        
        # 檢查是否已綁定
        doc_id = f"{request.device_id}_{current_user['sub']}"
        existing_doc = device_bindings.document(doc_id).get()
        
        if existing_doc.exists and existing_doc.to_dict().get("status") == "active":
            return {
                "device_id": request.device_id,
                "bound_at": existing_doc.to_dict()["bound_at"],
                "status": "already_bound"
            }
        
        # 創建新綁定
        binding_doc = {
            "device_id": request.device_id,
            "user_id": current_user["sub"],
            "device_name": request.device_name,
            "device_model": request.device_model,
            "os_version": request.os_version,
            "app_version": request.app_version,
            "bound_at": datetime.utcnow(),
            "status": "active",
            "last_sync": None
        }
        
        device_bindings.document(doc_id).set(binding_doc)
        
        logger.info(f"Device {request.device_id} bound to user {current_user['sub']}")
        
        return {
            "device_id": request.device_id,
            "bound_at": binding_doc["bound_at"],
            "status": "active"
        }
        
    except Exception as e:
        logger.error(f"Device binding failed: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

# 健康數據同步 API 已移除 - iOS App 直接連接 Firestore
# 後端只負責透過 MCP 工具查詢數據

@app.get("/api/health/query")
async def query_health_data(
    metric_type: Optional[MetricType] = None,
    days: int = 7,
    latest_only: bool = False,
    current_user: dict = Depends(get_current_user_optional)
):
    """查詢健康數據"""
    if not current_user:
        return JSONResponse(status_code=401, content={"error": "未授權"})
    
    try:
        health_data_collection = firestore_db.collection('health_data')
        
        # 構建查詢條件
        query = {
            "user_id": current_user["sub"],
            "timestamp": {"$gte": datetime.utcnow() - timedelta(days=days)}
        }
        
        if metric_type:
            query["metric_type"] = metric_type
        
        # 執行查詢
        cursor = health_data_collection.find(query).sort("timestamp", -1)
        
        if latest_only:
            cursor = cursor.limit(1)
        
        data = []
        async for doc in cursor:
            data.append({
                "metric_type": doc["metric_type"],
                "value": doc["value"],
                "unit": doc["unit"],
                "timestamp": doc["timestamp"],
                "source": doc.get("source", "Unknown")
            })
        
        return {
            "status": "success",
            "data": data,
            "count": len(data),
            "query_time": datetime.utcnow()
        }
        
    except Exception as e:
        logger.error(f"Health data query failed: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/api/health/devices")
async def list_devices(current_user: dict = Depends(get_current_user_optional)):
    """列出用戶綁定的設備"""
    if not current_user:
        return JSONResponse(status_code=401, content={"error": "未授權"})
    
    try:
        device_bindings = firestore_db.collection('device_bindings')
        
        devices = []
        query = device_bindings.where(filter=FieldFilter("user_id", "==", current_user["sub"])).where(filter=FieldFilter("status", "==", "active"))
        docs = query.get()
        
        for doc in docs:
            device_data = doc.to_dict()
            devices.append({
                "device_id": device_data["device_id"],
                "device_name": device_data["device_name"],
                "device_model": device_data["device_model"],
                "bound_at": device_data["bound_at"],
                "last_sync": device_data.get("last_sync")
            })
        
        return devices
        
    except Exception as e:
        logger.error(f"Device list failed: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# -----------------------------
# TTS API
# -----------------------------
class TTSRequest(BaseModel):
    """TTS 請求模型"""
    text: str
    voice: Optional[str] = "nova"
    speed: Optional[float] = 1.0
    language: Optional[str] = None
    persona: Optional[str] = "xiaohua"
    mode: Optional[str] = "standard"
    speaking_rate: Optional[float] = None
    markup: Optional[str] = None
    custom_pronunciations: Optional[list[dict]] = None


@app.post("/api/tts")
async def synthesize_speech(
    request: TTSRequest,
    current_user: dict = Depends(get_current_user_optional)
):
    """
    文字轉語音 API

    Args:
        text: 要轉換的文字
        voice: 聲音類型（alloy, echo, fable, onyx, nova, shimmer）
        speed: 語速（0.25 到 4.0）

    Returns:
        完整音頻數據（MP3 格式）
    """
    try:
        from services.tts_service import text_to_speech
        from fastapi.responses import Response

        # 驗證參數
        if not request.text or len(request.text) > 4096:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "文字長度必須在 1-4096 字元之間"}
            )

        valid_voices = [
            "alloy", "echo", "fable", "onyx", "nova", "shimmer", "coral",
            "zh-tw", "zh-cn", "en-us", "ja-jp", "ko-kr", "id-id", "vi-vn"
        ]
        if request.voice not in valid_voices:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": f"無效的聲音類型，支援: {', '.join(valid_voices)}"}
            )

        if not 0.25 <= request.speed <= 4.0:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "語速必須在 0.25 到 4.0 之間"}
            )

        logger.info(
            f"🔊 TTS 請求: text={request.text[:50]}..., voice={request.voice}, speed={request.speed}, "
            f"language={request.language}, persona={request.persona}, speaking_rate={request.speaking_rate}, "
            f"has_markup={bool(request.markup)}, custom_pronunciations={len(request.custom_pronunciations or [])}"
        )

        # 調用 TTS 服務獲取完整音頻
        result = await text_to_speech(
            request.text,
            request.voice,
            request.speed,
            language=request.language,
            persona=request.persona,
            speaking_rate=request.speaking_rate,
        )

        if not result.get("success"):
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": result.get("error", "TTS 合成失敗")}
            )

        audio_data = result.get("audio_data")

        return Response(
            content=audio_data,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=speech.mp3",
                "Cache-Control": "no-cache",
                "Content-Length": str(len(audio_data))
            }
        )

    except Exception as e:
        logger.exception(f"❌ TTS API 錯誤: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.websocket("/ws/tts")
async def tts_stream_websocket(websocket: WebSocket):
    await websocket.accept()
    stream_started_at = time.perf_counter()
    total_chunks = 0
    total_bytes = 0
    first_chunk_at = None
    try:
        payload = await websocket.receive_json()
        text = str(payload.get("text") or "").strip()
        voice = str(payload.get("voice") or "nova")
        speed = float(payload.get("speed") or 1.0)
        language = payload.get("language")
        persona = payload.get("persona") or "xiaohua"
        speaking_rate = payload.get("speaking_rate")
        markup = payload.get("markup")
        custom_pronunciations = payload.get("custom_pronunciations")
        emotion = payload.get("emotion")
        care_mode = bool(payload.get("care_mode", False))

        if not text and not markup:
            await websocket.send_json({"type": "tts_error", "error": "文字不可為空"})
            await websocket.close()
            return

        from services.tts_service import tts_service

        await websocket.send_json({
            "type": "tts_stream_start",
            "sample_rate": 24000,
            "encoding": "LINEAR16",
            "persona": persona,
            "language": language,
        })

        async for chunk in tts_service.streaming_synthesize(
            text=text,
            voice=voice,
            speed=speed,
            language=language,
            persona=persona,
            speaking_rate=speaking_rate,
            markup=markup,
            custom_pronunciations=custom_pronunciations,
            emotion=emotion,
            care_mode=care_mode,
        ):
            total_chunks += 1
            total_bytes += len(chunk)
            if first_chunk_at is None:
                first_chunk_at = time.perf_counter()
            await websocket.send_json({
                "type": "tts_audio_chunk",
                "audio_base64": base64.b64encode(chunk).decode("ascii"),
            })

        logger.debug(
            "📡 TTS 串流傳送完成: chunks=%d bytes=%d first_chunk_delay=%s total_elapsed=%.2fs",
            total_chunks,
            total_bytes,
            f"{(first_chunk_at - stream_started_at):.2f}s" if first_chunk_at is not None else "none",
            time.perf_counter() - stream_started_at,
        )
        await websocket.send_json({"type": "tts_stream_end"})
    except WebSocketDisconnect:
        logger.debug(
            "🔌 TTS 串流連線已由客戶端關閉: chunks=%d bytes=%d first_chunk_delay=%s total_elapsed=%.2fs",
            total_chunks,
            total_bytes,
            f"{(first_chunk_at - stream_started_at):.2f}s" if first_chunk_at is not None else "none",
            time.perf_counter() - stream_started_at,
        )
    except Exception as e:
        error_detail = f"{type(e).__name__}: {str(e) or repr(e)}"
        logger.error(f"❌ TTS 串流失敗: {error_detail}")
        logger.exception("TTS 串流詳細錯誤堆疊:")
        try:
            await websocket.send_json({"type": "tts_error", "error": str(e)})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass



# -----------------------------
# MCP Tools API
# -----------------------------
@app.get("/api/mcp/tools")
async def list_mcp_tools(current_user: dict = Depends(get_current_user_optional)):
    """
    列出所有可用的 MCP 工具及其 metadata

    返回格式：
    {
        "success": true,
        "tools": [
            {
                "name": "weather_query",
                "description": "查詢天氣資訊",
                "category": "天氣",
                "tags": ["weather", "climate"],
                "usage_tips": ["直接說「台北天氣」"],
                "input_schema": {...}
            },
            ...
        ],
        "count": 5
    }
    """
    try:
        # 從 MCPAgentBridge 獲取工具列表
        if not hasattr(app.state, "feature_router"):
            return JSONResponse(
                status_code=503,
                content={"success": False, "error": "MCP 服務未初始化"}
            )

        agent_bridge = app.state.feature_router
        mcp_server = agent_bridge.mcp_server

        tools_metadata = []

        for tool_name, tool in mcp_server.tools.items():
            # 構建工具資訊
            tool_info = {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema
            }

            # 加入 metadata（category, tags, usage_tips）
            if tool.metadata:
                tool_info["category"] = tool.metadata.get("category", "其他")
                tool_info["tags"] = tool.metadata.get("tags", [])
                tool_info["usage_tips"] = tool.metadata.get("usage_tips", [])
            else:
                # 預設值
                tool_info["category"] = "其他"
                tool_info["tags"] = []
                tool_info["usage_tips"] = []

            tools_metadata.append(tool_info)

        logger.info(f"✅ 回傳 {len(tools_metadata)} 個 MCP 工具的 metadata")

        return {
            "success": True,
            "tools": tools_metadata,
            "count": len(tools_metadata)
        }

    except Exception as e:
        logger.exception(f"❌ 獲取 MCP 工具列表失敗: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.get("/api/performance/stats")
async def get_performance_stats(current_user: dict = Depends(get_current_user_optional)):
    """
    獲取系統效能統計

    返回格式：
    {
        "success": true,
        "cache": {
            "user_cache": {"size": 150, "hits": 1500, "misses": 50, "hit_rate": "96.77%"},
            "chat_cache": {"size": 80, "hits": 800, "misses": 20, "hit_rate": "97.56%"},
            "message_cache": {"size": 300, "hits": 3000, "misses": 100, "hit_rate": "96.77%"},
            "memory_cache": {"size": 50, "hits": 500, "misses": 10, "hit_rate": "98.04%"}
        },
        "system": {
            "active_connections": 5,
            "pending_requests": 0
        }
    }
    """
    try:
        from core.database.cache import db_cache

        cache_stats = db_cache.get_all_stats()

        return {
            "success": True,
            "cache": cache_stats,
            "system": {
                "active_connections": len(manager.active_connections),
                "pending_requests": len(db_cache.pending_requests)
            },
            "timestamp": time.time()
        }

    except Exception as e:
        logger.exception(f"❌ 獲取效能統計失敗: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


if __name__ == "__main__":
    # 允許任何設備訪問 - 使用 0.0.0.0 綁定所有網路接口
    # 開發模式會自動列出所有可用的訪問地址
    host = settings.HOST  # 0.0.0.0 表示監聽所有網路接口
    port = settings.PORT  # 固定後端為 8080（本地）或 10000（Render）
    
    # 生產模式：關閉 reload（提升效能與穩定性）
    # 開發時如需熱重載，改為：reload=True
    import sys
    logger.info("\n" + "="*60)
    logger.info("🚀 Bloom Ware 後端服務器啟動中...")
    logger.info("="*60)
    logger.info(f"📡 監聽所有網路接口: {host}:{port}")
    logger.info(f"🌐 可用的訪問地址:")
    logger.info(f"   • 本機: http://127.0.0.1:{port}")
    try:
        import socket
        hostname = socket.gethostname()
        local_ips = [ip for ip in socket.gethostbyname_ex(hostname)[2] if not ip.startswith("127.")]
        for ip in local_ips:
            logger.info(f"   • 局域網: http://{ip}:{port}")
    except:
        pass
    logger.info("="*60 + "\n")

    # 生產模式：reload=False, log_level="error"（只顯示錯誤），關閉 uvicorn access log
    uvicorn.run("app:app", host=host, port=port, reload=False, log_level="error", access_log=False)
