from __future__ import annotations

import os
import random
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import joblib
import librosa
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch
import torch.nn as nn
from sklearn.model_selection import StratifiedShuffleSplit
from sklearn.preprocessing import LabelEncoder, StandardScaler
import inspect

try:
    from huggingface_hub.utils import EntryNotFoundError, HfHubHTTPError
except Exception:
    EntryNotFoundError = None  # type: ignore[assignment]
    HfHubHTTPError = None  # type: ignore[assignment]

try:
    import httpx
except Exception:
    httpx = None  # type: ignore[assignment]

# 兼容新版 huggingface_hub：0.25.0 起移除 use_auth_token 參數
try:
    import huggingface_hub

    _hf_hub_download_orig = huggingface_hub.hf_hub_download
    _hf_sig = inspect.signature(_hf_hub_download_orig)

    if "use_auth_token" not in _hf_sig.parameters:
        def _hf_hub_download_compat(*args, **kwargs):
            if "use_auth_token" in kwargs:
                token = kwargs.pop("use_auth_token")
                if token is True:
                    token = None
                if token is not None:
                    kwargs.setdefault("token", token)
            return _hf_hub_download_orig(*args, **kwargs)

        huggingface_hub.hf_hub_download = _hf_hub_download_compat  # type: ignore[assignment]
except Exception:
    pass


# 修復第三方套件對舊 API 的相依：將 deprecated 的 torch.cuda.amp.custom_fwd/bwd
# 動態改寫成新版 torch.amp.custom_fwd/bwd，避免噴 FutureWarning，且維持正確語意。
try:  # 在 speechbrain 載入之前先完成 monkey patch
    if hasattr(torch, "amp") and hasattr(torch.amp, "custom_fwd") and hasattr(torch.amp, "custom_bwd"):
        if hasattr(torch, "cuda") and hasattr(torch.cuda, "amp"):
            def _sb_custom_fwd(*args, **kwargs):
                device_type = "cuda" if torch.cuda.is_available() else "cpu"
                return torch.amp.custom_fwd(*args, device_type=device_type, **kwargs)

            def _sb_custom_bwd(*args, **kwargs):
                device_type = "cuda" if torch.cuda.is_available() else "cpu"
                return torch.amp.custom_bwd(*args, device_type=device_type, **kwargs)

            torch.cuda.amp.custom_fwd = _sb_custom_fwd  # type: ignore[attr-defined]
            torch.cuda.amp.custom_bwd = _sb_custom_bwd  # type: ignore[attr-defined]
except Exception:
    # 就算 patch 失敗也不影響主要流程
    pass

# 低資源裝置（0.5 CPU / 512MB）限制 torch 執行緒數，避免 OOM 或排程飽和
try:
    if torch.get_num_threads() > 1:
        torch.set_num_threads(1)
except Exception:
    pass

# 嘗試使用新版匯入路徑，失敗再退回舊版；若都沒有就保持 None
try:  # SpeechBrain >= 1.0
    from speechbrain.inference import EncoderClassifier  # type: ignore
except Exception:  # pragma: no cover
    try:  # SpeechBrain < 1.0（已被官方標示將棄用）
        from speechbrain.pretrained import EncoderClassifier  # type: ignore
    except Exception:  # pragma: no cover
        EncoderClassifier = None  # type: ignore


SUPPORTED_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg"}


_CUSTOM_MODULE_ERRORS: Tuple[type, ...] = tuple(
    err
    for err in (
        EntryNotFoundError if isinstance(EntryNotFoundError, type) else None,
        HfHubHTTPError if isinstance(HfHubHTTPError, type) else None,
        getattr(httpx, "HTTPStatusError", None) if httpx is not None else None,
        FileNotFoundError,
    )
    if isinstance(err, type)
)


class MissingCustomModuleError(RuntimeError):
    """Raised when SpeechBrain pretrained模型缺少可選的 custom.py 檔案時使用。"""


@dataclass
class TrainConfig:
    dataset_dir: Path = Path("voice_data")
    out_dir: Path = Path("models_mps")
    target_sr: int = 16000
    use_speechbrain: bool = True
    aug_per_file: int = 2
    val_ratio: float = 0.2
    seed: int = 42
    device_preferred: str = "auto"  # auto|mps|cpu
    # MLP 訓練
    epochs: int = 40
    batch_size: int = 32
    learning_rate: float = 1e-3
    weight_decay: float = 1e-4
    patience: int = 8  # EarlyStopping


