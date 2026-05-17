"""
Google Cloud Text-to-Speech service.

與 Firebase、Google OAuth 分開：使用「語音 GCP」的 API Key（GOOGLE_TTS_API_KEY 等），
與 STT gRPC 串流所用之服務帳戶 OAuth 不同。

OpenAI TTS support has been removed intentionally. API keys are read from
environment variables only; no key is embedded in source code.
"""

import base64
import logging
import re
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

import aiohttp
from dotenv import load_dotenv
from google.oauth2 import service_account

from core.config import settings

load_dotenv()

logger = logging.getLogger("services.tts")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")

GOOGLE_TTS_ENDPOINT = "https://texttospeech.googleapis.com/v1/text:synthesize"

EMOTION_RATE = {
    "neutral": 1.0,
    "happy": 1.05,
    "sad": 0.92,
    "angry": 0.96,
    "fear": 0.94,
    "surprise": 1.08,
}

VOICE_ALIASES = {
    "coral": ("cmn-TW", "cmn-TW-Wavenet-A"),
    "nova": ("cmn-TW", "cmn-TW-Wavenet-A"),
    "alloy": ("en-US", "en-US-Neural2-F"),
    "echo": ("en-US", "en-US-Neural2-D"),
    "fable": ("en-US", "en-US-Neural2-F"),
    "onyx": ("en-US", "en-US-Neural2-J"),
    "shimmer": ("en-US", "en-US-Neural2-H"),
    "zh-tw": ("cmn-TW", "cmn-TW-Wavenet-A"),
    "zh-cn": ("cmn-CN", "cmn-CN-Wavenet-A"),
    "en-us": ("en-US", "en-US-Neural2-F"),
    "ja-jp": ("ja-JP", "ja-JP-Neural2-B"),
    "ko-kr": ("ko-KR", "ko-KR-Neural2-A"),
    "id-id": ("id-ID", "id-ID-Wavenet-A"),
    "vi-vn": ("vi-VN", "vi-VN-Wavenet-A"),
}

PERSONA_LANGUAGE_ALIASES = {
    "zh": "zh-TW",
    "zh-tw": "zh-TW",
    "zh-hant": "zh-TW",
    "zh-hant-tw": "zh-TW",
    "cmn-hant-tw": "zh-TW",
    "zh-cn": "zh-CN",
    "zh-hans": "zh-CN",
    "zh-hans-cn": "zh-CN",
    "cmn-hans-cn": "zh-CN",
    "en": "en-US",
    "en-us": "en-US",
    "ja": "ja-JP",
    "ja-jp": "ja-JP",
    "ko": "ko-KR",
    "ko-kr": "ko-KR",
    "id": "id-ID",
    "id-id": "id-ID",
    "vi": "vi-VN",
    "vi-vn": "vi-VN",
}

PERSONA_VOICE_MAP = {
    "xiaohua": {
        "default": ("cmn-CN", "cmn-CN-Chirp3-HD-Gacrux"),
        "zh-TW": ("cmn-CN", "cmn-CN-Chirp3-HD-Gacrux"),
        "zh-CN": ("cmn-CN", "cmn-CN-Chirp3-HD-Gacrux"),
        "en-US": ("en-US", "en-US-Chirp-HD-F"),
        "ja-JP": ("ja-JP", "ja-JP-Chirp3-HD-Despina"),
        "ko-KR": ("ko-KR", "ko-KR-Chirp3-HD-Despina"),
        "id-ID": ("id-ID", "id-ID-Chirp3-HD-Despina"),
        "vi-VN": ("vi-VN", "vi-VN-Chirp3-HD-Despina"),
    }
}

