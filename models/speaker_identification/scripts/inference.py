import os
import argparse
import numpy as np
import librosa
import noisereduce as nr
import pyaudio
import wave
import torch
import torch.nn as nn
import torchaudio


def get_device():
    if torch.cuda.is_available():
        print("Using device: CUDA")
        return torch.device('cuda')
    if torch.backends.mps.is_available():
        print("Using device: MPS")
        return torch.device('mps')
    print("Using device: CPU")
    return torch.device('cpu')


class Wav2Vec2SpeakerClassifier(nn.Module):
    def __init__(self, bundle, num_classes, freeze_encoder=True):
        super().__init__()
        self.encoder = bundle.get_model()
        for p in self.encoder.parameters():
            p.requires_grad = False
        hidden_dim = getattr(self.encoder, 'encoder_embed_dim', 768)
        self.classifier = nn.Sequential(
            nn.Dropout(0.0),
            nn.Linear(hidden_dim, num_classes)
        )

    def forward(self, waveforms, lengths=None):
        out = self.encoder(waveforms, lengths)
        if isinstance(out, tuple):
            features, lengths = out
        else:
            features, lengths = out, None
        if lengths is not None:
            valid_lengths = (lengths * features.size(1)).round().to(torch.long).clamp(min=1, max=features.size(1))
            mask = torch.arange(features.size(1), device=features.device).unsqueeze(0) < valid_lengths.unsqueeze(1)
            features = features * mask.unsqueeze(-1)
            pooled = features.sum(dim=1) / valid_lengths.unsqueeze(-1)
        else:
            pooled = features.mean(dim=1)
        return self.classifier(pooled)


def load_classes(classes_path_or_dir):
    # 若提供文字檔則逐行讀取，否則從目錄列出子資料夾
    if os.path.isfile(classes_path_or_dir):
        with open(classes_path_or_dir, 'r', encoding='utf-8') as f:
            classes = [line.strip() for line in f if line.strip()]
    else:
        classes = sorted([d for d in os.listdir(classes_path_or_dir)
                          if os.path.isdir(os.path.join(classes_path_or_dir, d))])
    return classes


def load_audio(path, target_sr):
    wav, sr = torchaudio.load(path)
    if wav.size(0) > 1:
        wav = wav.mean(dim=0, keepdim=True)
    if sr != target_sr:
        resampler = torchaudio.transforms.Resample(sr, target_sr)
        wav = resampler(wav)
        sr = target_sr
    wav = wav.squeeze(0)
    length = torch.tensor([wav.shape[0]], dtype=torch.long)
    return wav.unsqueeze(0), length


def softmax(x):
    e = torch.exp(x - x.max(dim=1, keepdim=True).values)
    return e / e.sum(dim=1, keepdim=True)


# ============== 錄音與前處理（比照 process_audio.py） ==============
REC_SR = 22050
TARGET_RMS = 0.1
VAD_TOP_DB = 30


def record_audio(filename, seconds=3, sr=REC_SR):
    pa = pyaudio.PyAudio()
    stream = pa.open(format=pyaudio.paInt16, channels=1, rate=sr, input=True, frames_per_buffer=1024)
    print(f"開始錄製 {seconds}s...")
    frames = []
    for _ in range(int(sr / 1024 * seconds)):
        frames.append(stream.read(1024))
    stream.stop_stream(); stream.close(); pa.terminate()
    with wave.open(filename, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(pyaudio.PyAudio().get_sample_size(pyaudio.paInt16))
        wf.setframerate(sr)
        wf.writeframes(b''.join(frames))
    print("錄製結束。")


def process_like_training(input_wav_path):
    # 與 process_audio.py 一致：librosa 載入、去噪、VAD、RMS 正規化（保留原始長度）
    y, sr = librosa.load(input_wav_path, sr=REC_SR)
    y = nr.reduce_noise(y=y, sr=sr)
    intervals = librosa.effects.split(y, top_db=VAD_TOP_DB)
    if len(intervals) > 0:
        y = np.concatenate([y[s:e] for s, e in intervals])
    # RMS 正規化
    rms = np.sqrt(np.mean(y ** 2)) if len(y) else 0.0
    if rms > 0:
        y = y * (TARGET_RMS / rms)
    return y, sr


def main():
    parser = argparse.ArgumentParser(description='Speaker ID Inference (Wav2Vec2)')
    parser.add_argument('--audio', type=str, default=None, help='Path to wav file；若省略則使用麥克風錄音')
    parser.add_argument('--model', type=str, default='speaker_id_model.pth', help='Path to model .pth')
    parser.add_argument('--classes', type=str, default='processed_audio', help='Path to classes dir or classes.txt')
    parser.add_argument('--seconds', type=int, default=3, help='錄音秒數（麥克風模式）')
    parser.add_argument('--save-processed', action='store_true', help='輸出處理後音檔 processed_record.wav')
    args = parser.parse_args()

    device = get_device()
    bundle = torchaudio.pipelines.WAV2VEC2_BASE
    target_sr = bundle.sample_rate

    classes = load_classes(args.classes)
    num_classes = len(classes)

    model = Wav2Vec2SpeakerClassifier(bundle, num_classes)
    state = torch.load(args.model, map_location='cpu')
    model.load_state_dict(state)
    model.to(device).eval()

    # 準備音訊來源：檔案或錄音
    temp_path = None
    if args.audio is None:
        temp_path = 'temp_record.wav'
        record_audio(temp_path, seconds=args.seconds, sr=REC_SR)
        raw_path = temp_path
    else:
        raw_path = args.audio

    # 前處理（比照 process_audio.py）
    y, sr = process_like_training(raw_path)
    if args.save_processed:
        try:
            import soundfile as sf
            sf.write('processed_record.wav', y, sr)
        except Exception:
            pass

    # 轉成模型輸入：重採樣到 16k + 提供長度
    y_t = torch.tensor(y, dtype=torch.float32).unsqueeze(0)
    if sr != target_sr:
        resampler = torchaudio.transforms.Resample(sr, target_sr)
        y_t = resampler(y_t)
        sr = target_sr
    length = torch.tensor([y_t.shape[1]], dtype=torch.long)
    waveforms, lengths = y_t.to(device), length.to(device)

    with torch.no_grad():
        logits = model(waveforms, lengths)
        probs = softmax(logits).squeeze(0).cpu()
        top_prob, top_idx = torch.max(probs, dim=0)
        pred = classes[top_idx.item()]

    print(f'Predicted speaker: {pred} (prob={top_prob.item():.3f})')
    # 顯示前 3 名
    topk = torch.topk(probs, k=min(3, num_classes))
    print('Top candidates:')
    for p, i in zip(topk.values.tolist(), topk.indices.tolist()):
        print(f'  {classes[i]}: {p:.3f}')

    if temp_path is not None and os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except Exception:
            pass


if __name__ == '__main__':
    main()