def set_all_seeds(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def resolve_device(preferred: str = "auto") -> torch.device:
    try:
        if preferred in ("mps", "auto"):
            mps_available = bool(getattr(torch.backends.mps, "is_available", lambda: False)())
            mps_built = bool(getattr(torch.backends.mps, "is_built", lambda: True)())
            if mps_available and mps_built:
                return torch.device("mps")
    except Exception:
        pass
    return torch.device("cpu")


def list_audio_files(dataset_dir: Path) -> List[Path]:
    files: List[Path] = []
    for speaker_dir in dataset_dir.iterdir():
        if speaker_dir.is_dir():
            for p in speaker_dir.rglob("*"):
                if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
                    files.append(p)
    files.sort()
    if not files:
        raise FileNotFoundError(f"在 {dataset_dir} 找不到音檔")
    return files


def read_audio_mono(path: Path, target_sr: int) -> np.ndarray:
    y, _ = librosa.load(str(path), sr=target_sr, mono=True)
    if not np.any(np.isfinite(y)):
        raise ValueError(f"讀取音訊失敗或全為 NaN: {path}")
    return y.astype(np.float32, copy=False)


def compute_rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x)) + 1e-12))


def augment_waveform(y: np.ndarray, sr: int) -> np.ndarray:
    def gain(x: np.ndarray) -> np.ndarray:
        g = np.random.uniform(0.85, 1.15)
        return np.clip(x * g, -1.0, 1.0)

    def noise(x: np.ndarray) -> np.ndarray:
        snr_db = np.random.uniform(18, 28)
        target_snr = 10 ** (snr_db / 20.0)
        n_rms = compute_rms(x) / (target_snr + 1e-12)
        n = np.random.normal(0.0, n_rms, size=x.shape).astype(np.float32)
        out = x + n
        return np.clip(out, -1.0, 1.0)

    def shift(x: np.ndarray) -> np.ndarray:
        max_shift = int(0.08 * len(x))
        k = np.random.randint(-max_shift, max_shift + 1)
        return np.roll(x, k)

    def pitch(x: np.ndarray) -> np.ndarray:
        steps = np.random.uniform(-1.5, 1.5)
        try:
            z = librosa.effects.pitch_shift(x, sr=sr, n_steps=steps)
            if len(z) != len(x):
                z = z[: len(x)] if len(z) > len(x) else np.pad(z, (0, len(x) - len(z)))
            return np.clip(z, -1.0, 1.0)
        except Exception:
            return x

    candidates = [gain, noise, shift, pitch]
    num_ops = np.random.randint(2, 4)
    ops = np.random.choice(candidates, size=num_ops, replace=False)
    z = y.copy()
    for op in ops:
        z = op(z)
    return z


def logmel_stats(y: np.ndarray, sr: int) -> np.ndarray:
    mels = librosa.feature.melspectrogram(
        y=y, sr=sr, n_fft=1024, hop_length=256, n_mels=64, fmin=20, fmax=sr // 2
    ).astype(np.float32)
    logmels = librosa.power_to_db(np.maximum(mels, 1e-10))
    mean = np.mean(logmels, axis=1)
    std = np.std(logmels, axis=1)
    X = logmels - mean[:, None]
    m3 = np.mean(np.power(X, 3), axis=1) / (np.power(std + 1e-8, 3))
    m4 = np.mean(np.power(X, 4), axis=1) / (np.power(std + 1e-8, 4))
    feat = np.concatenate([mean, std, m3, m4], axis=0)
    return feat.astype(np.float32, copy=False)


_EMBEDDER_CACHE: Dict[str, "SpeechEmbedder"] = {}