PERSONA_PROMPTS = {
    "xiaohua": {
        "default": "You are XiaoHua, a warm youthful companion voice. Read like natural conversation, not a formal bulletin. Use short phrasing, gentle smile, light warmth, and graceful brief pauses. Do not sound flat, robotic, or like you are reading citations, links, or metadata aloud.",
        "zh-TW": "你是小花。請像面對面說話一樣自然、溫柔、帶一點笑意與陪伴感。句子要短一點、順口一點，停頓乾淨，不要像新聞播報，也不要唸出來源、連結、括號資訊或多餘說明。",
        "zh-CN": "你是小花。请像面对面说话一样自然、温柔、带一点笑意与陪伴感。句子要短一点、顺口一点，停顿干净，不要像新闻播报，也不要念出来源、链接、括号信息或多余说明。",
        "en-US": "You are XiaoHua. Speak like a warm companion in direct conversation. Keep phrases compact, clear, and human. Do not sound like a formal announcer, and do not read links, source labels, or metadata aloud.",
        "ja-JP": "あなたは小花です。対面でやさしく話しかけるように、自然であたたかく、少し笑みを含んだ声で話してください。短く言いやすいフレーズを使い、リンクや出典のような情報は読み上げないでください。",
        "ko-KR": "당신은 샤오화입니다. 마주 보고 이야기하듯 자연스럽고 따뜻하게, 은은한 미소가 느껴지는 톤으로 말하세요. 문장은 짧고 부드럽게, 링크나 출처 같은 메타 정보는 읽지 마세요.",
        "id-ID": "Kamu adalah XiaoHua. Bicaralah seperti sedang menemani seseorang secara langsung: hangat, alami, lembut, dan sedikit tersenyum dalam suara. Gunakan frasa singkat yang enak didengar, dan jangan membacakan tautan atau label sumber.",
        "vi-VN": "Bạn là XiaoHua. Hãy nói như đang trò chuyện trực tiếp với người dùng: tự nhiên, ấm áp, dịu dàng và có chút mỉm cười trong giọng nói. Dùng câu ngắn, dễ nghe, và không đọc liên kết hay nhãn nguồn.",
    }
}

LANGUAGE_PRONUNCIATION_SUPPORT = {
    "cmn-CN": {"PHONETIC_ENCODING_PINYIN"},
    "ja-JP": {"PHONETIC_ENCODING_JAPANESE_YOMIGANA"},
    "en-US": {"PHONETIC_ENCODING_IPA", "PHONETIC_ENCODING_X_SAMPA"},
}


def get_emotion_rate(emotion: Optional[str], care_mode: bool = False) -> float:
    if care_mode:
        return 0.92
    return EMOTION_RATE.get(str(emotion or "neutral").lower(), 1.0)


