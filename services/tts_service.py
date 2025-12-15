"""
OpenAI TTS 服務（2025 最佳實踐版）
使用 AsyncOpenAI + Streaming 進行低延遲文字轉語音

特色：
- 異步 API（AsyncOpenAI）
- 串流播放（邊生成邊播放，降低 TTFB）
- 支援情緒指令（gpt-4o-mini-tts）
- 多語言支援（自動檢測：中文、英文、印尼文、日文、越南文）
"""

import os
import logging
import asyncio
from typing import Optional, Dict, Any, Literal, AsyncIterator
from openai import AsyncOpenAI
from openai.helpers import LocalAudioPlayer
from dotenv import load_dotenv

# 統一日誌配置
from core.logging import get_logger
logger = get_logger("services.tts")

# 統一配置管理
from core.config import settings

load_dotenv()

# 支援的 TTS 聲音（2025 新增：coral, sage, verse）
VoiceType = Literal["coral", "sage", "verse", "alloy", "echo", "fable", "onyx", "nova", "shimmer"]

# 支援的音頻格式
AudioFormat = Literal["mp3", "opus", "aac", "flac", "wav", "pcm"]

# 情緒指令預設模板
EMOTION_INSTRUCTIONS = {
    "neutral": "用平穩、自然的語氣說話",
    "happy": "用開心、愉悅的語氣說話",
    "sad": "用溫柔、安慰的語氣說話",
    "angry": "用冷靜、理性的語氣說話",
    "fear": "用溫暖、鼓勵的語氣說話",
    "surprise": "用輕快、活潑的語氣說話"
}

# 關懷模式特殊指令
CARE_MODE_INSTRUCTION = "用溫柔、關懷、陪伴的語氣說話，讓對方感受到被理解和支持"


def get_emotion_instruction(emotion: Optional[str], care_mode: bool = False) -> str:
    """
    根據情緒選擇對應的 TTS instruction

    Args:
        emotion: 情緒標籤（neutral, happy, sad, angry, fear, surprise）
        care_mode: 是否為關懷模式

    Returns:
        TTS instruction 字串
    """
    # 關懷模式優先
    if care_mode:
        return CARE_MODE_INSTRUCTION
    
    # 根據情緒選擇
    if emotion and emotion in EMOTION_INSTRUCTIONS:
        return EMOTION_INSTRUCTIONS[emotion]
    
    # 預設中性語氣
    return EMOTION_INSTRUCTIONS["neutral"]