class SpeechEmbedder:
    """
    ECAPA-TDNN 語音嵌入提取器（基於 SpeechBrain）
    
    Hugging Face Space 部署建議：
    - 設定環境變數 HF_HOME=/tmp/huggingface
    - 設定環境變數 SPEECHBRAIN_CACHE_DIR=/tmp/speechbrain
    - 確保 requirements.txt 包含 speechbrain>=1.0.0
    """
    def __init__(self, device: torch.device, max_retries: int = 2) -> None:
        if EncoderClassifier is None:
            raise RuntimeError("需要 speechbrain 才能載入 ECAPA 嵌入，請安裝 speechbrain 與 torch。")
        
        run_device = "mps" if device.type == "mps" else "cpu"
        self.classifier = None
        self.is_available = False
        self.device = device
        self.load_error = None
        
        # 嘗試載入（含重試機制）
        for attempt in range(max_retries):
            try:
                self.classifier = self._load_classifier(run_device)
                if self.classifier is not None:
                    self.is_available = True
                    self.device = device
                    print(f"✓ ECAPA embedder 載入成功 (device={run_device}, attempt={attempt + 1})")
                    return
                else:
                    self.load_error = "EncoderClassifier.from_hparams 返回 None（可能缺少模型檔案）"
            except Exception as e:
                self.load_error = str(e)
                if attempt < max_retries - 1:
                    warnings.warn(f"ECAPA 載入失敗 (attempt {attempt + 1}/{max_retries}): {e}，重試中...")
                    continue
                else:
                    warnings.warn(f"ECAPA 在 {run_device} 載入失敗，嘗試改用 CPU。原因: {e}")
        
        # 如果主要設備失敗，且不是 CPU，嘗試 CPU
        if run_device != "cpu":
            try:
                self.classifier = self._load_classifier("cpu")
                if self.classifier is not None:
                    self.is_available = True
                    self.device = torch.device("cpu")
                    print("✓ ECAPA embedder 載入成功 (降級至 CPU)")
                    return
            except Exception as e:
                warnings.warn(f"ECAPA 在 CPU 也載入失敗: {e}")
                self.load_error = f"所有設備載入失敗: {e}"
        
        # 完全失敗
        self.classifier = None
        self.is_available = False
        warnings.warn(
            f"⚠️  ECAPA embedder 不可用。錯誤: {self.load_error}\n"
            f"建議檢查：\n"
            f"  1. speechbrain 版本 >= 1.0.0\n"
            f"  2. 網路連線是否正常\n"
            f"  3. 環境變數 SPEECHBRAIN_CACHE_DIR 是否設定\n"
            f"  4. Hugging Face Space 請設定 HF_HOME=/tmp/huggingface"
        )

    def _load_classifier(self, run_device: str):
        """
        載入 SpeechBrain ECAPA-TDNN 分類器
        
        2025 最佳實踐：
        - 使用明確的 savedir（Hugging Face Space 需要）
        - 設定適當的 run_opts
        - 處理 custom.py 缺失問題
        """
        # 優先使用環境變數，否則使用 /tmp（Hugging Face Space 友善）
        savedir = os.environ.get("SPEECHBRAIN_CACHE_DIR")
        if savedir is None:
            import tempfile
            savedir = os.path.join(tempfile.gettempdir(), "speechbrain_cache")
        
        try:
            model_source = os.environ.get("SPEECHBRAIN_VOXCELEB_CACHE", "speechbrain/spkrec-ecapa-voxceleb")
            
            classifier = EncoderClassifier.from_hparams(
                source=model_source,
                savedir=savedir,
                run_opts={
                    "device": run_device,
                    "inference_batch_size": 1,
                },
            )
            return classifier
            
        except _CUSTOM_MODULE_ERRORS as e:
            # custom.py 缺失或 HTTP 錯誤
            warnings.warn(f"載入模型時遇到預期錯誤（custom.py 或網路問題）: {type(e).__name__}: {e}")
            return None
        except Exception as e:
            # 其他未預期錯誤
            warnings.warn(f"載入 ECAPA 模型時發生錯誤: {type(e).__name__}: {e}")
            raise

    def embed(self, y: np.ndarray, sr: int) -> np.ndarray:
        if not self.is_available:
            error_msg = (
                "ECAPA embedder 不可用，無法提取語音特徵。\n"
                f"載入錯誤: {self.load_error}\n"
                "建議：\n"
                "  1. 檢查 speechbrain 是否正確安裝: pip install speechbrain>=1.0.0\n"
                "  2. 確認網路連線可訪問 huggingface.co\n"
                "  3. 在 Hugging Face Space 設定環境變數 HF_HOME\n"
                "  4. 或設定環境變數 DISABLE_SPEECHBRAIN=true 改用 log-mel 特徵重新訓練模型"
            )
            raise RuntimeError(error_msg)
        
        if sr != 16000:
            y = librosa.resample(y, orig_sr=sr, target_sr=16000)
            sr = 16000
        # mps 的 torch tensor 必須是 float32，避免無法轉 device
        sig = torch.from_numpy(y).float().unsqueeze(0)  # [1, T]
        with torch.no_grad():
            emb = self.classifier.encode_batch(sig)  # [1, D, 1]
        emb = emb.squeeze().detach().cpu().numpy()
        if emb.ndim == 2:
            emb = emb[:, 0]
        return emb.astype(np.float32, copy=False)


