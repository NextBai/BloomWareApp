"""
OpenAI TTS 服務
使用 OpenAI Text-to-Speech API 進行文字轉語音
"""

import os
import logging
from typing import Optional, Dict, Any, Literal
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("services.tts")

# OpenAI 配置
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logger.warning("⚠️ OPENAI_API_KEY 未設置")

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# 支援的 TTS 聲音
VoiceType = Literal["alloy", "echo", "fable", "onyx", "nova", "shimmer"]


class TTSService:
    """OpenAI Text-to-Speech 服務"""

    def __init__(self):
        self.client = client
        if not self.client:
            logger.error("❌ OpenAI client 初始化失敗，請檢查 OPENAI_API_KEY")

    async def synthesize(
        self,
        text: str,
        voice: VoiceType = "nova",
        model: str = "gpt-4o-mini-tts",
        speed: float = 1.0,
        instruction: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        使用 OpenAI TTS API 將文字轉語音（2025 最佳實踐：gpt-4o-mini-tts）

        Args:
            text: 要轉換的文字
            voice: 聲音類型（alloy, echo, fable, onyx, nova, shimmer）
            model: TTS 模型（gpt-4o-mini-tts 或 tts-1-hd）
            speed: 語速（0.25 到 4.0）
            instruction: 語音指令（如「用溫柔、安慰的語氣說話」）

        Returns:
            {
                "success": bool,
                "audio_data": bytes,  # MP3 音頻數據
                "voice": str,
                "error": str  # 錯誤訊息（如果失敗）
            }
        """
        if not self.client:
            return {
                "success": False,
                "audio_data": None,
                "error": "OpenAI client 未初始化"
            }

        try:
            logger.info(f"🔊 開始 TTS 合成，文字長度: {len(text)}, 聲音: {voice}")

            # 調用 OpenAI TTS API（2025 最佳實踐：支援情緒指令）
            params = {
                "model": model,
                "voice": voice,
                "input": text,
                "speed": speed
            }

            # 如果提供情緒指令（gpt-4o-mini-tts 支援）
            if instruction and model == "gpt-4o-mini-tts":
                params["instruction"] = instruction

            response = self.client.audio.speech.create(**params)

            # 獲取音頻數據（MP3 格式）
            audio_data = response.content

            logger.info(f"✅ TTS 合成成功，音頻大小: {len(audio_data)} bytes")

            return {
                "success": True,
                "audio_data": audio_data,
                "voice": voice
            }

        except Exception as e:
            logger.exception(f"❌ TTS 合成失敗: {e}")
            return {
                "success": False,
                "audio_data": None,
                "error": str(e)
            }


# 全域單例
tts_service = TTSService()


async def text_to_speech(
    text: str,
    voice: VoiceType = "nova",
    speed: float = 1.0
) -> Dict[str, Any]:
    """
    便捷函數：將文字轉為語音

    Args:
        text: 要轉換的文字
        voice: 聲音類型（alloy, echo, fable, onyx, nova, shimmer）
        speed: 語速（0.25 到 4.0）

    Returns:
        {
            "success": bool,
            "audio_data": bytes,
            "voice": str,
            "error": str (optional)
        }
    """
    return await tts_service.synthesize(text, voice, speed=speed)
