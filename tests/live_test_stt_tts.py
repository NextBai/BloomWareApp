import asyncio
import os
import sys
import logging
import base64

# Add the current directory to sys.path to import local modules
sys.path.append(os.getcwd())

from services.tts_service import TTSService
from services.realtime_stt_service import RealtimeSTTService
from core.config import settings

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("live_test")

async def test_tts():
    logger.info("=== Testing TTS (Google Text-to-Speech) ===")
    service = TTSService()
    
    test_text = "你好，這是一個來自 Bloom Ware 的測試語音。"
    logger.info(f"Synthesizing text: {test_text}")
    
    result = await service.synthesize(test_text, voice="coral", response_format="wav")
    
    if result["success"]:
        logger.info("TTS Success!")
        audio_data = result["audio_data"]
        logger.info(f"Received {len(audio_data)} bytes of audio data.")
        # Save for reference
        with open("tests/test_output.wav", "wb") as f:
            f.write(audio_data)
        logger.info("Saved audio to tests/test_output.wav")
        return audio_data
    else:
        logger.error(f"TTS Failed: {result.get('error')}")
        return None

async def test_stt(audio_data):
    if not audio_data:
        logger.error("No audio data to test STT.")
        return

    logger.info("\n=== Testing STT (Google Speech-to-Text v2) ===")
    service = RealtimeSTTService()
    
    # Strip WAV header (44 bytes) to get raw PCM
    # Note: This assumes the header is 44 bytes and the audio is LINEAR16 16k mono
    raw_pcm = audio_data[44:] if len(audio_data) > 44 else audio_data
    
    transcript_parts = []
    
    def on_delta(text):
        logger.info(f"STT Delta: {text}")
        transcript_parts.append(text)

    def on_done(text):
        logger.info(f"STT Done: {text}")

    logger.info("Connecting to STT service...")
    success = await service.connect(
        on_transcript_delta=on_delta,
        on_transcript_done=on_done,
        language="zh-TW",
        model="short",
        sample_rate=24000
    )
    
    if not success:
        logger.error("STT Connection Failed. Check your service account credentials.")
        return

    logger.info("Sending audio chunks...")
    # Send in small chunks
    chunk_size = 4096
    for i in range(0, len(raw_pcm), chunk_size):
        chunk = raw_pcm[i:i+chunk_size]
        await service.send_audio_chunk(chunk)
        await asyncio.sleep(0.1) # Simulate real-time
    
    logger.info("Finalizing STT...")
    final_text = await service.wait_for_final_transcript(timeout=5.0)
    
    if final_text:
        logger.info(f"STT Result: {final_text}")
    else:
        logger.warning("STT returned no result.")
    
    await service.disconnect()

async def main():
    # Verify environment variables
    if not settings.GOOGLE_TTS_API_KEY:
        logger.error("GOOGLE_TTS_API_KEY is missing!")
    if not settings.GOOGLE_SPEECH_PROJECT_ID:
        logger.error("GOOGLE_SPEECH_PROJECT_ID is missing!")
    
    audio = await test_tts()
    if audio:
        await test_stt(audio)

if __name__ == "__main__":
    asyncio.run(main())
