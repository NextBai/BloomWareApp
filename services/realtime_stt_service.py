"""
OpenAI Realtime API - 即時語音轉文字服務
使用 WebSocket 進行低延遲串流轉錄

支援語言：中文(zh)、英文(en)、印尼文(id)、日文(ja)、越南文(vi)
"""

import os
import json
import asyncio
import logging
from typing import Optional, Callable, Dict, Any, Literal
import websockets
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("services.realtime_stt")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logger.warning("⚠️ OPENAI_API_KEY 未設置")

# OpenAI Realtime API WebSocket URL
REALTIME_API_URL = "wss://api.openai.com/v1/realtime?intent=transcription"

# 支援的語言列表
SupportedLanguage = Literal["zh", "en", "id", "ja", "vi"]
SUPPORTED_LANGUAGES = {
    "zh": "中文",
    "en": "English",
    "id": "Bahasa Indonesia",
    "ja": "日本語",
    "vi": "Tiếng Việt"
}


class RealtimeSTTService:
    """OpenAI Realtime API 即時語音轉文字服務"""

    def __init__(self):
        self.api_key = OPENAI_API_KEY
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.is_connected = False
        self._receive_task: Optional[asyncio.Task] = None
        self.current_language: str = "zh"

    def _build_language_prompt(self) -> str:
        """
        建立語言提示，引導 Whisper 優先識別支援的 5 種語言
        
        Whisper 的 prompt 參數可以包含：
        - 多語言範例文字
        - 引導模型識別特定語言
        
        Returns:
            語言提示字串
        """
        # 使用多語言範例引導 Whisper（每種語言的常見詞彙）
        prompt_samples = [
            "你好",  # 中文
            "Hello",  # 英文
            "Halo",  # 印尼文
            "こんにちは",  # 日文
            "Xin chào"  # 越南文
        ]
        
        return ", ".join(prompt_samples)
    
    def _validate_language(self, language: str) -> Optional[str]:
        """
        驗證並正規化語言代碼

        Args:
            language: 語言代碼（或 'auto' 表示自動檢測）

        Returns:
            正規化後的語言代碼，或 None（自動檢測）
        """
        lang = language.lower().strip()
        
        # 自動檢測模式
        if lang in ('auto', 'detect', ''):
            logger.info("🌐 啟用自動語言檢測")
            return None
        
        if lang in SUPPORTED_LANGUAGES:
            return lang
        
        # 嘗試從完整語言名稱匹配
        for code, name in SUPPORTED_LANGUAGES.items():
            if name.lower() == lang.lower():
                return code
        
        # 不支援的語言，使用自動檢測
        logger.warning(f"⚠️ 不支援的語言 '{language}'，改用自動檢測")
        return None

    async def connect(
        self,
        on_transcript_delta: Optional[Callable[[str], None]] = None,
        on_transcript_done: Optional[Callable[[str], None]] = None,
        on_vad_committed: Optional[Callable[[str], None]] = None,
        model: str = "gpt-4o-mini-transcribe",
        language: str = "zh",
    ) -> bool:
        """
        建立與 OpenAI Realtime API 的 WebSocket 連線

        Args:
            on_transcript_delta: 接收部分轉錄結果的回調函數
            on_transcript_done: 接收完整轉錄結果的回調函數
            on_vad_committed: VAD 偵測到語音結束的回調函數
            model: 使用的模型（gpt-4o-transcribe 或 gpt-4o-mini-transcribe）
            language: 語言代碼（zh/en/id/ja/vi）

        Returns:
            bool: 連線是否成功
        """
        if not self.api_key:
            logger.error("❌ OpenAI API Key 未設置")
            return False

        # 驗證語言
        validated_language = self._validate_language(language)
        self.current_language = validated_language or "auto"
        
        if validated_language:
            language_name = SUPPORTED_LANGUAGES.get(validated_language, validated_language)
            logger.info(f"🌐 語言設定: {language_name} ({validated_language})")
        else:
            logger.info("🌐 語言設定: 自動檢測（支援 zh/en/id/ja/vi）")

        try:
            logger.info(f"🔌 連接到 OpenAI Realtime API: {REALTIME_API_URL}")

            # 建立 WebSocket 連線（使用 API Key 認證）
            self.ws = await websockets.connect(
                REALTIME_API_URL,
                additional_headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "OpenAI-Beta": "realtime=v1"
                }
            )

            self.is_connected = True
            logger.info("✅ 已連接到 OpenAI Realtime API")

            # 建立語言提示（引導 Whisper 優先識別支援的 5 種語言）
            language_prompt = self._build_language_prompt()
            
            # 發送 session 配置（正確格式：需要 session 物件包裹）
            session_config = {
                "type": "transcription_session.update",
                "session": {
                    "input_audio_format": "pcm16",
                    "input_audio_transcription": {
                        "model": model,
                        "prompt": language_prompt  # 使用語言提示引導識別
                        # 不指定 language，讓 Whisper 自動檢測（但透過 prompt 引導）
                    },
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.5,
                        "prefix_padding_ms": 300,
                        "silence_duration_ms": 500
                    },
                    "input_audio_noise_reduction": {
                        "type": "far_field"
                    }
                }
            }
            
            # 如果指定了語言，則加入配置
            if validated_language:
                session_config["session"]["input_audio_transcription"]["language"] = validated_language

            await self.ws.send(json.dumps(session_config))
            logger.info("📤 已發送 session 配置（含語言引導提示）")

            # 啟動接收事件的背景任務
            self._receive_task = asyncio.create_task(
                self._receive_events(
                    on_transcript_delta,
                    on_transcript_done,
                    on_vad_committed
                )
            )

            return True

        except Exception as e:
            logger.error(f"❌ 連接失敗: {e}")
            self.is_connected = False
            return False

    async def _receive_events(
        self,
        on_transcript_delta: Optional[Callable],
        on_transcript_done: Optional[Callable],
        on_vad_committed: Optional[Callable]
    ):
        """
        接收並處理來自 OpenAI Realtime API 的事件

        Args:
            on_transcript_delta: 部分轉錄回調
            on_transcript_done: 完整轉錄回調
            on_vad_committed: VAD 提交回調
        """
        try:
            while self.is_connected and self.ws:
                try:
                    message = await self.ws.recv()
                    event = json.loads(message)
                    event_type = event.get("type")

                    logger.debug(f"📩 收到事件: {event_type}")

                    # 處理使用者語音的部分轉錄結果（即時串流）
                    if event_type == "conversation.item.input_audio_transcription.delta":
                        delta_text = event.get("delta", "")
                        if on_transcript_delta and delta_text:
                            await self._safe_callback(on_transcript_delta, delta_text)

                    # 處理完整轉錄結果（語音段結束）
                    elif event_type == "conversation.item.input_audio_transcription.completed":
                        full_text = event.get("transcript", "")
                        if on_transcript_done and full_text:
                            await self._safe_callback(on_transcript_done, full_text)

                    # 處理 VAD 提交事件（語音段結束）
                    elif event_type == "input_audio_buffer.committed":
                        item_id = event.get("item_id", "")
                        if on_vad_committed:
                            await self._safe_callback(on_vad_committed, item_id)

                    # 處理錯誤事件
                    elif event_type == "error":
                        error_msg = event.get("error", {})
                        logger.error(f"❌ OpenAI API 錯誤: {error_msg}")

                except websockets.exceptions.ConnectionClosed:
                    logger.warning("⚠️ WebSocket 連線已關閉")
                    break
                except json.JSONDecodeError as e:
                    logger.error(f"❌ JSON 解析錯誤: {e}")
                except Exception as e:
                    logger.error(f"❌ 接收事件失敗: {e}")

        except Exception as e:
            logger.error(f"❌ 事件接收循環失敗: {e}")
        finally:
            self.is_connected = False

    async def _safe_callback(self, callback: Callable, *args):
        """安全地執行回調函數（支援同步和異步）"""
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(*args)
            else:
                callback(*args)
        except Exception as e:
            logger.error(f"❌ 回調函數執行失敗: {e}")

    async def send_audio_chunk(self, audio_data: bytes) -> bool:
        """
        發送音頻 chunk 到 OpenAI Realtime API

        Args:
            audio_data: PCM16 格式的音頻數據（需 Base64 編碼）

        Returns:
            bool: 是否發送成功
        """
        if not self.is_connected or not self.ws:
            logger.warning("⚠️ WebSocket 未連接，無法發送音頻")
            return False

        try:
            import base64

            # 將音頻數據編碼為 Base64
            audio_base64 = base64.b64encode(audio_data).decode('utf-8')

            # 發送音頻 chunk
            message = {
                "type": "input_audio_buffer.append",
                "audio": audio_base64
            }

            await self.ws.send(json.dumps(message))
            logger.debug(f"📤 已發送音頻 chunk: {len(audio_data)} bytes")
            return True

        except Exception as e:
            logger.error(f"❌ 發送音頻失敗: {e}")
            return False

    async def commit_audio(self) -> bool:
        """
        手動提交音頻緩衝區（當不使用 Server VAD 時）

        Returns:
            bool: 是否提交成功
        """
        if not self.is_connected or not self.ws:
            logger.warning("⚠️ WebSocket 未連接，無法提交音頻")
            return False

        try:
            message = {
                "type": "input_audio_buffer.commit"
            }

            await self.ws.send(json.dumps(message))
            logger.info("📤 已手動提交音頻緩衝區")
            return True

        except Exception as e:
            logger.error(f"❌提交音頻失敗: {e}")
            return False

    async def disconnect(self):
        """關閉 WebSocket 連線"""
        if self.ws:
            logger.info("🔌 關閉 OpenAI Realtime API 連線")
            self.is_connected = False

            # 取消接收任務
            if self._receive_task and not self._receive_task.done():
                self._receive_task.cancel()
                try:
                    await self._receive_task
                except asyncio.CancelledError:
                    pass

            # 關閉 WebSocket
            await self.ws.close()
            self.ws = None

            logger.info("✅ 已斷開連線")


# 全域單例
realtime_stt_service = RealtimeSTTService()


async def create_realtime_session(
    on_transcript_delta: Optional[Callable] = None,
    on_transcript_done: Optional[Callable] = None,
    model: str = "gpt-4o-mini-transcribe",
    language: str = "zh"
) -> RealtimeSTTService:
    """
    便捷函數：建立 Realtime STT 會話

    Args:
        on_transcript_delta: 部分轉錄回調
        on_transcript_done: 完整轉錄回調
        model: 使用的模型
        language: 語言代碼

    Returns:
        RealtimeSTTService: 已連線的服務實例
    """
    service = RealtimeSTTService()
    await service.connect(
        on_transcript_delta=on_transcript_delta,
        on_transcript_done=on_transcript_done,
        model=model,
        language=language
    )
    return service
