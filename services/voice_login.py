from __future__ import annotations

import base64
import contextlib
import io
import logging
import os
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


def _is_writable_directory(path: Path) -> bool:
    """
    檢查目錄是否可寫；若目錄不存在則嘗試建立。
    在 Hugging Face Spaces（Docker）容器中，/app 通常唯讀，
    因此若配置指向該處需回退到 /tmp。
    """
    try:
        path.mkdir(parents=True, exist_ok=True)
        test_file = path / ".perm_probe"
        with open(test_file, "wb") as probe:
            probe.write(b"ok")
        if test_file.exists():
            test_file.unlink()
        return os.access(path, os.W_OK | os.X_OK)
    except Exception as exc:
        logging.warning("語音暫存目錄不可寫: %s (%s)", path, exc)
        return False


def resolve_voice_temp_dir(preferred: Optional[str] = None) -> Path:
    """
    依序檢查環境變數與預設路徑，返回第一個可寫的暫存目錄。
    參考 Hugging Face 官方建議，優先放在 /tmp（RAM 磁碟）以避免唯讀工作目錄。
    """
    candidates: List[Path] = []
    if preferred:
        candidates.append(Path(preferred).expanduser())

    env_override = os.getenv("VOICE_LOGIN_TMP_DIR")
    if env_override and (not preferred or env_override != preferred):
        candidates.append(Path(env_override).expanduser())

    # 正式機建議使用 /tmp，若使用者更改 XDG_CACHE_HOME 也可沿用
    default_tmp = Path(tempfile.gettempdir()) / "voice_cache"
    candidates.append(default_tmp)

    xdg_cache_home = os.getenv("XDG_CACHE_HOME")
    if xdg_cache_home:
        candidates.append(Path(xdg_cache_home).expanduser() / "voice_cache")

    # 最後保底：直接建立獨立 mkdtemp
    for candidate in candidates:
        if _is_writable_directory(candidate):
            return candidate

    try:
        fallback = Path(tempfile.mkdtemp(prefix="voice_cache_"))
        logging.warning("全部候選目錄不可寫，改用動態暫存: %s", fallback)
        return fallback
    except Exception as exc:
        raise RuntimeError("無法建立語音暫存目錄") from exc


@dataclass
class VoiceLoginConfig:
    window_seconds: int = 5
    required_windows: int = 1
    sample_rate: int = 16000
    bytes_per_sample: int = 2  # 16-bit PCM
    channels: int = 1
    # 決策門檻（硬編）
    prob_threshold: float = 0.80
    margin_threshold: float = 0.20
    min_snr_db: float = 12.0
    # 高信心覆蓋規則（若單窗極高信心，允許覆蓋另一窗的中等分數）
    override_high_prob: float = 0.95
    override_high_margin: float = 0.30
    override_other_max: float = 0.70