class TTSService:
    """OpenAI Text-to-Speech 服務（異步版）"""

    def __init__(self):
        self._client: Optional[AsyncOpenAI] = None
        self._initialized = False

    @property
    def client(self) -> Optional[AsyncOpenAI]:
        """延遲初始化 AsyncOpenAI 客戶端"""
        if not self._initialized:
            api_key = settings.OPENAI_API_KEY
            if api_key:
                self._client = AsyncOpenAI(
                    api_key=api_key,
                    timeout=float(settings.OPENAI_TIMEOUT),
                    max_retries=3
                )
                logger.info("✅ TTS 服務初始化成功（AsyncOpenAI）")
            else:
                logger.error("❌ TTS 服務初始化失敗：OPENAI_API_KEY 未設置")
            self._initialized = True
        return self._client

    async def synthesize(
        self,
        text: str,
        voice: VoiceType = "coral",
        model: str = "gpt-4o-mini-tts",
        speed: float = 1.0,
        instruction: Optional[str] = None,
        emotion: Optional[str] = None,
        care_mode: bool = False,
        response_format: AudioFormat = "mp3"
    ) -> Dict[str, Any]:
        """
        使用 OpenAI TTS API 將文字轉語音（非串流版）

        Args:
            text: 要轉換的文字
            voice: 聲音類型（coral, sage, verse, alloy, echo, fable, onyx, nova, shimmer）
            model: TTS 模型（gpt-4o-mini-tts 或 tts-1-hd）
            speed: 語速（0.25 到 4.0）
            instruction: 語音指令（手動指定，優先級最高）
            emotion: 情緒標籤（自動選擇 instruction）
            care_mode: 是否為關懷模式（使用特殊語氣）
            response_format: 音頻格式（mp3, opus, aac, flac, wav, pcm）

        Returns:
            {
                "success": bool,
                "audio_data": bytes,
                "voice": str,
                "format": str,
                "error": str (optional)
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
                "speed": speed,
                "response_format": response_format
            }

            # 選擇 instruction（優先級：手動 > 情緒自動選擇）
            final_instruction = instruction or get_emotion_instruction(emotion, care_mode)
            
            # 如果提供情緒指令（gpt-4o-mini-tts 支援）
            if final_instruction and model == "gpt-4o-mini-tts":
                params["instructions"] = final_instruction
                logger.info(f"🎭 TTS 語氣指令: {final_instruction}")

            response = await self.client.audio.speech.create(**params)

            # 獲取音頻數據
            audio_data = response.content

            logger.info(f"✅ TTS 合成成功，音頻大小: {len(audio_data)} bytes")

            return {
                "success": True,
                "audio_data": audio_data,
                "voice": voice,
                "format": response_format
            }

        except Exception as e:
            logger.exception(f"❌ TTS 合成失敗: {e}")
            return {
                "success": False,
                "audio_data": None,
                "error": str(e)
            }

    async def synthesize_stream(
        self,
        text: str,
        voice: VoiceType = "coral",
        model: str = "gpt-4o-mini-tts",
        speed: float = 1.0,
        instruction: Optional[str] = None,
        emotion: Optional[str] = None,
        care_mode: bool = False,
        response_format: AudioFormat = "pcm"
    ) -> AsyncIterator[bytes]:
        """
        使用 OpenAI TTS API 串流生成語音（邊生成邊播放，低延遲）

        Args:
            text: 要轉換的文字
            voice: 聲音類型
            model: TTS 模型
            speed: 語速
            instruction: 語音指令（手動指定，優先級最高）
            emotion: 情緒標籤（自動選擇 instruction）
            care_mode: 是否為關懷模式
            response_format: 音頻格式（建議用 pcm 以獲得最低延遲）

        Yields:
            bytes: 音頻數據塊
        """
        if not self.client:
            logger.error("❌ OpenAI client 未初始化")
            return

        try:
            logger.info(f"🔊 開始 TTS 串流合成，文字長度: {len(text)}, 聲音: {voice}")

            # 調用 OpenAI TTS API（串流模式）
            params = {
                "model": model,
                "voice": voice,
                "input": text,
                "speed": speed,
                "response_format": response_format
            }

            # 選擇 instruction（優先級：手動 > 情緒自動選擇）
            final_instruction = instruction or get_emotion_instruction(emotion, care_mode)
            
            if final_instruction and model == "gpt-4o-mini-tts":
                params["instructions"] = final_instruction
                logger.info(f"🎭 TTS 串流語氣指令: {final_instruction}")

            async with self.client.audio.speech.with_streaming_response.create(**params) as response:
                logger.info("✅ TTS 串流已啟動")
                
                # 逐塊產出音頻數據
                async for chunk in response.iter_bytes(chunk_size=4096):
                    if chunk:
                        yield chunk

                logger.info("✅ TTS 串流完成")

        except Exception as e:
            logger.exception(f"❌ TTS 串流失敗: {e}")

    async def play_locally(
        self,
        text: str,
        voice: VoiceType = "coral",
        model: str = "gpt-4o-mini-tts",
        speed: float = 1.0,
        instruction: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        使用 LocalAudioPlayer 直接播放語音（本地測試用）

        Args:
            text: 要轉換的文字
            voice: 聲音類型
            model: TTS 模型
            speed: 語速
            instruction: 語音指令

        Returns:
            {
                "success": bool,
                "error": str (optional)
            }
        """
        if not self.client:
            return {
                "success": False,
                "error": "OpenAI client 未初始化"
            }

        try:
            logger.info(f"🔊 開始本地播放，文字長度: {len(text)}, 聲音: {voice}")

            params = {
                "model": model,
                "voice": voice,
                "input": text,
                "speed": speed,
                "response_format": "pcm"
            }

            if instruction and model == "gpt-4o-mini-tts":
                params["instructions"] = instruction

            async with self.client.audio.speech.with_streaming_response.create(**params) as response:
                await LocalAudioPlayer().play(response)

            logger.info("✅ 本地播放完成")

            return {
                "success": True
            }

        except Exception as e:
            logger.exception(f"❌ 本地播放失敗: {e}")
            return {
                "success": False,
                "error": str(e)
            }


# 全域單例
tts_service = TTSService()


async def text_to_speech(
    text: str,
    voice: VoiceType = "coral",
    speed: float = 1.0,
    instruction: Optional[str] = None
) -> Dict[str, Any]:
    """
    便捷函數：將文字轉為語音（非串流）

    Args:
        text: 要轉換的文字
        voice: 聲音類型（coral, sage, verse, alloy, echo, fable, onyx, nova, shimmer）
        speed: 語速（0.25 到 4.0）
        instruction: 語音指令（如「用溫柔、安慰的語氣說話」）

    Returns:
        {
            "success": bool,
            "audio_data": bytes,
            "voice": str,
            "format": str,
            "error": str (optional)
        }
    """
    return await tts_service.synthesize(text, voice, speed=speed, instruction=instruction)


async def text_to_speech_stream(
    text: str,
    voice: VoiceType = "coral",
    speed: float = 1.0,
    instruction: Optional[str] = None
) -> AsyncIterator[bytes]:
    """
    便捷函數：將文字轉為語音（串流模式，低延遲）

    Args:
        text: 要轉換的文字
        voice: 聲音類型
        speed: 語速
        instruction: 語音指令

    Yields:
        bytes: 音頻數據塊
    """
    async for chunk in tts_service.synthesize_stream(text, voice, speed=speed, instruction=instruction):
        yield chunk


async def test_tts_playback(
    text: str = "今天是美好的一天！",
    voice: VoiceType = "coral",
    instruction: Optional[str] = "用開心、愉悅的語氣說話"
) -> None:
    """
    快速測試 TTS 播放（使用 LocalAudioPlayer）

    Args:
        text: 要播放的文字
        voice: 聲音類型
        instruction: 語音指令
    """
    result = await tts_service.play_locally(text, voice=voice, instruction=instruction)
    if result["success"]:
        logger.debug(f"✅ 播放成功：{text}")
    else:
        logger.debug(f"❌ 播放失敗：{result.get('error')}")


if __name__ == "__main__":
    # 測試範例：播放中文語音
    asyncio.run(test_tts_playback(
        text="你好！我是 BloomWare 智能助手，很高興為你服務！",
        voice="coral",
        instruction="用溫暖、友善的語氣說話"
    ))
