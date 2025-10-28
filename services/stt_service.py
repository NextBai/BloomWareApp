"""
OpenAI Whisper STT 服務
使用 OpenAI Whisper API 進行語音轉文字
"""

import os
import io
import wave
import logging
import tempfile
from typing import Optional, Dict, Any
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("services.stt")

# OpenAI 配置
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logger.warning("⚠️ OPENAI_API_KEY 未設置")

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


class STTService:
    """OpenAI Whisper 語音轉文字服務"""

    def __init__(self):
        self.client = client
        if not self.client:
            logger.error("❌ OpenAI client 初始化失敗，請檢查 OPENAI_API_KEY")

    async def transcribe(
        self,
        audio_data: bytes,
        language: str = "zh",
        prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        使用 Whisper API 將音頻轉文字

        Args:
            audio_data: 音頻數據（PCM16 raw bytes 或完整 WAV 文件）
            language: 語言代碼（zh, en, ja, ko 等）
            prompt: 提示詞（可選，幫助提高準確度）

        Returns:
            {
                "success": bool,
                "text": str,  # 轉錄文字
                "language": str,  # 偵測到的語言
                "error": str  # 錯誤訊息（如果失敗）
            }
        """
        if not self.client:
            return {
                "success": False,
                "text": "",
                "error": "OpenAI client 未初始化"
            }

        try:
            logger.info(f"🎙️ 開始 STT 轉錄，音頻大小: {len(audio_data)} bytes")

            # 檢查是否為原始 PCM 數據（沒有 WAV header）
            # WAV 文件以 "RIFF" 開頭
            is_raw_pcm = not audio_data.startswith(b'RIFF')
            
            if is_raw_pcm:
                # 將 PCM16 數據轉換為 WAV 格式
                logger.info("🔄 轉換 PCM16 → WAV 格式")
                wav_buffer = io.BytesIO()
                with wave.open(wav_buffer, 'wb') as wav_file:
                    wav_file.setnchannels(1)  # 單聲道
                    wav_file.setsampwidth(2)  # 16-bit = 2 bytes
                    wav_file.setframerate(16000)  # 16kHz
                    wav_file.writeframes(audio_data)
                audio_data = wav_buffer.getvalue()

            # 將音頻數據寫入臨時文件（Whisper API 需要文件路徑）
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_audio:
                temp_audio.write(audio_data)
                temp_audio_path = temp_audio.name

            try:
                # 調用 Whisper API
                with open(temp_audio_path, "rb") as audio_file:
                    transcript_params = {
                        "model": "gpt-4o-mini-transcribe",  # 2025 最佳實踐：WER 提升 25%
                        "file": audio_file,
                        "language": language
                    }

                    # 如果提供提示詞，加入參數
                    if prompt:
                        transcript_params["prompt"] = prompt

                    response = self.client.audio.transcriptions.create(**transcript_params)

                # 提取轉錄文字
                transcribed_text = response.text.strip()

                logger.info(f"✅ STT 轉錄成功: {transcribed_text[:50]}...")

                return {
                    "success": True,
                    "text": transcribed_text,
                    "language": language
                }

            finally:
                # 清理臨時文件
                import os as os_module
                if os_module.path.exists(temp_audio_path):
                    os_module.remove(temp_audio_path)

        except Exception as e:
            logger.exception(f"❌ STT 轉錄失敗: {e}")
            return {
                "success": False,
                "text": "",
                "error": str(e)
            }

    async def transcribe_with_retry(
        self,
        audio_data: bytes,
        language: str = "zh",
        max_retries: int = 2
    ) -> Dict[str, Any]:
        """
        帶重試機制的轉錄

        Args:
            audio_data: 音頻數據
            language: 語言代碼
            max_retries: 最大重試次數

        Returns:
            同 transcribe()
        """
        for attempt in range(max_retries + 1):
            result = await self.transcribe(audio_data, language)

            if result["success"]:
                return result

            if attempt < max_retries:
                logger.warning(f"⚠️ STT 重試 {attempt + 1}/{max_retries}")
            else:
                logger.error("❌ STT 達到最大重試次數")

        return result


# 全域單例
stt_service = STTService()


async def transcribe_audio(audio_data: bytes, language: str = "zh") -> Dict[str, Any]:
    """
    便捷函數：轉錄音頻

    Args:
        audio_data: 音頻數據（bytes）
        language: 語言代碼

    Returns:
        {
            "success": bool,
            "text": str,
            "language": str,
            "error": str (optional)
        }
    """
    return await stt_service.transcribe_with_retry(audio_data, language)
