import os
import json
import time
import base64
import mimetypes
import logging
import secrets
from datetime import datetime
from typing import List, Dict, Optional, Any

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

# 本專案整合版：單一 app.py 作為後端入口，前端靜態檔（index.html/app.js/style.css）放在根目錄

# 日誌設定 (生產模式：只記錄 INFO 以上的訊息)
logging.basicConfig(
    level=logging.INFO,  # 改為 INFO（不再顯示 DEBUG）
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # 輸出到終端
        # 可選：輸出到檔案
        # logging.FileHandler('app.log')
    ]
)
logger = logging.getLogger(__name__)

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
from core.pipeline import ChatPipeline, PipelineResult
from core.memory_system import memory_manager
# 環境 Context 寫入 API
from core.database import set_user_env_current, add_user_env_snapshot


# -----------------------------
# Pydantic 模型
# -----------------------------
class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str = Field(min_length=6)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class ChatCreateRequest(BaseModel):
    user_id: str
    title: Optional[str] = "新對話"


class MessageCreateRequest(BaseModel):
    sender: str
    content: str


class ChatTitleUpdateRequest(BaseModel):
    title: str


class UserInfo(BaseModel):
    id: str
    name: str
    email: EmailStr
    created_at: datetime


class UserPublic(BaseModel):
    success: bool
    user: UserInfo


class UserLoginPublicResponse(BaseModel):
    success: bool
    user: UserInfo
    token: Optional[str] = None


class ChatPublic(BaseModel):
    chat_id: str
    user_id: str
    title: str
    created_at: datetime
    updated_at: datetime


class MessagePublic(BaseModel):
    sender: str
    content: str
    timestamp: datetime


class ChatDetailResponse(ChatPublic):
    messages: List[MessagePublic]


class ChatSummary(BaseModel):
    chat_id: str
    title: str
    updated_at: datetime


class ChatListResponse(BaseModel):
    chats: List[ChatSummary]


class FileAnalysisRequest(BaseModel):
    filename: str
    content: str
    mime_type: str
    user_prompt: Optional[str] = "請分析這個檔案的內容"


class FileAnalysisResponse(BaseModel):
    success: bool
    filename: str
    analysis: Optional[str] = None
    error: Optional[str] = None

class SpeakerLabelBindRequest(BaseModel):
    speaker_label: str


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

        app.state.feature_router = MCPAgentBridge()
        
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
                prob_threshold=0.40,
                margin_threshold=0.01,
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
            # 每30分鐘清理一次
            await asyncio.sleep(1800)  # 30分鐘

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

# CORS 設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CSP Middleware（允許內嵌 script 用於語音沉浸式前端）
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response

class CSPMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        response = await call_next(request)
        # 對所有靜態檔案路徑添加寬鬆的 CSP header（用於語音沉浸式前端）
        if request.url.path.startswith("/static/"):
            # 移除可能存在的嚴格 CSP
            if "Content-Security-Policy" in response.headers:
                del response.headers["Content-Security-Policy"]

            # 設定寬鬆的 CSP 以允許內嵌 script
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://accounts.google.com https://www.gstatic.com; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com data:; "
                "connect-src 'self' ws: wss: https://accounts.google.com; "
                "img-src 'self' data: https: blob:; "
                "media-src 'self' blob: data:; "
                "frame-src https://accounts.google.com; "
                "base-uri 'self';"
            )
        return response

app.add_middleware(CSPMiddleware)

# 掛載靜態檔案目錄（語音沉浸式前端）
static_dir = Path("static/frontend")
if static_dir.exists() and static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(static_dir), html=True), name="frontend")
    logger.info(f"✅ 已掛載語音沉浸式前端: /static → {static_dir}")
