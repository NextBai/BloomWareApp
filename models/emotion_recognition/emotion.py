import os
import wave
import numpy as np
import pyaudio
import torch
import torch.nn as nn
import torch.nn.functional as F
import librosa
from transformers import AutoConfig, Wav2Vec2FeatureExtractor, HubertPreTrainedModel, HubertModel

# 模型設定
model_name_or_path = "xmj2002/hubert-base-ch-speech-emotion-recognition"
sample_rate = 16000
duration = 6  # 錄音時長(秒)

# 全域變數，用於延遲載入
_model = None
_processor = None
_config = None

# 情緒標籤
def id2class(id):
    emotions = {
        0: "生氣(angry)", 
        1: "恐懼(fear)", 
        2: "開心(happy)", 
        3: "中性(neutral)", 
        4: "悲傷(sad)", 
        5: "驚訝(surprise)"
    }
    return emotions.get(id, "未知情緒")

# 定義模型架構
class HubertClassificationHead(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.dense = nn.Linear(config.hidden_size, config.hidden_size)
        self.dropout = nn.Dropout(config.classifier_dropout)
        self.out_proj = nn.Linear(config.hidden_size, config.num_class)

    def forward(self, x):
        x = self.dense(x)
        x = torch.tanh(x)
        x = self.dropout(x)
        x = self.out_proj(x)
        return x

class HubertForSpeechClassification(HubertPreTrainedModel):
    def __init__(self, config):
        super().__init__(config)
        self.hubert = HubertModel(config)
        self.classifier = HubertClassificationHead(config)
        self.init_weights()

    def forward(self, x):
        outputs = self.hubert(x)
        hidden_states = outputs[0]
        x = torch.mean(hidden_states, dim=1)
        x = self.classifier(x)
        return x

def _load_model():
    """延遲載入模型，避免在模組匯入時就下載"""
    global _model, _processor, _config
    if _model is None:
        print("正在延遲載入情緒辨識模型...")
        try:
            _config = AutoConfig.from_pretrained(model_name_or_path)
            _processor = Wav2Vec2FeatureExtractor.from_pretrained(model_name_or_path)
            _model = HubertForSpeechClassification.from_pretrained(model_name_or_path, config=_config)
            _model.eval()
            print("情緒辨識模型載入完成！")
        except Exception as e:
            print(f"情緒辨識模型載入失敗: {e}")
            _model = None
            _processor = None
            _config = None

def record_audio():
    """從麥克風錄製音頻"""
    p = pyaudio.PyAudio()
    
    print(f"請開始說話，錄音時間為 {duration} 秒...")
    
    stream = p.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=sample_rate,
        input=True,
        frames_per_buffer=1024
    )
    
    frames = []
    for _ in range(0, int(sample_rate / 1024 * duration)):
        data = stream.read(1024)
        frames.append(data)
    
    print("錄音結束！")
    
    stream.stop_stream()
    stream.close()
    p.terminate()
    
    # 保存為臨時文件
    temp_file = "temp_recording.wav"
    wf = wave.open(temp_file, 'wb')
    wf.setnchannels(1)
    wf.setsampwidth(p.get_sample_size(pyaudio.paInt16))
    wf.setframerate(sample_rate)
    wf.writeframes(b''.join(frames))
    wf.close()
    
    return temp_file

def predict(audio_path):
    """使用模型預測情緒"""
    global _model, _processor
    if _model is None or _processor is None:
        _load_model()
        if _model is None or _processor is None:
            return 3, 0.0, {"中性(neutral)": "1.0000"}  # 返回預設值
    
    speech, sr = librosa.load(path=audio_path, sr=sample_rate)
    speech = _processor(speech, padding="max_length", truncation=True, 
                       max_length=duration * sr, return_tensors="pt", 
                       sampling_rate=sr).input_values
    
    with torch.no_grad():
        logit = _model(speech)
    
    scores = F.softmax(logit, dim=1).detach().cpu().numpy()[0]
    pred_id = torch.argmax(logit).cpu().item()
    
    # 列出所有情緒的置信度
    all_emotions = {}
    for i in range(6):
        all_emotions[id2class(i)] = f"{scores[i]:.4f}"
    
    return pred_id, scores[pred_id], all_emotions

def main():
    print("歡迎使用中文語音情緒辨識系統！")
    print("這個程式會錄製你的語音，然後辨識你的情緒。")
    
    while True:
        input("按下 Enter 開始錄音...")
        audio_path = record_audio()
        
        print("正在分析情緒...")
        pred_id, confidence, all_emotions = predict(audio_path)
        
        print("\n==========================================")
        print(f"預測結果：{id2class(pred_id)}") 
        print(f"置信度：{confidence:.4f}")
        print("\n所有情緒置信度：")
        for emotion, score in all_emotions.items():
            print(f"{emotion}: {score}")
        print("==========================================\n")
        
        choice = input("要再試一次嗎？(y/n): ")
        if choice.lower() != 'y':
            # 清理臨時文件
            if os.path.exists(audio_path):
                os.remove(audio_path)
            break
    
    print("謝謝使用！掰掰～")

if __name__ == "__main__":
    main()