class TTSService:
    """Google Text-to-Speech REST service."""

    def __init__(self):
        self.api_key = settings.GOOGLE_TTS_API_KEY
        self._grpc_credentials = None
        self._reload_tts_identity()

    def _reload_tts_identity(self) -> None:
        info, _source = settings.resolve_speech_service_account_info()
        if info is None:
            self._grpc_credentials = None
            return
        try:
            self._grpc_credentials = service_account.Credentials.from_service_account_info(
                info,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
        except Exception as exc:
            logger.warning("Google TTS service account 載入失敗: %s", exc)
            self._grpc_credentials = None
        
        self._async_client = None  # 延遲初始化 AsyncClient

    def _normalize_language(self, language: Optional[str]) -> Optional[str]:
        raw = str(language or "").strip()
        if not raw:
            return None
        normalized = raw.replace("_", "-").lower()
        return PERSONA_LANGUAGE_ALIASES.get(normalized, raw.replace("_", "-"))

    def _persona_voice_config(self, persona: Optional[str], language: Optional[str]) -> Optional[Dict[str, str]]:
        persona_key = str(persona or "").strip().lower()
        if not persona_key:
            return None

        persona_map = PERSONA_VOICE_MAP.get(persona_key)
        if not persona_map:
            return None

        normalized_language = self._normalize_language(language)
        language_code, voice_name = persona_map.get(
            normalized_language,
            persona_map.get("default", (settings.GOOGLE_TTS_LANGUAGE_CODE, settings.GOOGLE_TTS_DEFAULT_VOICE)),
        )
        return {"languageCode": language_code, "name": voice_name}

    def _persona_prompt(self, persona: Optional[str], language: Optional[str]) -> Optional[str]:
        persona_key = str(persona or "").strip().lower()
        if not persona_key:
            return None

        persona_prompts = PERSONA_PROMPTS.get(persona_key)
        if not persona_prompts:
            return None

        normalized_language = self._normalize_language(language)
        return persona_prompts.get(normalized_language) or persona_prompts.get("default")

    def _build_custom_pronunciations(self, custom_pronunciations: Optional[List[Dict[str, Any]]], texttospeech_module: Any) -> Optional[Any]:
        if not custom_pronunciations:
            return None

        phonetic_enum = texttospeech_module.CustomPronunciationParams.pb().DESCRIPTOR.fields_by_name["phonetic_encoding"].enum_type
        entries = []
        for item in custom_pronunciations:
            phrase = str((item or {}).get("phrase") or "").strip()
            pronunciation = str((item or {}).get("pronunciation") or "").strip()
            encoding_key = str((item or {}).get("phonetic_encoding") or "").strip().upper()
            if not phrase or not pronunciation or not encoding_key:
                continue
            if encoding_key == "PHONETIC_ENCODING_PINYIN" and not _CJK_RE.search(phrase):
                logger.info("略過非中文 phrase 的 PINYIN pronunciation: %s", phrase)
                continue
            encoding_value = phonetic_enum.values_by_name.get(encoding_key)
            if encoding_value is None:
                logger.warning("略過不支援的 phonetic_encoding: %s", encoding_key)
                continue
            entries.append(
                texttospeech_module.CustomPronunciationParams(
                    phrase=phrase,
                    phonetic_encoding=encoding_value.number,
                    pronunciation=pronunciation,
                )
            )

        if not entries:
            return None

        return texttospeech_module.CustomPronunciations(pronunciations=entries)

    def _filter_custom_pronunciations_for_language(
        self,
        custom_pronunciations: Optional[List[Dict[str, Any]]],
        language_code: str,
        source_text: str,
    ) -> Optional[List[Dict[str, Any]]]:
        if not custom_pronunciations:
            return None

        supported_encodings = LANGUAGE_PRONUNCIATION_SUPPORT.get(language_code, set())
        if not supported_encodings:
            return None

        filtered = []
        source = str(source_text or "")
        for item in custom_pronunciations:
            phrase = str((item or {}).get("phrase") or "").strip()
            encoding_key = str((item or {}).get("phonetic_encoding") or "").strip().upper()
            if not phrase:
                continue
            if phrase not in source:
                logger.info(
                    "略過 pronunciation：phrase 不在本次文本中 language=%s phrase=%s",
                    language_code,
                    phrase,
                )
                continue
            if encoding_key in supported_encodings:
                filtered.append(item)
            else:
                logger.info(
                    "略過 pronunciation：language=%s 不支援 encoding=%s",
                    language_code,
                    encoding_key or "<empty>",
                )
        return filtered or None

    def _voice_config(self, voice: str, language: Optional[str] = None, persona: Optional[str] = None) -> Dict[str, str]:
        persona_config = self._persona_voice_config(persona, language)
        if persona_config:
            return persona_config

        key = str(voice or settings.GOOGLE_TTS_DEFAULT_VOICE).strip()
        alias = key.lower()
        language_code, voice_name = VOICE_ALIASES.get(
            alias,
            (settings.GOOGLE_TTS_LANGUAGE_CODE, key),
        )
        return {"languageCode": language_code, "name": voice_name}

    @staticmethod
    def _clean_text_for_tts(text: str) -> str:
        """清理文字中的 Markdown 和 Emoji，避免 TTS 截斷或發音異常"""
        if not text:
            return ""
        # 移除 Markdown 語法 (粗體, 斜體, 連結等)
        text = re.sub(r'(\*\*|__)(.*?)\1', r'\2', text)
        text = re.sub(r'(\*|_)(.*?)\1', r'\2', text)
        text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text)
        text = re.sub(r'#{1,6}\s+', '', text)
        text = re.sub(r'`{1,3}.*?`{1,3}', '', text, flags=re.DOTALL)
        
        # 移除常見 Emoji
        # 使用一個簡單的範圍，或者更複雜的 regex
        text = re.sub(r'[\U00010000-\U0010ffff]', '', text)
        
        # 移除多餘空白
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    async def synthesize(
        self,
        text: str,
        voice: str = "coral",
        model: str = "",
        speed: float = 1.0,
        instruction: Optional[str] = None,
        emotion: Optional[str] = None,
        care_mode: bool = False,
        response_format: str = "mp3",
        language: Optional[str] = None,
        persona: Optional[str] = None,
        speaking_rate: Optional[float] = None,
    ) -> Dict[str, Any]:
        if not self.api_key:
            return {
                "success": False,
                "audio_data": None,
                "error": "GOOGLE_TTS_API_KEY 未設定",
            }

        # 清理文字
        text = self._clean_text_for_tts(text)
        if not text:
            return {"success": False, "audio_data": None, "error": "文字不可為空"}

        # 稍微提高預設語速 (1.1x)
        effective_rate = float(speaking_rate if speaking_rate is not None else speed or 1.1)
        speaking_rate = max(0.25, min(4.0, effective_rate * get_emotion_rate(emotion, care_mode)))
        audio_encoding = "MP3" if response_format != "wav" else "LINEAR16"
        
        voice_cfg = self._voice_config(voice, language=language, persona=persona)
        
        logger.info(
            "🎤 TTS 合成請求: text_len=%d, voice=%s, lang=%s, rate=%.2f, format=%s",
            len(text), voice_cfg["name"], voice_cfg["languageCode"], speaking_rate, audio_encoding
        )

        payload = {
            "input": {"text": text},
            "voice": voice_cfg,
            "audioConfig": {
                "audioEncoding": audio_encoding,
                "speakingRate": speaking_rate,
            },
        }

        async with aiohttp.ClientSession() as session:
            data = await self._post_synthesize(session, payload)
            if not data.get("success"):
                error = data.get("error", "")
                if "does not exist" in error or "misspelled" in error:
                    fallback_payload = dict(payload)
                    fallback_payload["voice"] = {"languageCode": payload["voice"]["languageCode"]}
                    logger.warning("Google TTS voice %s unavailable, retrying with language only", payload["voice"].get("name"))
                    data = await self._post_synthesize(session, fallback_payload)
                    if data.get("success"):
                        payload = fallback_payload
                if not data.get("success"):
                    logger.error("❌ Google TTS 合成失敗: %s", data.get("error"))
                    return {
                        "success": False,
                        "audio_data": None,
                        "error": data.get("error", "Google TTS 合成失敗"),
                    }

        audio_content = data.get("audioContent")
        if not audio_content:
            logger.error("❌ Google TTS 未返回音訊內容")
            return {"success": False, "audio_data": None, "error": "Google TTS 未返回音訊"}

        audio_bytes = base64.b64decode(audio_content)
        logger.info("✅ TTS 合成完成: size=%d bytes", len(audio_bytes))

        return {
            "success": True,
            "audio_data": audio_bytes,
            "voice": payload["voice"]["name"],
            "format": "mp3" if audio_encoding == "MP3" else "wav",
        }

    async def _post_synthesize(self, session: aiohttp.ClientSession, payload: Dict[str, Any]) -> Dict[str, Any]:
        async with session.post(
            GOOGLE_TTS_ENDPOINT,
            params={"key": self.api_key},
            json=payload,
            timeout=30,
        ) as resp:
            data = await resp.json(content_type=None)
            if resp.status >= 400:
                logger.error("Google TTS HTTP failed: status=%s body=%s", resp.status, data)
                return {
                    "success": False,
                    "error": data.get("error", {}).get("message", "Google TTS 合成失敗"),
                }
            data["success"] = True
            return data

    async def synthesize_stream(self, *args, **kwargs) -> AsyncIterator[bytes]:
        result = await self.synthesize(*args, **kwargs)
        if result.get("success") and result.get("audio_data"):
            yield result["audio_data"]

    async def streaming_synthesize(
        self,
        text: str,
        voice: str = "coral",
        speed: float = 1.0,
        language: Optional[str] = None,
        persona: Optional[str] = None,
        speaking_rate: Optional[float] = None,
        markup: Optional[str] = None,
        custom_pronunciations: Optional[List[Dict[str, Any]]] = None,
        emotion: Optional[str] = None,
        care_mode: bool = False,
    ) -> AsyncIterator[bytes]:
        try:
            # 🎯 2026 最佳實踐：延遲初始化 AsyncClient 以重用 gRPC Channel
            if self._async_client is None:
                if not self._grpc_credentials:
                    logger.warning("⚠️ GOOGLE_SPEECH_* 服務帳戶未設定，無法啟用 Chirp3-HD 串流 TTS，將回退到 REST")
                    # 這裡直接拋出一個特定的錯誤，讓外層捕捉並執行回退
                    raise RuntimeError("Missing gRPC credentials")

                from google.cloud import texttospeech_v1beta1 as texttospeech
                try:
                    # 建立持久化 Client，自動處理連線池與 Keepalive
                    self._async_client = texttospeech.TextToSpeechAsyncClient(
                        credentials=self._grpc_credentials,
                        client_options={
                            "api_endpoint": "texttospeech.googleapis.com",
                        }
                    )
                    logger.debug("📡 已建立持久化 Google TTS gRPC 串流連線")
                except Exception as client_err:
                    logger.error(f"❌ 無法建立 TTS AsyncClient: {client_err}")
                    raise

            from google.cloud import texttospeech_v1beta1 as texttospeech

            # 清理文字
            cleaned_text = self._clean_text_for_tts(text)
            cleaned_markup = (markup or "").strip()
            if not cleaned_text and not cleaned_markup:
                return

            voice_cfg = self._voice_config(voice, language=language, persona=persona)
            persona_prompt = self._persona_prompt(persona, language)
            
            # 🎯 2026 最佳實踐：根據情緒與關懷模式動態調整語速
            effective_rate = float(speaking_rate if speaking_rate is not None else speed or 1.1)
            speaking_rate = max(0.25, min(4.0, effective_rate * get_emotion_rate(emotion, care_mode)))
            
            logger.debug(
                "📡 啟動 TTS 串流: voice=%s, lang=%s, rate=%.2f, emotion=%s, care_mode=%s",
                voice_cfg["name"], voice_cfg["languageCode"], speaking_rate, emotion, care_mode
            )

            filtered_pronunciations = self._filter_custom_pronunciations_for_language(
                custom_pronunciations,
                voice_cfg["languageCode"],
                cleaned_markup or cleaned_text,
            )
            custom_pronunciations_obj = self._build_custom_pronunciations(filtered_pronunciations, texttospeech)

            synthesis_input_kwargs: Dict[str, Any] = {}
            if cleaned_markup:
                synthesis_input_kwargs["markup"] = cleaned_markup
            else:
                synthesis_input_kwargs["text"] = cleaned_text
            if persona_prompt:
                synthesis_input_kwargs["prompt"] = persona_prompt

            # 🎯 使用持久化的 AsyncClient
            client = self._async_client
            
            streaming_config = texttospeech.StreamingSynthesizeConfig(
                voice=texttospeech.VoiceSelectionParams(
                    language_code=voice_cfg["languageCode"],
                    name=voice_cfg["name"],
                ),
                streaming_audio_config=texttospeech.StreamingAudioConfig(
                    audio_encoding=texttospeech.AudioEncoding.PCM,
                    sample_rate_hertz=24000,
                    speaking_rate=speaking_rate,
                ),
                custom_pronunciations=custom_pronunciations_obj,
            )

            async def request_iter():
                yield texttospeech.StreamingSynthesizeRequest(streaming_config=streaming_config)
                yield texttospeech.StreamingSynthesizeRequest(
                    input=texttospeech.StreamingSynthesisInput(**synthesis_input_kwargs)
                )

            total_chunks = 0
            total_bytes = 0
            
            # 🎯 緩衝區設計：避免發送過小的 chunk 導致前端處理效能崩潰或斷音
            # 同時確保每次送出的 PCM 數據長度都是偶數 (16-bit = 2 bytes)
            audio_buffer = bytearray()
            MIN_CHUNK_SIZE = 4096  # 約 85ms 的音訊 @ 24kHz
            
            response_iter = await client.streaming_synthesize(requests=request_iter(), timeout=20.0)
            async for response in response_iter:
                chunk = getattr(response, "audio_content", b"")
                if chunk:
                    audio_buffer.extend(chunk)
                    # 當累積超過最低大小時送出，且確保送出長度為偶數
                    while len(audio_buffer) >= MIN_CHUNK_SIZE:
                        # 計算可送出的最大偶數長度
                        send_len = len(audio_buffer) - (len(audio_buffer) % 2)
                        if send_len == 0:
                            break
                        
                        send_chunk = bytes(audio_buffer[:send_len])
                        audio_buffer = audio_buffer[send_len:]
                        
                        total_chunks += 1
                        total_bytes += len(send_chunk)
                        yield send_chunk
            
            # 處理剩餘的尾部資料
            if len(audio_buffer) > 0:
                # 確保長度為偶數
                send_len = len(audio_buffer) - (len(audio_buffer) % 2)
                if send_len > 0:
                    send_chunk = bytes(audio_buffer[:send_len])
                    total_chunks += 1
                    total_bytes += len(send_chunk)
                    yield send_chunk
            
            logger.debug("✅ TTS 串流完成: total_chunks=%d, total_bytes=%d", total_chunks, total_bytes)

        except Exception as e:
            error_msg = str(e) or repr(e)
            logger.warning(f"📡 gRPC 串流 TTS 失敗 (回退中): {error_msg}")
            # 重置 Client 以便下次重建連線
            self._async_client = None
            
            try:
                # 調用 REST 版 synthesize 作為回退方案
                res = await self.synthesize(
                    text=text,
                    voice=voice,
                    speed=speed,
                    language=language,
                    persona=persona,
                    speaking_rate=speaking_rate,
                    emotion=emotion,
                    care_mode=care_mode,
                    # 注意：REST 版不支援 markup，所以傳入純文字
                )
                if res.get("success") and res.get("audio_data"):
                    logger.debug("✅ 已通過 REST API 完成 TTS 回退合成")
                    yield res["audio_data"]
                    return
            except Exception as fallback_err:
                logger.error("❌ TTS 回退方案也失敗: %s", fallback_err)
            
            logger.exception("❌ TTS 串流中斷且回退失敗")
            raise

    async def play_locally(self, text: str, voice: str = "coral", **kwargs) -> Dict[str, Any]:
        return await self.synthesize(text=text, voice=voice, **kwargs)


tts_service = TTSService()


async def text_to_speech(
    text: str,
    voice: str = "coral",
    speed: float = 1.0,
    instruction: Optional[str] = None,
    language: Optional[str] = None,
    persona: Optional[str] = None,
    speaking_rate: Optional[float] = None,
) -> Dict[str, Any]:
    return await tts_service.synthesize(
        text,
        voice,
        speed=speed,
        instruction=instruction,
        language=language,
        persona=persona,
        speaking_rate=speaking_rate,
    )


async def text_to_speech_stream(
    text: str,
    voice: str = "coral",
    speed: float = 1.0,
    instruction: Optional[str] = None,
) -> AsyncIterator[bytes]:
    async for chunk in tts_service.synthesize_stream(text, voice, speed=speed, instruction=instruction):
        yield chunk
