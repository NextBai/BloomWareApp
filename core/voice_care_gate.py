from dataclasses import dataclass
from typing import Any, Dict, Optional


EXTREME_EMOTIONS = {"sad", "angry", "fear"}
VOICE_EMOTION_CONFIDENCE_THRESHOLD = 0.70
VOICE_SPEECH_CONFIDENCE_THRESHOLD = 0.70


@dataclass(frozen=True)
class VoiceCareDecision:
    allow: bool
    emotion: str
    confidence: float
    reason: str
    evidence: Dict[str, Any]


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_emotion(value: Any) -> str:
    text = str(value or "neutral").strip().lower()
    return text if text else "neutral"


def is_voice_context(audio_emotion: Optional[Dict[str, Any]]) -> bool:
    if not audio_emotion:
        return False
    source = str(audio_emotion.get("source") or "").strip().lower()
    return source in {"realtime_voice", "voice", "speech", "audio"}


def decide_voice_care(
    *,
    text_emotion: str,
    audio_emotion: Optional[Dict[str, Any]],
) -> VoiceCareDecision:
    """
    Gate for voice-triggered care mode.

    Voice emotion is allowed to trigger care mode only when the transcript-side
    emotion agrees that the user is in the same extreme-emotion family.
    """
    text_value = _normalize_emotion(text_emotion)
    audio_value = _normalize_emotion((audio_emotion or {}).get("emotion"))
    audio_confidence = _to_float((audio_emotion or {}).get("confidence"))
    speech_confidence_raw = (audio_emotion or {}).get("speech_confidence")
    speech_confidence = (
        _to_float(speech_confidence_raw)
        if speech_confidence_raw is not None
        else None
    )
    evidence = {
        "text_emotion": text_value,
        "audio_emotion": audio_value,
        "audio_emotion_confidence": audio_confidence,
        "speech_confidence": speech_confidence,
    }

    if not audio_emotion or not audio_emotion.get("success"):
        return VoiceCareDecision(False, text_value, 0.5, "voice-audio-missing", evidence)

    if speech_confidence is not None and speech_confidence < VOICE_SPEECH_CONFIDENCE_THRESHOLD:
        return VoiceCareDecision(False, text_value, 0.5, "voice-speech-low-confidence", evidence)

    if audio_confidence < VOICE_EMOTION_CONFIDENCE_THRESHOLD:
        if text_value in EXTREME_EMOTIONS:
            return VoiceCareDecision(True, text_value, 0.5, "voice-text-extreme-audio-low-confidence", evidence)
        return VoiceCareDecision(False, text_value, 0.5, "voice-audio-low-confidence", evidence)

    if audio_value not in EXTREME_EMOTIONS:
        return VoiceCareDecision(False, text_value, audio_confidence, "voice-audio-not-extreme", evidence)

    if text_value not in EXTREME_EMOTIONS:
        return VoiceCareDecision(False, text_value, 0.5, "voice-text-not-extreme", evidence)

    return VoiceCareDecision(True, text_value, audio_confidence, "voice-extreme-family-match", evidence)