class FeatureExtractor:
    def __init__(self, cfg: TrainConfig, device: torch.device):
        self.cfg = cfg
        self.device = device
        disable_sb = os.environ.get("DISABLE_SPEECHBRAIN", "false").lower() in {"1", "true", "yes"}
        self._use_speechbrain = bool(cfg.use_speechbrain and EncoderClassifier is not None and not disable_sb)
        self._embedder: Optional[SpeechEmbedder] = None
        
        if disable_sb:
            warnings.warn("⚠️  SpeechBrain 嵌入已透過環境變數停用，改用 log-mel 特徵。")
            self._use_speechbrain = False

        if self._use_speechbrain:
            try:
                self._embedder = SpeechEmbedder(device=device)
                if not self._embedder.is_available:
                    warnings.warn(
                        "⚠️  ECAPA embedder 初始化失敗，自動降級到 log-mel 特徵。\n"
                        "這可能影響模型準確度。若要使用 ECAPA，請確保：\n"
                        "  - speechbrain >= 1.0.0 已安裝\n"
                        "  - 網路可訪問 huggingface.co\n"
                        "  - 環境變數正確設定（HF_HOME, SPEECHBRAIN_CACHE_DIR）"
                    )
                    self._use_speechbrain = False
                    self._embedder = None
            except Exception as e:
                warnings.warn(f"⚠️  speechbrain 初始化失敗，降級到 log-mel。原因: {e}")
                self._use_speechbrain = False
                self._embedder = None

    @property
    def feature_kind(self) -> str:
        """返回當前使用的特徵類型"""
        if self._use_speechbrain and self._embedder is not None and self._embedder.is_available:
            return "ecapa_embedding"
        return "logmel_stats"

    def extract_one(self, y: np.ndarray, sr: int) -> np.ndarray:
        """提取單一音訊片段的特徵"""
        if self._use_speechbrain and self._embedder is not None and self._embedder.is_available:
            return self._embedder.embed(y, sr)
        return logmel_stats(y, sr)

    def extract_with_aug(self, path: Path, num_aug: int) -> List[np.ndarray]:
        y = read_audio_mono(path, self.cfg.target_sr)
        feats = [self.extract_one(y, self.cfg.target_sr)]
        for _ in range(num_aug):
            ya = augment_waveform(y, self.cfg.target_sr)
            feats.append(self.extract_one(ya, self.cfg.target_sr))
        return feats


def get_label_from_path(p: Path) -> str:
    return p.parent.name


def stratified_holdout_split(
    files: Sequence[Path], labels: Sequence[str], val_ratio: float, seed: int
) -> Tuple[List[int], List[int]]:
    le = LabelEncoder()
    y = le.fit_transform(labels)
    sss = StratifiedShuffleSplit(n_splits=1, test_size=val_ratio, random_state=seed)
    train_idx, val_idx = next(sss.split(np.zeros(len(files)), y))
    return list(train_idx), list(val_idx)


