import os
import librosa
import numpy as np
import noisereduce as nr
import soundfile as sf

# 參考採樣率與音量標準化
sr = 22050  # 假設採樣率
target_rms = 0.1  # 目標 RMS 水平
vad_top_db = 30  # VAD 門檻，值越小越容易刪除靜音

# 輸出目錄
output_dir = 'processed_audio'
os.makedirs(output_dir, exist_ok=True)

# 用於記錄每個子目錄的當前編號
counter = {}

# 遍歷 voice_data 目錄下的所有 .wav 和 .mp3 文件
for root, dirs, files in os.walk('voice_data'):
    for file in files:
        if file.endswith(('.wav', '.mp3')):
            file_path = os.path.join(root, file)
            # 獲取相對路徑，用於創建輸出子目錄
            rel_path = os.path.relpath(root, 'voice_data')
            sub_output_dir = os.path.join(output_dir, rel_path)
            os.makedirs(sub_output_dir, exist_ok=True)
            
            if rel_path not in counter:
                counter[rel_path] = 1
            
            y, sr = librosa.load(file_path, sr=sr)
            # 去噪
            y = nr.reduce_noise(y=y, sr=sr)
            
            # 語音活動偵測 (VAD)，移除靜音區段
            intervals = librosa.effects.split(y, top_db=vad_top_db)
            if len(intervals) == 0:
                # 無語音內容，跳過此檔
                continue
            y = np.concatenate([y[start:end] for start, end in intervals])

            # 保留原始長度並直接保存
            rms = np.sqrt(np.mean(y**2))
            if rms > 0:
                y = y * (target_rms / rms)

            output_path = os.path.join(sub_output_dir, f'voice_{counter[rel_path]:02d}.wav')
            sf.write(output_path, y, sr)
            counter[rel_path] += 1

print("音頻處理完成。")
