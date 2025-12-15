
const canvas = document.getElementById('waveform-canvas');
const ctx = canvas.getContext('2d');
const centerX = canvas.width / 2;
const centerY = canvas.height / 2;
const baseRadius = 140;
const maxAmplitude = 50;

const points = 120; // 從 180 降到 120（降低 33% 計算量）
const angleCache = [];
const cosCache = [];
const sinCache = [];

for (let i = 0; i <= points; i++) {
  const angle = (i / points) * Math.PI * 2;
  angleCache[i] = angle;
  cosCache[i] = Math.cos(angle);
  sinCache[i] = Math.sin(angle);
}

let canvasAudioContext = null;
let analyser = null;
let dataArray = null;
let bufferLength = 0;
let audioStream = null;
let useRealAudio = false; // 是否使用真實音訊數據

async function startRealAudioAnalysis() {
  try {
    audioStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        sampleRate: 16000,
        echoCancellation: true,
        noiseSuppression: true
      }
    });

    canvasAudioContext = new (window.AudioContext || window.webkitAudioContext)();
    analyser = canvasAudioContext.createAnalyser();
    analyser.fftSize = 256; // FFT 大小（必須是 2 的冪次）
    analyser.smoothingTimeConstant = 0.8; // 平滑係數（0-1）

    const source = canvasAudioContext.createMediaStreamSource(audioStream);
    source.connect(analyser);

    bufferLength = analyser.frequencyBinCount; // fftSize / 2 = 128
    dataArray = new Uint8Array(bufferLength);

    useRealAudio = true;

  } catch (error) {
    console.warn('⚠️ 無法啟動真實音訊分析（降級為假動畫）:', error);
    useRealAudio = false;

    if (error.name === 'NotAllowedError') {
      showErrorNotification('需要麥克風權限才能使用語音功能');
    }
  }
}

function stopRealAudioAnalysis() {
  if (audioStream) {
    audioStream.getTracks().forEach(track => track.stop());
    audioStream = null;
  }

  if (canvasAudioContext) {
    canvasAudioContext.close();
    canvasAudioContext = null;
  }

  analyser = null;
  dataArray = null;
  useRealAudio = false;

}

function draw360Waveform() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  const time = Date.now() * 0.001;

  if (useRealAudio && analyser && dataArray) {
    analyser.getByteFrequencyData(dataArray); // 獲取頻率數據（0-255）
  }

  for (let layer = 0; layer < 3; layer++) {
    ctx.beginPath();
    ctx.strokeStyle = `rgba(0, 0, 0, ${0.08 - layer * 0.02})`;
    ctx.lineWidth = 2 - layer * 0.5;

    const layerOffset = layer * 0.5;
    const layerMultiplier = 1 - layer * 0.2;

    for (let i = 0; i <= points; i++) {
      const angle = angleCache[i];

      let amplitude;

      if (useRealAudio && dataArray && bufferLength > 0) {
        const dataIndex = Math.floor((i / points) * bufferLength);
        const audioValue = dataArray[dataIndex] / 255.0; // 標準化到 0-1

        const wave1 = audioValue * 0.6; // 主要由音訊驅動
        const wave2 = Math.sin(angle * 4 - time * 1.2) * 0.1; // 保留少量動畫
        const wave3 = sinCache[i * 6 % points] * 0.05 * Math.cos(time * 2);

        amplitude = (wave1 + wave2 + wave3) * layerMultiplier;

      } else {
        const wave1 = Math.sin(angle * 2 + time * 1.5 + layerOffset) * 0.3;
        const wave2 = Math.sin(angle * 4 - time * 1.2) * 0.2;
        const wave3 = sinCache[i * 6 % points] * 0.15 * Math.cos(time * 2);
        amplitude = (wave1 + wave2 + wave3) * layerMultiplier;
      }

      const radius = baseRadius + layer * 15 + (amplitude * maxAmplitude);
      const x = centerX + cosCache[i] * radius;
      const y = centerY + sinCache[i] * radius;

      if (i === 0) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
    }

    ctx.closePath();
    ctx.stroke();
  }

  requestAnimationFrame(draw360Waveform);
}

draw360Waveform();
