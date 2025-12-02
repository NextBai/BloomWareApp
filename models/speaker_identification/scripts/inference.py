import os
import torch
import librosa
import numpy as np
import pickle
import wave
import pyaudio
from speechbrain.pretrained import EncoderClassifier
from sklearn.metrics.pairwise import cosine_similarity

# 常數
SAMPLE_RATE = 16000
DB_FILE = "speaker_db.pkl"

# 全域 classifier（延遲載入）
_classifier = None


def get_classifier():
    """取得 ECAPA-TDNN 分類器（單例模式）"""
    global _classifier
    if _classifier is None:
        _classifier = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb"
        )
    return _classifier


def get_embedding(file_path):
    """從音訊檔案取得 ECAPA-TDNN 嵌入向量"""
    signal, sr = librosa.load(file_path, sr=SAMPLE_RATE, mono=True)
    signal_tensor = torch.tensor(signal).unsqueeze(0)
    classifier = get_classifier()
    embedding = classifier.encode_batch(signal_tensor)
    return embedding.squeeze().detach().numpy()


def load_speaker_db(db_path):
    """載入說話者嵌入資料庫"""
    with open(db_path, "rb") as f:
        speaker_embeddings = pickle.load(f)
    return speaker_embeddings


def recognize_speaker(test_file, speaker_embeddings):
    """
    辨識語音（與原始 ECAPA_TDNN.py 完全一致）
    """
    test_emb = get_embedding(test_file).reshape(1, -1)
    scores = {}
    for spk, emb in speaker_embeddings.items():
        sim = cosine_similarity(test_emb, emb.reshape(1, -1))[0][0]
        scores[spk] = sim
    predicted = max(scores, key=scores.get)
    scores[predicted] += 0.35
    return predicted, scores


def predict_files(model_dir, file_list, threshold=0.0):
    """
    預測多個音訊檔案的說話者

    Args:
        model_dir: 模型目錄，包含 speaker_db.pkl
        file_list: 檔案路徑列表
        threshold: 未使用，保留介面相容

    Returns:
        結果列表，每個元素為字典，包含 'pred', 'score', 'top'
    """
    db_path = os.path.join(model_dir, DB_FILE)
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"找不到說話者資料庫：{db_path}")

    speaker_embeddings = load_speaker_db(db_path)
    results = []

    for file_path in file_list:
        try:
            predicted, scores = recognize_speaker(file_path, speaker_embeddings)

            # 排序取 top 候選
            sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            top = [(spk, float(score)) for spk, score in sorted_scores[:3]]

            result = {
                'pred': predicted,
                'score': float(scores[predicted]),
                'top': top
            }
            results.append(result)
        except Exception as e:
            results.append({'error': str(e)})

    return results


# ============== 錄音功能 ==============
def record_audio(filename, seconds=3, sr=SAMPLE_RATE):
    """從麥克風錄製音訊"""
    pa = pyaudio.PyAudio()
    stream = pa.open(format=pyaudio.paInt16, channels=1, rate=sr, input=True, frames_per_buffer=1024)
    print(f"開始錄製 {seconds}s...")
    frames = []
    for _ in range(int(sr / 1024 * seconds)):
        frames.append(stream.read(1024))
    stream.stop_stream()
    stream.close()
    pa.terminate()
    with wave.open(filename, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(pyaudio.PyAudio().get_sample_size(pyaudio.paInt16))
        wf.setframerate(sr)
        wf.writeframes(b''.join(frames))
    print("錄製結束。")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Speaker ID Inference (ECAPA-TDNN)')
    parser.add_argument('--audio', type=str, default=None, help='音訊檔案路徑；若省略則使用麥克風錄音')
    parser.add_argument('--db', type=str, default='speaker_db.pkl', help='說話者資料庫路徑')
    parser.add_argument('--seconds', type=int, default=3, help='錄音秒數（麥克風模式）')
    args = parser.parse_args()

    # 載入資料庫
    speaker_embeddings = load_speaker_db(args.db)
    print(f"已載入 {len(speaker_embeddings)} 位說話者：{list(speaker_embeddings.keys())}")

    # 準備音訊
    temp_path = None
    if args.audio is None:
        temp_path = 'temp_record.wav'
        record_audio(temp_path, seconds=args.seconds)
        audio_path = temp_path
    else:
        audio_path = args.audio

    # 辨識
    predicted, scores = recognize_speaker(audio_path, speaker_embeddings)

    print(f'\n辨識結果：{predicted}')
    print('辨識機率：')
    for spk, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
        print(f'  {spk}: {score:.4f}')

    # 清理暫存檔
    if temp_path and os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except Exception:
            pass


if __name__ == '__main__':
    main()
