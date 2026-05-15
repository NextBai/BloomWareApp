import tempfile
from pathlib import Path

import numpy as np

from services.voice_login import VoiceAuthService, VoiceLoginConfig


def _make_pcm_bytes(seconds: float, sample_rate: int, noise_amp: float, tone_amp: float) -> bytes:
    samples = int(seconds * sample_rate)
    t = np.arange(samples, dtype=np.float32) / float(sample_rate)
    tone = tone_amp * np.sin(2.0 * np.pi * 220.0 * t)
    noise = noise_amp * np.random.default_rng(7).normal(0.0, 1.0, samples).astype(np.float32)
    signal = np.clip(tone + noise, -1.0, 1.0)
    return (signal * 32767.0).astype(np.int16).tobytes()


def _build_service(tmp_path: Path) -> VoiceAuthService:
    service = VoiceAuthService.__new__(VoiceAuthService)
    service.base_dir = tmp_path
    service.identity_dir = tmp_path
    service.model_dir = tmp_path
    service.temp_dir = tmp_path
    service.config = VoiceLoginConfig(
        window_seconds=3,
        required_windows=1,
        sample_rate=16000,
        prob_threshold=0.50,
        margin_threshold=0.05,
        min_snr_db=12.0,
    )
    service._buffers = {}
    service._sr_overrides = {}
    service._emo_predict = None
    service._emo_id2class = None
    service._predict_files = None
    return service


def test_low_snr_is_warning_only_not_hard_fail():
    with tempfile.TemporaryDirectory() as tmpdir:
        service = _build_service(Path(tmpdir))

        low_snr_audio = _make_pcm_bytes(
            seconds=3.1,
            sample_rate=service.config.sample_rate,
            noise_amp=0.05,
            tone_amp=0.01,
        )
        service._buffers["u1"] = bytearray(low_snr_audio)

        service._predict_one_wav = lambda wav_path: {
            "label": "speaker_a",
            "score": 0.93,
            "margin": 0.31,
        }
        service._infer_emotion_from_bytes = lambda pcm_bytes, sr: {"label": "neutral"}
        service._preprocess_bytes = lambda pcm_bytes, sr: pcm_bytes

        result = service.stop_and_authenticate("u1")

        assert result["success"] is True
        assert result["label"] == "speaker_a"
        assert "quality_warnings" in result
        assert result["quality_warnings"]
        assert result["quality_warnings"][0]["type"] == "LOW_SNR"