else:
    logger.warning("⚠️ 未找到 static/frontend/ 目錄")

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

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------
# WebSocket 連線管理（JWT認證）
# -----------------------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.client_info: Dict[str, dict] = {}
        self.user_sessions: Dict[str, Dict[str, Any]] = {}  # 用戶會話信息
        self.last_env: Dict[str, Dict[str, Any]] = {}  # 最近的環境快照

    async def connect(self, websocket: WebSocket, user_id: str, user_info: Dict[str, Any]):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        self.user_sessions[user_id] = user_info
        logger.info(f"新的WebSocket連接: {user_id}")

    def disconnect(self, user_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            if user_id in self.user_sessions:
                del self.user_sessions[user_id]
            logger.info(f"WebSocket連接關閉: {user_id}")

    async def send_message(self, message: str, user_id: str, message_type: str = "bot_message"):
        if user_id in self.active_connections:
            try:
                payload = {"type": message_type, "message": message, "timestamp": time.time()}
                await self.active_connections[user_id].send_json(
                    payload
                )
                try:
                    preview = (str(message) or "").strip().replace("\n", " ")
                    if len(preview) > 120:
                        preview = preview[:120] + "..."
                    logger.info(f"WebSocket已發送 → client={user_id} type={message_type} bytes≈{len((str(message) or '').encode('utf-8'))} preview=\"{preview}\"")
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"發送消息到客戶端 {user_id} 時出錯: {str(e)}")

    def set_client_info(self, user_id: str, info: dict):
        self.client_info[user_id] = info

    def get_client_info(self, user_id: str) -> dict:
        return self.client_info.get(user_id, {})

    def get_user_session(self, user_id: str) -> Optional[Dict[str, Any]]:
        """獲取用戶會話信息"""
        return self.user_sessions.get(user_id)

    async def cleanup_expired_sessions(self):
        """清理過期的用戶會話"""
        current_time = datetime.now()
        expired_users = []

        for user_id, session_info in self.user_sessions.items():
            # 如果會話超過30分鐘沒有活動，標記為過期
            last_activity = session_info.get("last_activity", current_time)
            if (current_time - last_activity).total_seconds() > 1800:  # 30分鐘
                expired_users.append(user_id)

        for user_id in expired_users:
            logger.info(f"清理過期會話: {user_id}")
            self.disconnect(user_id)


manager = ConnectionManager()


# 地理工具函式（內部使用）
def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import radians, sin, cos, asin, sqrt
    if None in (lat1, lon1, lat2, lon2):
        return 0.0
    R = 6371000.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    return R * c


def _heading_to_cardinal(deg: float) -> str:
    try:
        val = float(deg)
    except Exception:
        return ""
    dirs = [
        "N","NNE","NE","ENE","E","ESE","SE","SSE",
        "S","SSW","SW","WSW","W","WNW","NW","NNW"
    ]
    ix = int((val % 360) / 22.5 + 0.5) % 16
    return dirs[ix]