class VoiceAuthService:
    """
    管理語音登入流程：收集 PCM 串流、切窗、評估 1:N 認證結果。
    目前採用「標籤法」：CNN 後端的 top1 label 透過 mapping 關聯到 user。
    """

    def __init__(self, base_dir: Optional[Path] = None, config: Optional[VoiceLoginConfig] = None) -> None:
        self.base_dir = base_dir or Path(__file__).resolve().parent.parent
        self.identity_dir = self.base_dir / "models/speaker_identification"
        # 新模型（CNN）預設目錄，可用環境變數覆寫
        override_dir = os.getenv("VOICE_CNN_MODEL_DIR")
        self.model_dir = Path(override_dir).expanduser() if override_dir else (self.identity_dir / "models_cnn")
        self.config = config or VoiceLoginConfig()
        preferred_tmp = os.getenv("VOICE_LOGIN_TMP_DIR")
        self.temp_dir = resolve_voice_temp_dir(preferred_tmp)
        logging.info("語音暫存目錄使用: %s", self.temp_dir)

        # 載入 CNN 後端（完整取代舊 MPS/ECAPA）
        if str(self.identity_dir) not in os.sys.path:
            os.sys.path.insert(0, str(self.identity_dir))
        try:
            from models.speaker_identification.cnn_adapter import predict_files as _predict_files  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError(f"載入 CNN 說話者辨識模組失敗：{e}")
        self._predict_files = _predict_files

        # 資產檢查：需要 speaker_id_model.pth 與 classes 定義（classes.txt 或 processed_audio 目錄）
        # 若預設目錄不存在，向下相容：嘗試使用舊的專題cnn 目錄（搬遷前）
        if not self.model_dir.exists():
            legacy_dir = self.base_dir / "專題cnn"
            if legacy_dir.exists():
                self.model_dir = legacy_dir
            else:
                raise FileNotFoundError(f"找不到 CNN 模型目錄：{self.model_dir}")

        model_file = self.model_dir / "speaker_id_model.pth"
        classes_txt = self.model_dir / "classes.txt"
        processed_dir = self.model_dir / "processed_audio"
        if not model_file.exists():
            raise FileNotFoundError(f"缺少模型檔：{model_file}")
        if not classes_txt.exists() and not processed_dir.exists():
            raise FileNotFoundError(
                f"缺少類別定義，請提供 {classes_txt.name} 或 {processed_dir.name}/ 子資料夾；或設 VOICE_CNN_CLASSES 指定路徑"
            )
        if classes_txt.exists():
            try:
                content = classes_txt.read_text(encoding="utf-8").strip()
            except Exception:
                content = ""
            if not content:
                raise FileNotFoundError(
                    f"{classes_txt} 內容為空，請填入每行一個類別名稱，或提供 {processed_dir.name}/ 以自動推斷"
                )

        # 以 user_id 管理暫存錄音緩衝
        self._buffers: Dict[str, bytearray] = {}
        self._sr_overrides: Dict[str, int] = {}

        # 嘗試載入情緒辨識模組
        try:
            emotion_module_path = self.base_dir / "models" / "emotion_recognition"
            if str(emotion_module_path) not in os.sys.path:
                os.sys.path.insert(0, str(emotion_module_path))
            import emotion as _emo  # type: ignore
            self._emo_predict = getattr(_emo, "predict", None)
            self._emo_id2class = getattr(_emo, "id2class", None)
            if self._emo_predict and self._emo_id2class:
                logging.info("情緒辨識模組載入成功")
            else:
                logging.warning("情緒辨識模組載入不完整，情緒功能將被停用")
        except ImportError as e:
            logging.warning(f"情緒辨識模組匯入失敗: {e}，情緒功能將被停用")
            self._emo_predict = None
            self._emo_id2class = None
        except Exception as e:
            logging.error(f"載入情緒辨識模組時發生未知錯誤: {e}，情緒功能將被停用")
            self._emo_predict = None
            self._emo_id2class = None

    # -------------- Session 管理 --------------
    def start_session(self, user_id: str, sample_rate: Optional[int] = None) -> None:
        self._buffers[user_id] = bytearray()
        if sample_rate is not None:
            self._sr_overrides[user_id] = int(sample_rate)

    def append_chunk_base64(self, user_id: str, b64_pcm16: str) -> None:
        if user_id not in self._buffers:
            self._buffers[user_id] = bytearray()
        data = base64.b64decode(b64_pcm16)
        self._buffers[user_id].extend(data)

    def clear_session(self, user_id: str) -> None:
        self._buffers.pop(user_id, None)
        self._sr_overrides.pop(user_id, None)

    # -------------- 推論主流程 --------------
    def stop_and_authenticate(self, user_id: str) -> Dict[str, Any]:
        buf = self._buffers.get(user_id, None)
        sr = self._sr_overrides.get(user_id, self.config.sample_rate)
        if buf is None or len(buf) == 0:
            return {"success": False, "error": "NO_AUDIO"}

        # 至少兩個視窗
        bytes_per_window = self.config.window_seconds * sr * self.config.bytes_per_sample
        total_need = bytes_per_window * self.config.required_windows
        if len(buf) < total_need:
            return {"success": False, "error": "AUDIO_TOO_SHORT", "need_bytes": total_need, "got_bytes": len(buf)}

        # 只取前 required_windows 個視窗
        windows: List[bytes] = []
        windows_proc: List[bytes] = []
        for i in range(self.config.required_windows):
            start = i * bytes_per_window
            end = start + bytes_per_window
            windows.append(bytes(buf[start:end]))

        # 品質檢查（SNR）
        for w in windows:
            snr_db = self._estimate_snr_db(w)
            if snr_db < self.config.min_snr_db:
                return {"success": False, "error": "LOW_SNR", "snr_db": snr_db}

        # 視窗逐一評估
        win_results: List[Dict[str, Any]] = []
        for w in windows:
            # 降噪與正規化
            w_proc = self._preprocess_bytes(w, sr)
            windows_proc.append(w_proc)
            wav_path = self._bytes_to_wav(w_proc, sr)
            try:
                pred = self._predict_one_wav(wav_path)
            finally:
                try:
                    os.remove(str(wav_path))
                except Exception:
                    pass
            win_results.append(pred)

        # 決策：兩窗同標籤、各自達門檻、平均達門檻、且 margin 過
        labels = [r.get("label") for r in win_results]
        if any(r.get("error") for r in win_results):
            logging.error(f"MODEL_ERROR details: {win_results}")
            return {"success": False, "error": "MODEL_ERROR", "windows": win_results}
        if len(set(labels)) != 1:
            # 嘗試以單窗極高信心覆蓋
            try:
                scores = [float(r.get("score", 0.0)) for r in win_results]
                margins = [float(r.get("margin", 0.0)) for r in win_results]
                best_idx = int(np.argmax(scores)) if scores else 0
                best_score = scores[best_idx] if scores else 0.0
                best_margin = margins[best_idx] if margins else 0.0
                other_ok = all((i == best_idx) or (scores[i] <= self.config.override_other_max) for i in range(len(scores)))
                if (
                    best_score >= self.config.override_high_prob
                    and best_margin >= self.config.override_high_margin
                    and other_ok
                ):
                    label = labels[best_idx]
                    emotion = self._infer_emotion_from_bytes(windows_proc[best_idx], sr)
                    return {
                        "success": True,
                        "label": label,
                        "avg_prob": float(np.mean(scores)) if scores else best_score,
                        "windows": win_results,
                        "emotion": emotion,
                        "note": "override_high_confidence",
                    }
            except Exception:
                pass
            return {"success": False, "error": "INCONSISTENT_WINDOWS", "windows": win_results}
        probs = [float(r.get("score", 0.0)) for r in win_results]
        margins_ok = all(float(r.get("margin", 0.0)) >= self.config.margin_threshold for r in win_results)
        per_win_ok = all(
            (float(r.get("score", 0.0)) >= self.config.prob_threshold) and (float(r.get("margin", 0.0)) >= self.config.margin_threshold)
            for r in win_results
        )
        avg_prob = float(np.mean(probs)) if probs else 0.0
        if not (per_win_ok and margins_ok and avg_prob >= self.config.prob_threshold):
            return {
                "success": False,
                "error": "THRESHOLD_NOT_MET",
                "avg_prob": avg_prob,
                "windows": win_results,
            }

        label = labels[0]
        # 取分數最高視窗做情緒辨識
        try:
            best_idx = int(np.argmax(probs)) if probs else 0
        except Exception:
            best_idx = 0
        emotion = self._infer_emotion_from_bytes(windows_proc[best_idx], sr)
        return {
            "success": True,
            "label": label,
            "avg_prob": avg_prob,
            "windows": win_results,
            "emotion": emotion,
        }

    # -------------- 私有工具 --------------
    def _predict_one_wav(self, wav_path: Path) -> Dict[str, Any]:
        try:
            # 檢查文件是否存在
            if not wav_path.exists():
                logging.error(f"Audio file does not exist: {wav_path}")
                return {"error": "file_not_found"}

            if not wav_path.is_file():
                logging.error(f"Path is not a file: {wav_path}")
                return {"error": "not_a_file"}

            # 檢查文件大小
            file_size = wav_path.stat().st_size
            if file_size == 0:
                logging.error(f"Audio file is empty: {wav_path}")
                return {"error": "empty_file"}

            logging.info(f"Processing audio file: {wav_path} (size: {file_size} bytes)")

            # 調用預測函數
            results = self._predict_files(self.model_dir, [wav_path], threshold=0.0)

            if not results:
                logging.error(f"No results returned from _predict_files for {wav_path}")
                return {"error": "no_results"}

            r = results[0]
            if "error" in r:
                logging.error(f"Prediction error in result for {wav_path}: {r['error']}")
                return {"error": r["error"]}

            if not r:
                logging.error(f"Empty result from _predict_files for {wav_path}")
                return {"error": "empty_result"}

            # 處理結果
            top_pairs = r.get("top", [])
            if not isinstance(top_pairs, list):
                logging.error(f"Invalid top pairs format for {wav_path}: {top_pairs}")
                return {"error": "invalid_top_format"}

            if len(top_pairs) >= 2:
                margin = float(top_pairs[0][1] - top_pairs[1][1])
            elif len(top_pairs) == 1:
                margin = float(top_pairs[0][1])
            else:
                margin = 0.0

            result = {
                "label": r.get("pred"),
                "score": float(r.get("score", 0.0)),
                "top": top_pairs,
                "margin": margin,
            }
            logging.info(f"Successfully processed {wav_path}: {result['label']} (score: {result['score']:.4f})")
            return result

        except FileNotFoundError as e:
            logging.error(f"File not found error for {wav_path}: {e}")
            return {"error": "file_not_found"}
        except PermissionError as e:
            logging.error(f"Permission error for {wav_path}: {e}")
            return {"error": "permission_denied"}
        except OSError as e:
            logging.error(f"OS error for {wav_path}: {e}")
            return {"error": "os_error"}
        except ValueError as e:
            logging.error(f"Value error processing {wav_path}: {e}")
            return {"error": "value_error"}
        except Exception as e:
            logging.error(f"Unexpected exception in _predict_one_wav for {wav_path}: {type(e).__name__}: {e}")
            import traceback
            logging.error(f"Traceback: {traceback.format_exc()}")
            return {"error": f"{type(e).__name__}: {str(e)}"}

    def _bytes_to_wav(self, pcm_bytes: bytes, sr: int) -> Path:
        tmp = io.BytesIO()
        with contextlib.closing(wave.open(tmp, "wb")) as wf:
            wf.setnchannels(self.config.channels)
            wf.setsampwidth(self.config.bytes_per_sample)
            wf.setframerate(sr)
            wf.writeframes(pcm_bytes)
        tmp_path = self.temp_dir / f"tmp_voice_{os.getpid()}_{id(pcm_bytes)}.wav"
        with open(tmp_path, "wb") as f:
            f.write(tmp.getvalue())
        return tmp_path

    def _estimate_snr_db(self, pcm_bytes: bytes) -> float:
        """粗估 SNR：以整段 RMS 與背景估計。簡化：取信號 RMS 與最小能量窗比。"""
        try:
            x = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
            if x.size == 0:
                return 0.0
            x = x / 32768.0
            frame = 1024
            rms_all = np.sqrt(np.mean(x * x) + 1e-12)
            if len(x) < frame:
                return 20.0 * np.log10(max(rms_all, 1e-6) / 1e-6)
            # 取移動窗最小 RMS 視為噪音底
            mins = []
            for i in range(0, len(x) - frame + 1, frame):
                seg = x[i : i + frame]
                mins.append(np.sqrt(np.mean(seg * seg) + 1e-12))
            noise = float(np.percentile(mins, 10)) if mins else (rms_all * 0.5)
            noise = max(noise, 1e-6)
            snr = 20.0 * np.log10(max(rms_all, noise) / noise)
            return float(snr)
        except Exception:
            return 0.0

    def _preprocess_bytes(self, pcm_bytes: bytes, sr: int) -> bytes:
        """簡易降噪 + 正規化（去 DC、軟性降噪、峰值歸一化）。"""
        try:
            x = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
            if x.size == 0:
                return pcm_bytes
            # 轉到 [-1, 1]
            x = x / 32768.0
            # 去 DC
            x = x - float(np.mean(x))
            # 估計噪音門檻（基於 frame RMS 的 10 百分位）
            frame = 1024
            if len(x) < frame:
                noise_rms = max(1e-4, float(np.sqrt(np.mean(x * x) + 1e-12)) * 0.5)
            else:
                rms_list = []
                for i in range(0, len(x) - frame + 1, frame):
                    seg = x[i : i + frame]
                    rms_list.append(np.sqrt(np.mean(seg * seg) + 1e-12))
                noise_rms = max(1e-5, float(np.percentile(rms_list, 10))) if rms_list else 1e-4
            thr = noise_rms * 1.5
            # 軟性降噪（簡單 gate）：低於門檻的樣本衰減
            mask = np.abs(x) < thr
            x[mask] *= 0.4
            # 峰值歸一化到 0.95，限制最大增益避免過放
            peak = float(np.max(np.abs(x)) + 1e-9)
            target = 0.95
            gain = min(5.0, target / peak)
            x = np.clip(x * gain, -1.0, 1.0)
            # 回轉 int16 bytes
            y = (x * 32767.0).astype(np.int16)
            return y.tobytes()
        except Exception:
            return pcm_bytes

    def _infer_emotion_from_bytes(self, pcm_bytes: bytes, sr: int) -> Optional[Dict[str, Any]]:
        try:
            if not self._emo_predict or not self._emo_id2class:
                return None
            wav_path = self._bytes_to_wav(pcm_bytes, sr)
            try:
                pred_id, confidence, distribution = self._emo_predict(str(wav_path))  # type: ignore[misc]
                label = self._emo_id2class(int(pred_id))  # type: ignore[misc]
                return {
                    "label": label,
                    "confidence": float(confidence),
                    "distribution": distribution,
                }
            finally:
                try:
                    os.remove(str(wav_path))
                except Exception:
                    pass
        except Exception:
            return None
