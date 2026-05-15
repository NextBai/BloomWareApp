"""
Google Cloud Speech-to-Text v2 串流辨識（gRPC StreamingRecognize）。

注意：語音 GCP（STT/TTS 所屬專案，例如 supervisor-project）與 Firebase、
Google OAuth 登入是不同脈絡——專案 ID、API Key、服務帳戶請勿與 Firestore 混用。
STT 串流僅支援 gRPC + OAuth（服務帳戶）；API Key 僅供 TTS REST 等用途。

音訊限制見官方文件：每則 StreamingRecognize 訊息（含首則設定）上限 25 KB。
前端送 LINEAR16 mono PCM；依 sample_rate 設定 explicit decoding。
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
from typing import Any, Callable, Coroutine, List, Optional

from dotenv import load_dotenv
from google.oauth2 import credentials as oauth2_credentials
from google.oauth2 import service_account

from core.config import settings

load_dotenv()

logger = logging.getLogger("services.realtime_stt")

# 官方上限 25 KB；保留餘量避免邊界錯誤
_MAX_STREAMING_BYTES = 24 * 1024
# 即時串流：每累積 3200 bytes（~100ms @ 16kHz 16-bit mono）就送出一次，減少初始延遲
_FLUSH_THRESHOLD_BYTES = 3200

SUPPORTED_LANGUAGES = {
    "zh": ["cmn-Hant-TW", "cmn-Hans-CN", "yue-Hant-HK"],
    "zh-TW": ["cmn-Hant-TW"],
    "zh-CN": ["cmn-Hans-CN"],
    "en": ["en-US", "en-GB"],
    "ja": ["ja-JP"],
    "ko": ["ko-KR"],
    "id": ["id-ID"],
    "vi": ["vi-VN"],
    "th": ["th-TH"],
    "fr": ["fr-FR"],
    "de": ["de-DE"],
    "es": ["es-ES", "es-US"],
}

DEFAULT_AUTO_LANGUAGE_CODES = ["cmn-Hant-TW", "en-US", "ja-JP"]


def _normalize_v2_model(model: str) -> str:
    m = (model or "long").strip().lower()
    if m in ("latest_long", "default"):
        return "long"
    if m in ("latest_short",):
        return "short"
    return (model or "long").strip()


class RealtimeSTTService:
    """Speech-to-Text v2 雙向串流；需 OAuth（服務帳戶或有效 access token），不支援僅 API Key。"""

    def __init__(self) -> None:
        self.location = settings.GOOGLE_STT_LOCATION
        self.recognizer_id = settings.GOOGLE_STT_RECOGNIZER_ID
        self.api_key = settings.GOOGLE_SPEECH_API_KEY
        self.project_id = ""
        self._grpc_credentials = None
        self._reload_speech_identity()
        self.current_language = "auto"
        self.sample_rate = 16000
        self.model = "long"
        self.is_connected = False
        self._audio_buffer = bytearray()
        self._pending_send = bytearray()
        self._final_transcript: Optional[str] = None
        self._final_transcript_event = asyncio.Event()
        self._on_transcript_delta: Optional[Callable[[str], Any]] = None
        self._on_transcript_done: Optional[Callable[[str], Any]] = None
        self._on_status: Optional[Callable[[str], Any]] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._audio_thread_queue: Optional[queue.Queue] = None
        self._grpc_thread: Optional[threading.Thread] = None
        self._final_segments: List[str] = []
        self._speech_account_source: str = "none"

    def _language_codes(self, language: str) -> list[str]:
        lang = (language or "auto").strip()
        if lang in {"auto", "detect", ""}:
            configured = [
                item.strip()
                for item in settings.GOOGLE_STT_AUTO_LANGUAGE_CODES.split(",")
                if item.strip()
            ]
            return (configured or DEFAULT_AUTO_LANGUAGE_CODES)[:3]
        return SUPPORTED_LANGUAGES.get(lang, DEFAULT_AUTO_LANGUAGE_CODES)[:3]

    def _recognizer_name(self) -> str:
        return (
            f"projects/{self.project_id}/locations/{self.location}"
            f"/recognizers/{self.recognizer_id}"
        )

    def _validate_config(self) -> Optional[str]:
        if self._grpc_credentials is None:
            if self.api_key:
                return (
                    "STT 串流需 gRPC + OAuth（語音專案請設 GOOGLE_SPEECH_* 服務帳戶）；"
                    "僅 API Key 無法用於 Speech v2 streaming（API Key 可給 TTS REST）"
                )
            return (
                "Google STT 串流需要 OAuth 憑證：請設定 GOOGLE_SPEECH_SERVICE_ACCOUNT_PATH "
                "（或 *_JSON / *_BASE64）指向語音 GCP 之服務帳戶"
            )
        if not self.project_id:
            return (
                "缺少 Speech API 所屬 GCP 專案 ID：請設定 GOOGLE_SPEECH_PROJECT_ID 或 "
                "GOOGLE_CLOUD_PROJECT_ID（或於語音專用服務帳戶 JSON 內提供 project_id）"
            )
        speech_only_pid = settings.GOOGLE_SPEECH_PROJECT_ID.strip()
        if speech_only_pid and self._speech_account_source == "firebase":
            fb = settings.FIREBASE_PROJECT_ID.strip()
            if fb and speech_only_pid != fb:
                return (
                    "GOOGLE_SPEECH_PROJECT_ID 指向語音 GCP，但目前 OAuth 仍為 Firebase 服務帳戶；"
                    "請補上 GOOGLE_SPEECH_* 憑證（與語音專案一致），或移除 GOOGLE_SPEECH_PROJECT_ID"
                )
        return None

    def _reload_speech_identity(self) -> None:
        """從 .env 載入語音專用憑證（優先 GOOGLE_SPEECH_*，與 Firebase 分離）。"""
        self._speech_account_source = "none"
        info, source = settings.resolve_speech_service_account_info()
        cred_pid = (info or {}).get("project_id") if info else None
        self.project_id = settings.get_google_speech_project_id(
            str(cred_pid) if cred_pid else None,
        )

        if info is not None:
            try:
                self._grpc_credentials = service_account.Credentials.from_service_account_info(
                    info,
                    scopes=["https://www.googleapis.com/auth/cloud-platform"],
                )
                self._speech_account_source = source
                if source == "speech":
                    logger.info("Google STT 使用 GOOGLE_SPEECH_* 服務帳戶（與 Firebase 分離）")
                return
            except Exception as exc:
                logger.warning("Google STT service account 載入失敗: %s", exc)
                self._grpc_credentials = None

        static_token = settings.GOOGLE_STT_ACCESS_TOKEN.strip()
        if static_token:
            logger.warning("Google STT using static access token for gRPC; prefer service account")
            self._grpc_credentials = oauth2_credentials.Credentials(token=static_token)
            self._speech_account_source = "token"
        else:
            self._grpc_credentials = None
            self._speech_account_source = "none"

    async def _safe_callback(self, callback: Optional[Callable], *args) -> None:
        if not callback:
            return
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(*args)
            else:
                callback(*args)
        except Exception as exc:
            logger.error("Google STT callback failed: %s", exc)

    def _schedule_coroutine(self, coro: Coroutine[Any, Any, None]) -> None:
        if self._loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(coro, self._loop)
        except RuntimeError:
            logger.warning("Google STT event loop unavailable, drop async update")

    def _grpc_worker(self) -> None:
        from google.cloud.speech_v2 import SpeechClient
        from google.cloud.speech_v2.types import cloud_speech as cloud_speech_types

        assert self._audio_thread_queue is not None

        client = SpeechClient(credentials=self._grpc_credentials)
        language_codes = self._language_codes(self.current_language)
        recognition_config = cloud_speech_types.RecognitionConfig(
            explicit_decoding_config=cloud_speech_types.ExplicitDecodingConfig(
                encoding=cloud_speech_types.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=int(self.sample_rate),
                audio_channel_count=1,
            ),
            language_codes=language_codes,
            model=_normalize_v2_model(self.model),
        )
        streaming_config = cloud_speech_types.StreamingRecognitionConfig(
            config=recognition_config,
            streaming_features=cloud_speech_types.StreamingRecognitionFeatures(
                interim_results=True,
                enable_voice_activity_events=True,
            ),
        )
        config_request = cloud_speech_types.StreamingRecognizeRequest(
            recognizer=self._recognizer_name(),
            streaming_config=streaming_config,
        )

        def requests_iter():
            yield config_request
            while True:
                chunk = self._audio_thread_queue.get()
                if chunk is None:
                    return
                yield cloud_speech_types.StreamingRecognizeRequest(audio=chunk)

        try:
            for response in client.streaming_recognize(requests=requests_iter()):
                ev = response.speech_event_type
                if ev == cloud_speech_types.StreamingRecognizeResponse.SpeechEventType.SPEECH_ACTIVITY_BEGIN:
                    self._schedule_coroutine(self._safe_callback(self._on_status, "receiving_audio"))
                elif ev == cloud_speech_types.StreamingRecognizeResponse.SpeechEventType.SPEECH_ACTIVITY_END:
                    self._schedule_coroutine(self._safe_callback(self._on_status, "speech_stopped"))

                for result in response.results:
                    if not result.alternatives:
                        continue
                    text = (result.alternatives[0].transcript or "").strip()
                    if not text:
                        continue
                    if result.is_final:
                        self._final_segments.append(text)
                    combined = " ".join(self._final_segments)
                    preview = f"{combined} {text}".strip() if not result.is_final and combined else text
                    out = combined if result.is_final else preview
                    self._schedule_coroutine(self._safe_callback(self._on_transcript_delta, out))
        except Exception as exc:
            logger.error("Google STT streaming_recognize failed: %s", exc)
            self._schedule_coroutine(self._safe_callback(self._on_status, "error"))
        finally:
            done_text = " ".join(self._final_segments).strip()
            self._schedule_coroutine(self._finalize_stream_session(done_text))

    async def _finalize_stream_session(self, text: str) -> None:
        if text and not self._final_transcript_event.is_set():
            self._final_transcript = text
            await self._safe_callback(self._on_transcript_done, text)
        self._final_transcript_event.set()

    async def connect(
        self,
        on_transcript_delta: Optional[Callable[[str], Any]] = None,
        on_transcript_done: Optional[Callable[[str], Any]] = None,
        on_vad_committed: Optional[Callable[[str], Any]] = None,
        model: str = "latest_long",
        language: str = "auto",
        sample_rate: int = 16000,
    ) -> bool:
        self._reload_speech_identity()
        error = self._validate_config()
        if error:
            logger.error("Google STT 初始化失敗: %s", error)
            return False

        self.model = model or "latest_long"
        self.current_language = language or "auto"
        self.sample_rate = int(sample_rate or 16000)
        self._audio_buffer.clear()
        self._pending_send.clear()
        self._final_segments.clear()
        self._final_transcript = None
        self._final_transcript_event.clear()
        self._on_transcript_delta = on_transcript_delta
        self._on_transcript_done = on_transcript_done
        self._on_status = on_vad_committed
        self._loop = asyncio.get_running_loop()
        self._audio_thread_queue = queue.Queue()
        self.is_connected = True

        self._grpc_thread = threading.Thread(target=self._grpc_worker, name="google-stt-v2-stream", daemon=True)
        self._grpc_thread.start()
        await self._safe_callback(self._on_status, "speech_started")
        return True

    def _enqueue_pcm(self, audio_data: bytes) -> None:
        if not audio_data or self._audio_thread_queue is None:
            return
        self._pending_send.extend(audio_data)
        # 達到 flush 閾值（~100ms）就送出，讓 STT 盡快收到音訊，減少初始延遲
        while len(self._pending_send) >= _FLUSH_THRESHOLD_BYTES:
            chunk_size = min(len(self._pending_send), _MAX_STREAMING_BYTES)
            chunk = bytes(self._pending_send[:chunk_size])
            del self._pending_send[:chunk_size]
            self._audio_thread_queue.put(chunk)


    async def send_audio_chunk(self, audio_data: bytes) -> bool:
        if not self.is_connected:
            logger.warning("Google STT 尚未連線，無法接收音訊")
            return False
        if audio_data:
            self._audio_buffer.extend(audio_data)
            self._enqueue_pcm(audio_data)
            await self._safe_callback(self._on_status, "receiving_audio")
        return True

    async def commit_audio(self) -> bool:
        if not self.is_connected:
            logger.warning("Google STT 尚未連線，無法提交音訊")
            return False
        await self._safe_callback(self._on_status, "speech_stopped")
        return True

    def mark_final_transcript(self, transcript: str) -> None:
        if transcript:
            self._final_transcript = transcript
            self._final_transcript_event.set()

    def _close_stream(self) -> None:
        if self._audio_thread_queue is not None:
            if self._pending_send:
                self._audio_thread_queue.put(bytes(self._pending_send))
                self._pending_send.clear()
            self._audio_thread_queue.put(None)

    async def wait_for_final_transcript(self, timeout: float = 3.5) -> Optional[str]:
        if self._final_transcript:
            return self._final_transcript

        await self.commit_audio()
        self._close_stream()
        if self._grpc_thread and self._grpc_thread.is_alive():
            await asyncio.to_thread(self._grpc_thread.join, timeout)

        for _ in range(5):
            if self._final_transcript_event.is_set():
                break
            await asyncio.sleep(0)

        if not self._final_transcript_event.is_set():
            text = " ".join(self._final_segments).strip()
            if text:
                self._final_transcript = text
                await self._safe_callback(self._on_transcript_delta, text)
                await self._safe_callback(self._on_transcript_done, text)
            self._final_transcript_event.set()

        return self._final_transcript

    async def disconnect(self) -> None:
        self.is_connected = False
        self._close_stream()
        if self._grpc_thread and self._grpc_thread.is_alive():
            await asyncio.to_thread(self._grpc_thread.join, 2.0)
        await self._safe_callback(self._on_status, "disconnected")


realtime_stt_service = RealtimeSTTService()


async def create_realtime_session(
    on_transcript_delta: Optional[Callable] = None,
    on_transcript_done: Optional[Callable] = None,
    model: str = "latest_long",
    language: str = "auto",
) -> RealtimeSTTService:
    service = RealtimeSTTService()
    await service.connect(on_transcript_delta, on_transcript_done, None, model=model, language=language)
    return service