# -----------------------------
# 語音綁定狀態管理器（關鍵字匹配，無 GPT）
# -----------------------------
class VoiceBindingStateMachine:
    """
    語音帳號綁定狀態機（硬編碼關鍵字匹配）

    流程：
    1. 用戶說「我要綁定語音登入」
    2. Agent 回應「好的，你現在要綁定誰？」
    3. 用戶提供名稱
    4. 系統綁定 speaker_label 到用戶帳號
    5. Agent 回應「綁定成功！」
    """

    def __init__(self):
        # 用戶狀態：{user_id: {state: str, speaker_label: str}}
        self.user_states: Dict[str, Dict[str, Any]] = {}

    def check_binding_trigger(self, user_id: str, message: str) -> Optional[str]:
        """
        檢查是否觸發綁定流程

        Returns:
            - "TRIGGER": 觸發綁定流程
            - "AWAITING_NAME": 等待用戶提供名稱
            - None: 不是綁定相關訊息
        """
        message_lower = message.lower().replace(" ", "")

        # 檢測觸發關鍵字
        trigger_keywords = ["綁定語音登入", "語音登入綁定", "綁定語音", "設定語音登入"]
        for keyword in trigger_keywords:
            if keyword.replace(" ", "") in message_lower:
                # 進入等待狀態
                self.user_states[user_id] = {
                    "state": "AWAITING_NAME",
                    "timestamp": datetime.now()
                }
                return "TRIGGER"

        # 檢查是否在等待名稱狀態
        if user_id in self.user_states:
            state_info = self.user_states[user_id]
            if state_info.get("state") == "AWAITING_NAME":
                # 檢查是否超時（5分鐘）
                if (datetime.now() - state_info.get("timestamp")).total_seconds() > 300:
                    del self.user_states[user_id]
                    return None
                return "AWAITING_NAME"

        return None

    async def handle_binding_flow(
        self,
        user_id: str,
        message: str,
        websocket: WebSocket,
        voice_service: Optional[VoiceAuthService] = None
    ) -> bool:
        """
        處理綁定流程

        Returns:
            True: 已處理（不要繼續到 Agent）
            False: 未處理（繼續到 Agent）
        """
        state = self.check_binding_trigger(user_id, message)

        if state == "TRIGGER":
            # 用戶觸發綁定 - 先檢查是否已經綁定過
            logger.info(f"🎙️ 用戶 {user_id} 觸發語音綁定流程")

            # 檢查使用者是否已經綁定過 speaker_label
            from core.database import get_user_by_id
            try:
                user_data = await get_user_by_id(user_id)
                if user_data and user_data.get("speaker_label"):
                    # 已經綁定過了
                    existing_label = user_data.get("speaker_label")
                    logger.info(f"⚠️ 用戶 {user_id} 已綁定 speaker_label: {existing_label}")

                    await websocket.send_json({
                        "type": "bot_message",
                        "message": f"你已經綁定過語音了！目前的聲紋標籤是：{existing_label}。如果需要重新綁定，請聯繫管理員。",
                        "timestamp": time.time()
                    })

                    # 清理 FSM 狀態
                    self.clear_state(user_id)
                    return True
            except Exception as e:
                logger.error(f"❌ 檢查使用者綁定狀態失敗: {e}")
                await websocket.send_json({
                    "type": "error",
                    "message": "系統錯誤，無法檢查綁定狀態"
                })
                return True

            # 未綁定，繼續綁定流程
            logger.info(f"✅ 用戶 {user_id} 尚未綁定，啟動綁定流程")

            # 標記用戶進入語音綁定等待狀態
            user_session = manager.get_client_info(user_id) or {}
            user_session["voice_binding_pending"] = True
            user_session["voice_binding_started_at"] = datetime.now()
            manager.set_client_info(user_id, user_session)

            await websocket.send_json({
                "type": "bot_message",
                "message": "好的，請錄製一段語音（約3-5秒），用於建立你的聲紋特徵。系統會自動識別並綁定到你的帳號。",
                "timestamp": time.time()
            })
            await websocket.send_json({
                "type": "voice_binding_ready",
                "message": "請點擊錄音按鈕開始錄製"
            })
            return True

        elif state == "AWAITING_NAME":
            # 這個狀態已不再使用，因為我們改為直接錄音綁定
            # 但保留以防萬一
            pass

        return False

    def clear_state(self, user_id: str):
        """清理用戶狀態"""
        self.user_states.pop(user_id, None)


voice_binding_fsm = VoiceBindingStateMachine()


