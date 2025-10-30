import os
import random

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
import torch
import torch.nn as nn
import torch.optim as optim
import torchaudio
import torchaudio.functional as F
from sklearn.metrics import confusion_matrix
from sklearn.preprocessing import LabelEncoder
from sklearn.utils.class_weight import compute_class_weight
from torch.utils.data import DataLoader, Dataset


# 基本參數
data_dir = '/kaggle/input/voice-identity/processed_audio'
batch_size = 16
num_epochs = 50

# 遷移學習設定（不使用 HuggingFace，改用 torchaudio 內建預訓練）
bundle = torchaudio.pipelines.WAV2VEC2_BASE
target_sr = bundle.sample_rate
freeze_encoder = True      # 先凍結整個 encoder，只訓練分類頭
unfreeze_last_n = 2        # 若要微調，可調整解凍的 Transformer 層數
head_learning_rate = 1e-3
encoder_learning_rate = 1e-5
encoder_warmup_epochs = 10  # 預設 10 epoch 後解凍最後幾層（若 unfreeze_last_n > 0）
pitch_shift_semitones = [0, -4, 4]  # 每筆資料的音調擴增組合


def waveform_augment(waveform, sr, max_shift_ratio=0.02, noise_factor=0.002):
    """時間平移 + 微量噪音；針對短音訊使用較小位移"""
    if max_shift_ratio > 0:
        shift = int(sr * max_shift_ratio)
        if shift > 0:
            offset = random.randint(-shift, shift)
            waveform = torch.roll(waveform, offset, dims=1)
    if noise_factor > 0:
        noise = torch.randn_like(waveform) * noise_factor
        waveform = waveform + noise
    return waveform


class SpeakerDataset(Dataset):
    def __init__(self, data_dir, classes, transform=None, target_sr=16000, pitch_shifts=None):
        self.data_dir = data_dir
        self.classes = classes
        self.transform = transform
        self.target_sr = target_sr
        self.resamplers = {}
        self.pitch_shifts = sorted(set(pitch_shifts or [0]))
        self.data = []

        for label, cls in enumerate(classes):
            cls_dir = os.path.join(data_dir, cls)
            for file in os.listdir(cls_dir):
                if file.endswith('.wav'):
                    file_path = os.path.join(cls_dir, file)
                    for shift in self.pitch_shifts:
                        self.data.append((file_path, label, shift))

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        file_path, label, semitone = self.data[idx]
        waveform, sr = torchaudio.load(file_path)

        if waveform.size(0) > 1:
            waveform = waveform.mean(dim=0, keepdim=True)

        if sr != self.target_sr:
            if sr not in self.resamplers:
                self.resamplers[sr] = torchaudio.transforms.Resample(sr, self.target_sr)
            waveform = self.resamplers[sr](waveform)
            sr = self.target_sr

        if semitone != 0:
            waveform = F.pitch_shift(waveform, sr, n_steps=semitone)

        if self.transform:
            waveform = self.transform(waveform, sr)

        return waveform.squeeze(0), label


def collate_waveforms(batch):
    waveforms, labels = zip(*batch)
    lengths = torch.tensor([waveform.shape[0] for waveform in waveforms], dtype=torch.long)
    max_len = lengths.max().item()
    padded = torch.zeros(len(waveforms), max_len)
    for idx, waveform in enumerate(waveforms):
        padded[idx, : waveform.shape[0]] = waveform
    labels_tensor = torch.tensor(labels, dtype=torch.long)
    return padded, lengths, labels_tensor


class Wav2Vec2SpeakerClassifier(nn.Module):
    def __init__(self, bundle, num_classes, freeze_encoder=True, unfreeze_last_n=0):
        super().__init__()
        self.encoder = bundle.get_model()
        self.freeze_encoder = freeze_encoder
        self.unfreeze_last_n = unfreeze_last_n

        # 預設凍結整個 encoder
        for param in self.encoder.parameters():
            param.requires_grad = False

        if not freeze_encoder:
            # 先全部鎖住，再選擇性解凍最後 N 層；若無法部分解凍則退而求其次為完全解凍
            transformer_layers = getattr(self.encoder, 'encoder', None)
            if transformer_layers is not None and hasattr(transformer_layers, 'layers') and unfreeze_last_n > 0:
                for layer in transformer_layers.layers[-unfreeze_last_n:]:
                    for param in layer.parameters():
                        param.requires_grad = True
            elif not freeze_encoder:
                for param in self.encoder.parameters():
                    param.requires_grad = True

        self.encoder_frozen = freeze_encoder

        hidden_dim = getattr(self.encoder, 'encoder_embed_dim', 768)
        self.classifier = nn.Sequential(
            nn.Dropout(0.3),
            nn.Linear(hidden_dim, num_classes)
        )

    def unfreeze_last_layers(self, n_layers=None):
        """解凍最後 n 層 Transformer block，回傳剛解凍的參數列表。"""
        n_layers = n_layers or self.unfreeze_last_n
        unfrozen_params = []
        transformer_layers = getattr(self.encoder, 'encoder', None)
        if transformer_layers is not None and hasattr(transformer_layers, 'layers') and n_layers > 0:
            target_layers = transformer_layers.layers[-n_layers:]
            for layer in target_layers:
                for param in layer.parameters():
                    if not param.requires_grad:
                        param.requires_grad = True
                        unfrozen_params.append(param)
        elif n_layers > 0:
            for param in self.encoder.parameters():
                if not param.requires_grad:
                    param.requires_grad = True
                    unfrozen_params.append(param)
        if unfrozen_params:
            self.encoder_frozen = False
        return unfrozen_params

    def forward(self, waveforms, lengths=None):
        if waveforms.dim() != 2:
            raise ValueError("音訊張量應為 [batch, time] 形式")

        encoder_out = self.encoder(waveforms, lengths)
        if isinstance(encoder_out, tuple):
            features, lengths = encoder_out
        else:
            features, lengths = encoder_out, None

        if lengths is not None:
            if torch.is_floating_point(lengths):
                valid_lengths = (lengths * features.size(1)).round().to(torch.long)
            else:
                valid_lengths = lengths.to(torch.long)
            valid_lengths = valid_lengths.clamp(min=1, max=features.size(1))
            mask = torch.arange(features.size(1), device=features.device).unsqueeze(0) < valid_lengths.unsqueeze(1)
            masked_features = features * mask.unsqueeze(-1)
            pooled = masked_features.sum(dim=1) / valid_lengths.unsqueeze(-1)
        else:
            pooled = features.mean(dim=1)

        logits = self.classifier(pooled)
        return logits


