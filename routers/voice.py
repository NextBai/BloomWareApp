"""
語音相關 API 路由
包含語音登入、TTS、STT 等
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from core.auth import require_auth
from core.database import set_user_speaker_label, get_user_by_speaker_label

logger = logging.getLogger("routers.voice")

router = APIRouter(prefix="/api/voice", tags=["語音"])


class SpeakerLabelBindRequest(BaseModel):
    """綁定語音標籤請求"""
    speaker_label: str


class TTSRequest(BaseModel):
    """TTS 請求"""
    text: str
    voice: str = "coral"
    speed: float = 1.0
    emotion: Optional[str] = None  # 情緒標籤（neutral, happy, sad, angry, fear, surprise）
    care_mode: bool = False  # 是否為關懷模式


@router.post("/bind-speaker")
async def bind_speaker_label(
    request: SpeakerLabelBindRequest,
    user: dict = Depends(require_auth)
):
    """
    綁定語音標籤到用戶帳號
    """
    user_id = user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="無效的用戶")

    result = await set_user_speaker_label(user_id, request.speaker_label)
    
    if not result.get("success"):
        error = result.get("error")
        if error == "SPEAKER_LABEL_TAKEN":
            raise HTTPException(status_code=409, detail="此語音標籤已被其他用戶綁定")
        elif error == "USER_NOT_FOUND":
            raise HTTPException(status_code=404, detail="用戶不存在")
        else:
            raise HTTPException(status_code=500, detail=error)

    return {"success": True, "message": "語音標籤綁定成功"}


@router.get("/lookup-speaker/{speaker_label}")
async def lookup_speaker(speaker_label: str):
    """
    根據語音標籤查找用戶（用於語音登入）
    """
    user = await get_user_by_speaker_label(speaker_label)
    
    if not user:
        raise HTTPException(status_code=404, detail="找不到對應的用戶")

    return {
        "success": True,
        "user": {
            "id": user.get("id"),
            "name": user.get("name"),
        }
    }


@router.post("/tts")
async def text_to_speech(
    request: TTSRequest,
    user: dict = Depends(require_auth)
):
    """
    文字轉語音
    """
    try:
        from services.tts_service import tts_service
        
        result = await tts_service.synthesize(
            text=request.text,
            voice=request.voice,
            speed=request.speed,
            emotion=request.emotion,
            care_mode=request.care_mode,
        )

        if not result.get("success"):
            raise HTTPException(status_code=500, detail=result.get("error"))

        # 返回 base64 編碼的音頻
        import base64
        audio_base64 = base64.b64encode(result["audio_data"]).decode("utf-8")

        return {
            "success": True,
            "audio": audio_base64,
            "voice": result.get("voice"),
        }

    except ImportError:
        raise HTTPException(status_code=503, detail="TTS 服務不可用")
    except Exception as e:
        logger.exception(f"TTS 失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class VoiceLoginRequest(BaseModel):
    """語音登入請求"""
    audio_base64: str  # base64 編碼的 PCM16 音訊
    sample_rate: int = 16000


class VoiceLoginResponse(BaseModel):
    """語音登入回應"""
    success: bool
    access_token: str = None
    user: dict = None
    emotion: str = None
    error: str = None


@router.post("/login", response_model=VoiceLoginResponse)
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
    import jwt
    from datetime import datetime, timedelta
    from core.config import settings
    
    try:
        # 取得 VoiceAuthService 實例
        from fastapi import Request
        from main import app
        
        voice_auth = getattr(app.state, "voice_auth", None)
        if not voice_auth:
            # 嘗試動態建立
            from services.voice_login import VoiceAuthService, VoiceLoginConfig
            voice_auth = VoiceAuthService(config=VoiceLoginConfig(
                window_seconds=3,
                required_windows=1,
            ))
        
        # 解碼音訊
        audio_bytes = base64.b64decode(request.audio_base64)
        
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
            return VoiceLoginResponse(
                success=False,
                error=error_messages.get(error_code, f"辨識失敗：{error_code}")
            )

        quality_warnings = result.get("quality_warnings") or []
        if quality_warnings:
            logger.warning(f"🎙️ 語音登入品質警告（未阻擋）: {quality_warnings}")
        
        # 取得辨識結果
        speaker_label = result.get("label")
        emotion = result.get("emotion", {})
        emotion_label = emotion.get("label", "neutral") if isinstance(emotion, dict) else "neutral"
        
        logger.info(f"🎙️ 語音辨識成功: speaker={speaker_label}, emotion={emotion_label}")
        
        # 查詢對應的用戶
        user = await get_user_by_speaker_label(speaker_label)
        
        if not user:
            return VoiceLoginResponse(
                success=False,
                error=f"找不到綁定的帳號。請先使用 Google 登入並綁定語音。"
            )
        
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
        
        token = jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")
        
        logger.info(f"✅ 語音登入成功: user={user_name}, emotion={emotion_label}")
        
        return VoiceLoginResponse(
            success=True,
            access_token=token,
            user={
                "id": user_id,
                "name": user_name,
                "email": user_email,
            },
            emotion=emotion_label,
        )
        
    except Exception as e:
        logger.exception(f"❌ 語音登入失敗: {e}")
        return VoiceLoginResponse(
            success=False,
            error=f"系統錯誤：{str(e)}"
        )