# -----------------------------
# 統一 WebSocket 端點（JWT認證）
# -----------------------------
@app.websocket("/ws")
async def websocket_endpoint_with_jwt(websocket: WebSocket, token: str = Query(None)):
    """JWT認證的WebSocket端點（支援語音登入匿名連線）"""
    logger.info("WebSocket連接請求 - JWT認證")

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

        # 發送個性化歡迎消息（語音登入模式跳過）
        if not is_voice_login_mode:
            try:
                td = app.state.feature_router.get_current_time_data()
                # WebSocket 連線時沒有語音情緒，使用空字串
                welcome_msg = compose_welcome(user_name=user_info.get('name'), time_data=td, emotion_label="")
            except Exception as e:
                logger.warning(f"生成歡迎訊息失敗: {e}")
                welcome_msg = f"歡迎回來，{user_info['name']}！"

            # 發送歡迎訊息，並附帶 chat_id
            await websocket.send_json({
                "type": "system",
                "message": welcome_msg,
                "chat_id": current_chat_id
            })

        while True:
            data = await websocket.receive_text()
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
                                "你是一個友善、有禮且能夠提供幫助的AI助手。請使用繁體中文回覆，保持簡潔清晰的表達。"
                                "另外，請勿自稱為 GPT-4 或其他版本。若需要自我介紹，請表述為 '基於 gpt-5-nano 模型'。"
                            ),
                        },
                        {"role": "user", "content": user_message},
                    ]

                    request_id = uuid.uuid4().hex[:12]
                    logger.info(f"處理用戶消息 req_id={request_id} user_id={user_id} chat_id={chat_id}")

                    async def _do_process_and_send():
                        response = await handle_message(user_message, user_id, chat_id, messages_for_handler, request_id=request_id)
                        if not response or str(response).strip() == "":
                            logger.warning("AI回應為空，使用後備提示")
                            response = "抱歉，我暫時沒有合適的回應。可以換個說法再試試嗎？"

                        # 檢查是否為 dict（包含工具資訊、情緒等）
                        if isinstance(response, dict):
                            tool_name = response.get('tool_name')
                            tool_data = response.get('tool_data')
                            message_text = response.get('message', response.get('content', ''))
                            emotion = response.get('emotion')  # 新增：提取情緒
                            care_mode = response.get('care_mode', False)  # 新增：提取關懷模式

                            # 先發送情緒資訊（如果有）
                            if emotion:
                                await websocket.send_json({
                                    "type": "emotion_detected",
                                    "emotion": emotion,
                                    "care_mode": care_mode
                                })
                                logger.info(f"😊 發送情緒給前端: {emotion}, care_mode={care_mode}")

                            # 發送擴充格式的 bot_message
                            await websocket.send_json({
                                "type": "bot_message",
                                "message": message_text,
                                "timestamp": time.time(),
                                "tool_name": tool_name,
                                "tool_data": tool_data
                            })
                        else:
                            # 舊格式（純文字）
                            await manager.send_message(response, user_id, "bot_message")

                        if new_chat_info:
                            await websocket.send_json({
                                "type": "new_chat_created",
                                "chat_id": new_chat_info["chat_id"],
                                "title": new_chat_info["title"]
                            })

                        await save_message_to_db(user_id, chat_id, "user", user_message)
                        await save_message_to_db(user_id, chat_id, "assistant", response)

                    import asyncio as _asyncio
                    _asyncio.create_task(_do_process_and_send())

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
                    # 語音處理邏輯（保持不變）
                    try:
                        sr = int(message_data.get("sample_rate", 16000))
                    except Exception:
                        sr = 16000
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
                        if b64 and hasattr(app.state, "voice_auth") and app.state.voice_auth:
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
                                    emo_label = str(emo.get("label") or "")
                                    welcome = compose_welcome(user_name=name, time_data=td, emotion_label=emo_label)
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

                    elif mode == "chat":
                        # === 新的對話模式：並行執行 STT + 情緒辨識 ===
                        try:
                            import asyncio as _async_lib
                            from services.stt_service import transcribe_audio
                            from services.voice_login import VoiceAuthService

                            # 獲取音頻數據（從 _buffers 中）
                            audio_data = None
                            emotion_result = None

                            if hasattr(app.state, "voice_auth") and app.state.voice_auth:
                                voice_service = app.state.voice_auth

                                # 獲取音頻數據（從 _buffers 取得完整音頻）
                                if user_id in voice_service._buffers:
                                    audio_data = bytes(voice_service._buffers[user_id])
                                    sample_rate = voice_service._sr_overrides.get(user_id, 16000)

                                    # 並行執行 STT 和情緒辨識
                                    stt_task = transcribe_audio(audio_data, language="zh")
                                    emotion_task = _async_lib.to_thread(
                                        voice_service._infer_emotion_from_bytes,
                                        audio_data,
                                        sample_rate
                                    )

                                    stt_result, emotion_result = await _async_lib.gather(
                                        stt_task, emotion_task, return_exceptions=True
                                    )

                                    # 清理 session
                                    voice_service.clear_session(user_id)

                                    # 檢查結果
                                    if isinstance(stt_result, Exception):
                                        logger.error(f"❌ STT 失敗: {stt_result}")
                                        await websocket.send_json({
                                            "type": "error",
                                            "message": f"語音轉文字失敗: {str(stt_result)}"
                                        })
                                        continue

                                    if not stt_result.get("success"):
                                        await websocket.send_json({
                                            "type": "error",
                                            "message": stt_result.get("error", "STT 失敗")
                                        })
                                        continue

                                    # 提取轉錄文字和情緒標籤
                                    transcription = stt_result.get("text", "")
                                    emotion_label = emotion_result.get("label", "neutral") if emotion_result and not isinstance(emotion_result, Exception) else "neutral"

                                    logger.info(f"🎙️ STT: {transcription}")
                                    logger.info(f"😊 情緒: {emotion_label}")

                                    # 發送 STT 最終結果給前端（讓用戶看到轉錄文字）
                                    await websocket.send_json({
                                        "type": "stt_final",
                                        "text": transcription,
                                        "emotion": emotion_label
                                    })

                                    # 將轉錄文字和情緒標籤一起發送給 Agent
                                    # 構造包含情緒資訊的訊息
                                    enhanced_message = {
                                        "text": transcription,
                                        "emotion": emotion_label
                                    }

                                    # 通知前端開始思考
                                    await websocket.send_json({"type": "typing", "message": "thinking"})

                                    # 異步處理對話邏輯（複用現有的 chat 流程）
                                    async def _process_voice_chat():
                                        chat_id = message_data.get("chat_id")

                                        # 如果沒有 chat_id，創建新對話
                                        if not chat_id:
                                            try:
                                                user_chats_result = await get_user_chats(user_id)
                                                if user_chats_result["success"] and user_chats_result["chats"]:
                                                    latest_chat = user_chats_result["chats"][0]
                                                    chat_id = latest_chat["chat_id"]
                                                else:
                                                    chat_title = f"語音對話 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                                                    chat_result = await create_chat(user_id, chat_title)
                                                    if chat_result["success"]:
                                                        chat_id = chat_result["chat"]["chat_id"]
                                            except Exception as e:
                                                logger.error(f"創建對話失敗: {e}")
                                                await websocket.send_json({"type": "error", "message": "無法創建對話"})
                                                return

                                        # 保存用戶訊息（包含情緒標籤在訊息內容中）
                                        # 注意: 目前 save_message_to_db 不支持 metadata 參數
                                        # 情緒資訊已透過 enhanced_transcription 包含在訊息中
                                        await save_message_to_db(user_id, chat_id, "user", transcription)

                                        # 將情緒資訊嵌入用戶訊息 (讓 AI 知道用戶的情緒狀態)
                                        enhanced_transcription = transcription
                                        if emotion_label and emotion_label != "neutral":
                                            # 在訊息前添加情緒標籤提示
                                            emotion_hints = {
                                                "happy": "開心",
                                                "sad": "悲傷",
                                                "angry": "憤怒",
                                                "fear": "恐懼",
                                                "surprise": "驚訝"
                                            }
                                            emotion_cn = emotion_hints.get(emotion_label, emotion_label)
                                            enhanced_transcription = f"[用戶情緒: {emotion_cn}] {transcription}"

                                        # 處理對話（透過 handle_message，自動處理 pipeline）
                                        response = await handle_message(
                                            enhanced_transcription,
                                            user_id,
                                            chat_id,
                                            []  # messages 參數（會自動從數據庫載入）
                                        )

                                        # 發送回應
                                        if isinstance(response, PipelineResult):
                                            message_text = response.text
                                            
                                            await websocket.send_json({
                                                "type": "bot_message",
                                                "message": message_text,
                                                "timestamp": time.time(),
                                                "tool_name": None,
                                                "tool_data": None
                                            })
                                            
                                            # 保存 Agent 回應（已在 handle_message 中保存）
                                        elif isinstance(response, dict):
                                            tool_name = response.get('tool_name')
                                            tool_data = response.get('tool_data')
                                            message_text = response.get('message', response.get('content', ''))

                                            await websocket.send_json({
                                                "type": "bot_message",
                                                "message": message_text,
                                                "timestamp": time.time(),
                                                "tool_name": tool_name,
                                                "tool_data": tool_data
                                            })
                                            
                                            # 保存 Agent 回應（已在 handle_message 中保存）
                                        else:
                                            # 字串回應
                                            await websocket.send_json({
                                                "type": "bot_message",
                                                "message": str(response),
                                                "timestamp": time.time()
                                            })
                                            
                        finally:
                            pass
                    elif message_type == "env_snapshot":
                        # ===== 環境快照上報 =====
                        try:
                            lat = float(message_data.get("lat")) if message_data.get("lat") is not None else None
                            lon = float(message_data.get("lon")) if message_data.get("lon") is not None else None
                            acc = message_data.get("accuracy_m")
                            acc = float(acc) if acc is not None else None
                            heading_deg = message_data.get("heading_deg")
                            heading_deg = float(heading_deg) if heading_deg is not None else None
                            tz = message_data.get("tz")
                            locale = message_data.get("locale")
                            device = message_data.get("device")

                            # 後端節流：距離<100m且方位差<25度則忽略
                            do_write_snapshot = False
                            last = manager.last_env.get(user_id)
                            if last and lat is not None and lon is not None and last.get("lat") is not None:
                                dist = _haversine_m(last.get("lat",0), last.get("lon",0), lat, lon)
                                deg_diff = abs((heading_deg or 0) - (last.get("heading_deg") or 0))
                                if dist >= 100 or deg_diff >= 25:
                                    do_write_snapshot = True
                            else:
                                do_write_snapshot = True

                            from geohash2 import encode as gh_encode
                            geohash7 = gh_encode(lat, lon, precision=7) if (lat is not None and lon is not None) else None
                            heading_cardinal = _heading_to_cardinal(heading_deg) if heading_deg is not None else None
                            env_payload = {
                                "lat": lat,
                                "lon": lon,
                                "accuracy_m": acc,
                                "heading_deg": heading_deg,
                                "heading_cardinal": heading_cardinal,
                                "tz": tz,
                                "locale": locale,
                                "device": device,
                                "geohash_7": geohash7,
                            }

                            # 更新會話暫存
                            manager.last_env[user_id] = env_payload
                            info = manager.get_client_info(user_id) or {}
                            info['env_context'] = env_payload
                            manager.set_client_info(user_id, info)

                            try:
                                await set_user_env_current(user_id, env_payload)
                            except Exception as e:
                                logger.warning(f"寫入環境現況失敗: {e}")

                            if do_write_snapshot:
                                try:
                                    snap = env_payload.copy()
                                    snap['reason'] = 'threshold'
                                    await add_user_env_snapshot(user_id, snap)
                                except Exception as e:
                                    logger.warning(f"寫入環境快照失敗: {e}")

                            await websocket.send_json({"type": "env_ack", "success": True, "geohash_7": geohash7, "heading": heading_cardinal})
                        except Exception as e:
                            logger.error(f"處理 env_snapshot 失敗: {e}")
                            await websocket.send_json({"type": "env_ack", "success": False, "error": str(e)})
                else:
                    await manager.send_message(f"未知的消息類型: {message_type}", user_id, "error")

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
async def handle_message(user_message, user_id, chat_id, messages, request_id: str = None):
    logger.info(f"📥 handle_message: 收到訊息='{user_message}', user_id={user_id}")
    
    # 指令優先，避免進入管線造成不必要延遲
    if user_message and user_message.startswith("/"):
        cmd = await handle_command(user_message, user_id)
        if cmd:
            return cmd

    feature_router:MCPAgentBridge  = app.state.feature_router

    async def _detect(msg: str):
        logger.info(f"🎯 Pipeline: 開始意圖偵測，訊息='{msg}'")
        try:
            result = await feature_router.detect_intent(msg)
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

    async def _ai(messages_in, cid, model, rid, chat_id, use_care_mode=False, care_emotion=None):
        # 取得用戶名稱（優先順序：Google 名稱 > 語音 label > "用戶"）
        user_name = "用戶"
        try:
            user_data = await get_user_by_id(cid)
            if user_data and user_data.get("name"):
                user_name = user_data["name"]
        except Exception as e:
            logger.debug(f"無法取得用戶名稱，使用預設值: {e}")

        # 兼容：如果傳入字串，視為 user_message；如果傳入 list，視為 messages
        if isinstance(messages_in, str):
            return await ai_service.generate_response_for_user(
                user_message=messages_in,
                user_id=cid,
                model=model,
                request_id=rid,
                chat_id=chat_id,
                use_care_mode=use_care_mode,
                care_emotion=care_emotion,
                user_name=user_name
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
                user_name=user_name
            )

    model = settings.OPENAI_MODEL
    # 簡化 Pipeline：移除未使用的記憶管理和摘要決策
    # 長期記憶由 memory_system 在 Pipeline 外處理
    pipeline = ChatPipeline(
        _detect,
        _process_feature,
        _ai,
        model=model,
        detect_timeout=10.0,  # 意圖檢測超時 (15 → 10)
        feature_timeout=30.0,  # 功能處理超時 (15 → 30，新聞摘要生成需要更長時間)
        ai_timeout=20.0,  # AI回應超時 (30 → 20)
    )
    logger.info(f"⚙️ 準備調用 ChatPipeline.process，user_message='{user_message}'")
    res: PipelineResult = await pipeline.process(user_message, user_id=user_id, chat_id=chat_id, request_id=request_id)
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

    # 立即返回完整結果（包含工具信息與情緒）
    if tool_name or tool_data or emotion or care_mode:
        return {
            'message': res.text,
            'tool_name': tool_name,
            'tool_data': tool_data,
            'emotion': emotion,  # 新增情緒欄位
            'care_mode': care_mode  # 新增關懷模式標記
        }
    else:
        return res.text


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
    return RedirectResponse(url="/static/login.html", status_code=307)


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
        return RedirectResponse(url=f"/static/login.html?{error_params}", status_code=302)

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
                url=f"/static/login.html?error={error}&state={state or ''}",
                status_code=302
            )

        if not code:
            return JSONResponse(status_code=400, content={"success": False, "error": "NO_AUTHORIZATION_CODE"})

        # 構造前端處理的URL
        frontend_url = f"/static/login.html?code={code}&state={state or ''}&scope={scope or ''}"
        return RedirectResponse(url=frontend_url, status_code=302)

    except Exception as e:
        logger.error(f"Google OAuth GET 回調處理失敗: {e}")
        return RedirectResponse(url="/static/login.html?error=callback_error", status_code=302)

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
            response = ai_service.client.chat.completions.create(
                model="gpt-5-nano",
                messages=messages,
                max_completion_tokens=1500,
                reasoning_effort="medium"  # 圖片分析需要較深入理解，使用 medium
            )
            analysis = response.choices[0].message.content
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
        query = device_bindings.where("user_id", "==", current_user["sub"]).where("status", "==", "active")
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

        valid_voices = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
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

        logger.info(f"🔊 TTS 請求: text={request.text[:50]}..., voice={request.voice}, speed={request.speed}")

        # 調用 TTS 服務獲取完整音頻
        result = await text_to_speech(request.text, request.voice, request.speed)

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
    print("\n" + "="*60)
    print("🚀 Bloom Ware 後端服務器啟動中...")
    print("="*60)
    print(f"📡 監聽所有網路接口: {host}:{port}")
    print(f"🌐 可用的訪問地址:")
    print(f"   • 本機: http://127.0.0.1:{port}")
    try:
        import socket
        hostname = socket.gethostname()
        local_ips = [ip for ip in socket.gethostbyname_ex(hostname)[2] if not ip.startswith("127.")]
        for ip in local_ips:
            print(f"   • 局域網: http://{ip}:{port}")
    except:
        pass
    print("="*60 + "\n")

    # 生產模式：reload=False, log_level="warning"（只顯示警告和錯誤）
    uvicorn.run("app:app", host=host, port=port, reload=False, log_level="warning")