classes = sorted([d for d in os.listdir(data_dir) if os.path.isdir(os.path.join(data_dir, d))])
num_classes = len(classes)
label_encoder = LabelEncoder()
label_encoder.fit(classes)

dataset = SpeakerDataset(
    data_dir=data_dir,
    classes=classes,
    transform=waveform_augment,
    target_sr=target_sr,
    pitch_shifts=pitch_shift_semitones
)
train_loader = DataLoader(
    dataset,
    batch_size=batch_size,
    shuffle=True,
    num_workers=0,
    pin_memory=False,
    collate_fn=collate_waveforms
)

labels = [label for _, label, _ in dataset.data]
class_weights = compute_class_weight('balanced', classes=np.unique(labels), y=labels)
class_weights = torch.tensor(class_weights, dtype=torch.float)

if torch.cuda.is_available():
    device = torch.device('cuda')
    print("Using device: CUDA")
elif torch.backends.mps.is_available():
    device = torch.device('mps')
    print("Using device: MPS")
else:
    device = torch.device('cpu')
    print("Using device: CPU")

model = Wav2Vec2SpeakerClassifier(
    bundle=bundle,
    num_classes=num_classes,
    freeze_encoder=freeze_encoder,
    unfreeze_last_n=unfreeze_last_n
).to(device)
criterion = nn.CrossEntropyLoss(weight=class_weights.to(device))

encoder_params = [p for p in model.encoder.parameters() if p.requires_grad]
head_params = list(model.classifier.parameters())
if encoder_params:
    optimizer = optim.Adam([
        {'params': head_params, 'lr': head_learning_rate},
        {'params': encoder_params, 'lr': encoder_learning_rate}
    ])
else:
    optimizer = optim.Adam(head_params, lr=head_learning_rate)

use_amp = torch.cuda.is_available()
scaler = torch.amp.GradScaler() if use_amp else None

def add_encoder_params_to_optimizer(model, optimizer, lr):
    existing_params = set()
    for group in optimizer.param_groups:
        existing_params.update(id(p) for p in group['params'])
    new_params = [p for p in model.encoder.parameters() if p.requires_grad and id(p) not in existing_params]
    if new_params:
        optimizer.add_param_group({'params': new_params, 'lr': lr})

for epoch in range(num_epochs):
    # 動態解凍策略：達到指定 epoch 後解凍最後幾層
    if model.encoder_frozen and unfreeze_last_n > 0 and (epoch + 1) == encoder_warmup_epochs:
        newly_unfrozen = model.unfreeze_last_layers(unfreeze_last_n)
        if newly_unfrozen:
            add_encoder_params_to_optimizer(model, optimizer, encoder_learning_rate)
            print(f'Unfroze last {unfreeze_last_n} encoder layer(s) at epoch {epoch + 1}.')

    model.train()
    if model.encoder_frozen:
        model.encoder.eval()
    else:
        model.encoder.train()

    running_loss = 0.0
    for waveforms, lengths, labels_batch in train_loader:
        waveforms = waveforms.to(device)
        lengths = lengths.to(device)
        labels_batch = labels_batch.to(device)
        optimizer.zero_grad()

        if use_amp:
            with torch.amp.autocast(device_type='cuda'):
                logits = model(waveforms, lengths)
                loss = criterion(logits, labels_batch)
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
        else:
            logits = model(waveforms, lengths)
            loss = criterion(logits, labels_batch)
            loss.backward()
            optimizer.step()

        running_loss += loss.item()

    avg_loss = running_loss / len(train_loader)
    print(f'Epoch {epoch + 1}/{num_epochs}, Loss: {avg_loss:.4f}')

model.eval()
all_preds = []
all_labels = []
with torch.no_grad():
    for waveforms, lengths, labels_batch in train_loader:
        waveforms = waveforms.to(device)
        lengths = lengths.to(device)
        logits = model(waveforms, lengths)
        preds = torch.argmax(logits, dim=1)
        all_preds.extend(preds.cpu().numpy())
        all_labels.extend(labels_batch.numpy())

cm = confusion_matrix(all_labels, all_preds)
print("Confusion Matrix:")
print(cm)

plt.figure(figsize=(8, 6))
sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', xticklabels=classes, yticklabels=classes)
plt.title('Confusion Matrix')
plt.xlabel('Predicted')
plt.ylabel('True')
plt.savefig('confusion_matrix.png')
plt.close()

torch.save(model.state_dict(), 'speaker_id_model.pth')
print("訓練完成，模型已保存。")
