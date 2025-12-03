"""
音頻情緒辨識服務
使用 HuBERT 中文語音情緒辨識模型進行語音語調分析

支援情緒：angry, fear, happy, neutral, sad, surprise
"""

import io
import logging
import asyncio
import tempfile
import os
from typing import Dict, Any, Optional, Tuple
import numpy as np

from core.logging import get_logger

logger = get_logger("services.audio_emotion")

# 延遲導入（避免啟動時載入模型）
_emotion_module = None


def _load_emotion_module():
    """延遲載入情緒辨識模組"""
    global _emotion_module
    if _emotion_module is None:
        try:
            from models.emotion_recognition import emotion
            _emotion_module = emotion
            logger.info("✅ 音頻情緒辨識模組載入成功")
        except Exception as e:
            logger.error(f"❌ 音頻情緒辨識模組載入失敗: {e}")
            _emotion_module = None
    return _emotion_module


class AudioEmotionService:
    """音頻情緒辨識服務"""

    # 情緒標籤映射（統一格式）
    EMOTION_MAP = {
        "生氣(angry)": "angry",
        "恐懼(fear)": "fear",
        "開心(happy)": "happy",
        "中性(neutral)": "neutral",
        "悲傷(sad)": "sad",
        "驚訝(surprise)": "surprise"
    }

    def __init__(self):
        self._initialized = False

    async def predict_from_bytes(
        self,
        audio_bytes: bytes,
        sample_rate: int = 16000
    ) -> Dict[str, Any]:
        """
        從音頻 bytes 預測情緒

        Args:
            audio_bytes: PCM16 音頻數據
            sample_rate: 採樣率（預設 16000Hz）

        Returns:
            {
                "success": bool,
                "emotion": str,  # 情緒標籤（angry, fear, happy, neutral, sad, surprise）
                "confidence": float,  # 置信度（0-1）
                "all_emotions": dict,  # 所有情緒的置信度
                "source": "audio",  # 情緒來源
                "error": str (optional)
            }
        """
        try:
            # 延遲載入模組
            emotion_module = _load_emotion_module()
            if emotion_module is None:
                return {
                    "success": False,
                    "emotion": "neutral",
                    "confidence": 0.0,
                    "error": "情緒辨識模組未載入"
                }

            # 檢查音頻長度
            if len(audio_bytes) < sample_rate * 2:  # 至少 1 秒
                logger.warning(f"⚠️ 音頻過短: {len(audio_bytes)} bytes")
                return {
                    "success": False,
                    "emotion": "neutral",
                    "confidence": 0.0,
                    "error": "音頻過短"
                }

            logger.info(f"🎤 開始音頻情緒辨識，音頻大小: {len(audio_bytes)} bytes")

            # 使用臨時檔案（emotion.predict() 需要檔案路徑）
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
                temp_path = temp_file.name

                # 寫入 WAV 檔案
                import wave
                with wave.open(temp_path, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)  # 16-bit PCM
                    wf.setframerate(sample_rate)
                    wf.writeframes(audio_bytes)

            try:
                # 在執行緒池中執行（避免阻塞事件循環）
                loop = asyncio.get_event_loop()
                pred_id, confidence, all_emotions = await loop.run_in_executor(
                    None,
                    emotion_module.predict,
                    temp_path
                )

                # 映射情緒標籤
                raw_emotion = emotion_module.id2class(pred_id)
                emotion = self.EMOTION_MAP.get(raw_emotion, "neutral")

                # 轉換所有情緒置信度
                normalized_emotions = {}
                for raw_label, score_str in all_emotions.items():
                    normalized_label = self.EMOTION_MAP.get(raw_label, raw_label)
                    normalized_emotions[normalized_label] = float(score_str)

                logger.info(f"✅ 音頻情緒辨識完成: {emotion} (置信度: {confidence:.4f})")

                return {
                    "success": True,
                    "emotion": emotion,
                    "confidence": float(confidence),
                    "all_emotions": normalized_emotions,
                    "source": "audio"
                }

            finally:
                # 清理臨時檔案
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass

        except Exception as e:
            logger.exception(f"❌ 音頻情緒辨識失敗: {e}")
            return {
                "success": False,
                "emotion": "neutral",
                "confidence": 0.0,
                "error": str(e)
            }


# 全域單例
audio_emotion_service = AudioEmotionService()


async def predict_emotion_from_audio(
    audio_bytes: bytes,
    sample_rate: int = 16000
) -> Dict[str, Any]:
    """
    便捷函數：從音頻預測情緒

    Args:
        audio_bytes: PCM16 音頻數據
        sample_rate: 採樣率

    Returns:
        情緒辨識結果
    """
    return await audio_emotion_service.predict_from_bytes(audio_bytes, sample_rate)