class MLPClassifier(nn.Module):
    def __init__(self, input_dim: int, num_classes: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, 256),
            nn.ReLU(),
            nn.Dropout(p=0.2),
            nn.Linear(256, 128),
            nn.ReLU(),
            nn.Dropout(p=0.2),
            nn.Linear(128, num_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


def compute_class_weights(y_indices: np.ndarray, num_classes: int) -> torch.Tensor:
    # 反比於頻率的簡單平衡權重
    counts = np.bincount(y_indices, minlength=num_classes).astype(np.float32)
    counts[counts == 0] = 1.0
    inv = 1.0 / counts
    weights = inv * (num_classes / np.sum(inv))
    return torch.tensor(weights, dtype=torch.float32)


def accuracy_from_logits(logits: torch.Tensor, targets: torch.Tensor) -> float:
    preds = torch.argmax(logits, dim=1)
    return float((preds == targets).float().mean().item())


def train(cfg: TrainConfig) -> Dict[str, object]:
    set_all_seeds(cfg.seed)
    device = resolve_device(cfg.device_preferred)

    files = list_audio_files(cfg.dataset_dir)
    labels_str = [get_label_from_path(p) for p in files]
    label_encoder = LabelEncoder()
    labels_all = label_encoder.fit_transform(labels_str)

    train_ids, val_ids = stratified_holdout_split(files, labels_str, cfg.val_ratio, cfg.seed)

    extractor = FeatureExtractor(cfg, device)
    feature_kind = extractor.feature_kind

    # 擷取特徵（訓練含增強，驗證不增強）
    X_train: List[np.ndarray] = []
    y_train: List[int] = []
    X_val: List[np.ndarray] = []
    y_val: List[int] = []

    for i in train_ids:
        feats = extractor.extract_with_aug(files[i], cfg.aug_per_file)
        X_train.extend(feats)
        y_train.extend([labels_all[i]] * len(feats))

    for i in val_ids:
        feat = extractor.extract_with_aug(files[i], num_aug=0)[0]
        X_val.append(feat)
        y_val.append(labels_all[i])

    X_train_np = np.stack(X_train, axis=0)
    X_val_np = np.stack(X_val, axis=0)
    y_train_np = np.array(y_train, dtype=np.int64)
    y_val_np = np.array(y_val, dtype=np.int64)

    # 標準化
    scaler = StandardScaler()
    X_train_np = scaler.fit_transform(X_train_np)
    X_val_np = scaler.transform(X_val_np)

    input_dim = int(X_train_np.shape[1])
    num_classes = int(len(label_encoder.classes_))

    model = MLPClassifier(input_dim=input_dim, num_classes=num_classes).to(device)
    class_weights = compute_class_weights(y_train_np, num_classes=num_classes).to(device)
    criterion = nn.CrossEntropyLoss(weight=class_weights)
    optimizer = torch.optim.Adam(model.parameters(), lr=cfg.learning_rate, weight_decay=cfg.weight_decay)

    # 資料轉 tensor，因資料量小直接一次性張量訓練（也可改 DataLoader）
    X_train_t = torch.tensor(X_train_np, dtype=torch.float32, device=device)
    y_train_t = torch.tensor(y_train_np, dtype=torch.long, device=device)
    X_val_t = torch.tensor(X_val_np, dtype=torch.float32, device=device)
    y_val_t = torch.tensor(y_val_np, dtype=torch.long, device=device)

    history = {
        "train_loss": [],
        "val_loss": [],
        "train_acc": [],
        "val_acc": [],
    }

    best_val = float("inf")
    best_state: Optional[Dict[str, torch.Tensor]] = None
    no_improve = 0

    for epoch in range(1, cfg.epochs + 1):
        model.train()
        optimizer.zero_grad(set_to_none=True)
        logits = model(X_train_t)
        loss = criterion(logits, y_train_t)
        loss.backward()
        optimizer.step()

        with torch.no_grad():
            model.eval()
            val_logits = model(X_val_t)
            val_loss = criterion(val_logits, y_val_t)

            tr_acc = accuracy_from_logits(logits, y_train_t)
            va_acc = accuracy_from_logits(val_logits, y_val_t)

        history["train_loss"].append(float(loss.item()))
        history["val_loss"].append(float(val_loss.item()))
        history["train_acc"].append(tr_acc)
        history["val_acc"].append(va_acc)

        print(
            f"Epoch {epoch:02d}/{cfg.epochs}  "
            f"loss={loss.item():.4f} acc={tr_acc:.4f}  "
            f"val_loss={val_loss.item():.4f} val_acc={va_acc:.4f}"
        )

        if float(val_loss.item()) < best_val - 1e-6:
            best_val = float(val_loss.item())
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            no_improve = 0
        else:
            no_improve += 1
            if no_improve >= cfg.patience:
                print(f"早停：連續 {cfg.patience} 個 epoch 驗證沒有改善。")
                break

    if best_state is not None:
        model.load_state_dict(best_state)

    # 輸出目錄與資產
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    model_path = cfg.out_dir / "speaker_id_mlp.pt"
    assets_path = cfg.out_dir / "speaker_id_assets.joblib"
    torch.save(model.state_dict(), model_path)

    joblib.dump(
        {
            "label_encoder": label_encoder,
            "scaler": scaler,
            "feature_kind": feature_kind,
            "target_sr": cfg.target_sr,
            "input_dim": input_dim,
            "num_classes": num_classes,
            "history": history,
            "version": 1,
        },
        assets_path,
    )

    # 繪圖
    fig_path = cfg.out_dir / "training_curves.png"
    plot_training_curves(history, fig_path)

    return {
        "model_path": model_path,
        "assets_path": assets_path,
        "history": history,
        "feature_kind": feature_kind,
        "device": str(device),
        "figure": fig_path,
    }


def plot_training_curves(history: Dict[str, List[float]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))

    axes[0].plot(history["train_loss"], label="train_loss")
    axes[0].plot(history["val_loss"], label="val_loss")
    axes[0].set_title("Loss")
    axes[0].set_xlabel("Epoch")
    axes[0].set_ylabel("Loss")
    axes[0].legend()

    axes[1].plot(history["train_acc"], label="train_acc")
    axes[1].plot(history["val_acc"], label="val_acc")
    axes[1].set_title("Accuracy")
    axes[1].set_xlabel("Epoch")
    axes[1].set_ylabel("Accuracy")
    axes[1].legend()

    plt.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def _ensure_embedder_for_infer(feature_kind: str, device: torch.device) -> Optional[SpeechEmbedder]:
    """
    確保推論時 ECAPA embedder 可用
    
    Returns:
        SpeechEmbedder 實例（可用時）或 None（不可用時）
    
    Raises:
        RuntimeError: 當模型需要 ECAPA 但無法載入時
    """
    if feature_kind == "ecapa_embedding":
        if EncoderClassifier is None:
            raise RuntimeError(
                "此模型使用 ECAPA 特徵訓練，但 speechbrain 未安裝。\n"
                "請執行: pip install speechbrain>=1.0.0 torch torchaudio"
            )
        
        key = f"{feature_kind}:{device.type}"
        if key not in _EMBEDDER_CACHE:
            embedder = SpeechEmbedder(device=device)
            if not embedder.is_available:
                raise RuntimeError(
                    f"此模型使用 ECAPA 特徵訓練，但 embedder 載入失敗。\n"
                    f"錯誤: {embedder.load_error}\n\n"
                    "解決方案：\n"
                    "  1. 確認網路連線可訪問 huggingface.co\n"
                    "  2. 在 Hugging Face Space 設定環境變數:\n"
                    "     HF_HOME=/tmp/huggingface\n"
                    "     SPEECHBRAIN_CACHE_DIR=/tmp/speechbrain\n"
                    "  3. 或重新用 log-mel 特徵訓練模型:\n"
                    "     export DISABLE_SPEECHBRAIN=true\n"
                    "     python speaker_id_mps.py"
                )
            _EMBEDDER_CACHE[key] = embedder
        return _EMBEDDER_CACHE[key]
    return None


def predict_files(
    model_dir: Path,
    inputs: Sequence[Path],
    threshold: float = 0.0,
) -> List[Dict[str, object]]:
    """
    使用訓練好的模型對音訊檔案進行說話人識別
    
    Args:
        model_dir: 模型目錄（包含 speaker_id_mlp.pt 和 speaker_id_assets.joblib）
        inputs: 要預測的音訊檔案列表
        threshold: 信心度閾值（低於此值判定為 unknown）
    
    Returns:
        預測結果列表，每個元素包含 file, pred, score, top, is_unknown 等欄位
    
    Raises:
        FileNotFoundError: 模型檔案不存在
        RuntimeError: ECAPA 模型需要但無法載入
    """
    model_path = model_dir / "speaker_id_mlp.pt"
    assets_path = model_dir / "speaker_id_assets.joblib"
    if not model_path.exists() or not assets_path.exists():
        raise FileNotFoundError(f"找不到模型或資產檔，請先訓練。\n模型路徑: {model_path}\n資產路徑: {assets_path}")

    assets = joblib.load(assets_path)
    label_encoder: LabelEncoder = assets["label_encoder"]
    scaler: StandardScaler = assets["scaler"]
    feature_kind: str = assets["feature_kind"]
    target_sr: int = int(assets["target_sr"])
    input_dim: int = int(assets["input_dim"])
    num_classes: int = int(assets["num_classes"])

    print(f"📦 載入模型: feature_kind={feature_kind}, input_dim={input_dim}, classes={num_classes}")

    device = resolve_device("mps")
    model = MLPClassifier(input_dim=input_dim, num_classes=len(label_encoder.classes_))
    model.load_state_dict(torch.load(model_path, map_location=device))
    model.to(device)
    model.eval()

    # 確保 ECAPA embedder 可用（如果模型需要）
    embedder = _ensure_embedder_for_infer(feature_kind, device)
    
    if feature_kind == "ecapa_embedding" and (embedder is None or not embedder.is_available):
        # 這個錯誤不應該發生，因為 _ensure_embedder_for_infer 會拋異常
        raise RuntimeError("內部錯誤: ECAPA embedder 應該已被驗證可用")

    results: List[Dict[str, object]] = []
    for p in inputs:
        if not p.exists():
            results.append({"file": str(p), "error": "檔案不存在"})
            continue
        try:
            y = read_audio_mono(p, target_sr=target_sr)
            
            # 根據特徵類型提取特徵
            if feature_kind == "ecapa_embedding":
                if embedder is None:
                    raise RuntimeError("ECAPA embedder 未初始化")
                feat = embedder.embed(y, target_sr)
                feat = scaler.transform(feat.reshape(1, -1))
                feat_t = torch.tensor(feat, dtype=torch.float32, device=device)
            else:
                # log-mel 特徵
                feat = logmel_stats(y, target_sr)
                feat = scaler.transform(feat.reshape(1, -1))
                feat_t = torch.tensor(feat, dtype=torch.float32, device=device)
            
            with torch.no_grad():
                logits = model(feat_t)
                probs = torch.softmax(logits, dim=1).cpu().numpy()[0]
            
            pairs = list(zip(label_encoder.classes_.tolist(), probs.tolist()))
            pairs.sort(key=lambda x: x[1], reverse=True)
            pred_label, pred_score = pairs[0]
            pred_out = "unknown" if float(pred_score) < threshold else pred_label
            
            results.append(
                {
                    "file": str(p),
                    "pred": pred_out,
                    "score": float(pred_score),
                    "top": pairs[:3],
                    "is_unknown": bool(float(pred_score) < threshold),
                }
            )
        except Exception as e:
            results.append({"file": str(p), "error": str(e)})

    return results


if __name__ == "__main__":
    # 無需指令參數：直接訓練 + 輸出曲線 + 小量推論測試
    base_dir = Path(__file__).resolve().parent
    cfg = TrainConfig(
        dataset_dir=base_dir / "voice_data",
        out_dir=base_dir / "models_mps",
        device_preferred="mps",
        epochs=40,
        aug_per_file=2,
        val_ratio=0.2,
        patience=8,
    )
    print("開始訓練（MPS 若不可用會自動回 CPU）…")
    result = train(cfg)
    print(f"裝置: {result['device']}")
    print(f"訓練曲線: {result['figure']}")

    # 推論小測（取前三個檔案）
    try:
        some_files = list_audio_files(cfg.dataset_dir)[:3]
        if some_files:
            print("開始推論測試…")
            preds = predict_files(cfg.out_dir, some_files, threshold=0.5)
            for r in preds:
                name = Path(r.get("file", "")).name
                pred = r.get("pred")
                score = r.get("score", 0.0)
                print(f"{name}: {pred} (p={score:.4f})")
    except Exception as e:
        print(f"推論測試略過：{e}")
