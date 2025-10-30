import os
import sys
import types
import base64
import tempfile
from pathlib import Path

import numpy as np

from services.voice_login import VoiceAuthService, VoiceLoginConfig


def make_pcm16(duration_s: float, sr: int = 16000) -> bytes:
    t = np.linspace(0, duration_s, int(sr * duration_s), endpoint=False, dtype=np.float32)
    # 單純 220Hz 正弦波 + 微量雜訊避免全零
    x = 0.2 * np.sin(2 * np.pi * 220.0 * t) + 0.01 * np.random.randn(t.size).astype(np.float32)
    x = np.clip(x, -1.0, 1.0)
    y = (x * 32767.0).astype(np.int16)
    return y.tobytes()


def test_voice_login_success_with_cnn_stub(monkeypatch):
    # 準備臨時 CNN 模型目錄（空權重但有檔名，避免 __init__ 報缺檔）
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        (tmpdir / "speaker_id_model.pth").write_bytes(b"stub")
        (tmpdir / "classes.txt").write_text("alice\nbob\n", encoding="utf-8")
        monkeypatch.setenv("VOICE_CNN_MODEL_DIR", str(tmpdir))

        # 在 VoiceAuthService 初始化前，先以假模組覆蓋 inference，避免實際載入大型相依（如 torchaudio）
        dummy = types.SimpleNamespace(
            predict_files=lambda model_dir, inputs, threshold=0.0: [{
                "file": str(inputs[0]),
                "pred": "alice",
                "score": 0.92,
                "top": [("alice", 0.92), ("bob", 0.08)],
                "is_unknown": False,
            }]
        )
        monkeypatch.setitem(sys.modules, 'scripts.inference', dummy)

        svc = VoiceAuthService(config=VoiceLoginConfig(
            window_seconds=1,
            required_windows=1,
            sample_rate=16000,
            prob_threshold=0.80,
            margin_threshold=0.20,
            min_snr_db=0.0,
        ))


        user_id = "u1"
        svc.start_session(user_id, sample_rate=16000)
        pcm = make_pcm16(1.0, 16000)
        b64 = base64.b64encode(pcm).decode("ascii")
        svc.append_chunk_base64(user_id, b64)

        out = svc.stop_and_authenticate(user_id)
        assert out.get("success") is True
        assert out.get("label") == "alice"
        assert out.get("avg_prob", 0.0) >= 0.80


def test_voice_login_no_audio_returns_error(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        (tmpdir / "speaker_id_model.pth").write_bytes(b"stub")
        (tmpdir / "classes.txt").write_text("alice\nbob\n", encoding="utf-8")
        monkeypatch.setenv("VOICE_CNN_MODEL_DIR", str(tmpdir))

        # 同樣先注入假 inference 模組
        dummy = types.SimpleNamespace(
            predict_files=lambda model_dir, inputs, threshold=0.0: []
        )
        monkeypatch.setitem(sys.modules, 'scripts.inference', dummy)

        svc = VoiceAuthService(config=VoiceLoginConfig(
            window_seconds=1,
            required_windows=1,
            sample_rate=16000,
        ))


        out = svc.stop_and_authenticate("u2")
        assert out.get("success") is False
        assert out.get("error") == "NO_AUDIO"
