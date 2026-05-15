// ============================================================
// TTS 模組：支援即時句子串流播放 + Emoji/Markdown 清除
// ============================================================

let currentAudio = null;
let isPlaying = false;
let audioContext = null;
let userGestureReceived = false;
let pendingAudioUrl = null;
let ttsStreamSocket = null;
let ttsStreamNextStartAt = 0;
let _ttsActiveSources = [];

// === Streaming TTS State ===
let _streamTtsQueue = [];        // 待合成播放的句子佇列
let _streamTtsProcessing = false; // 是否正在處理佇列
let _streamTtsProcessedLen = 0;  // 已送入佇列的文字長度（用於增量偵測）
let _streamTtsStopped = false;   // 是否已停止（對話重置時設定）
let _streamTtsQueuedCount = 0;
let _streamTtsPlayedCount = 0;
let _streamTtsFinalText = '';
let _streamTtsFallbackUsed = false;

function logTtsDebug(event, extra = {}) {
  if (!window.DEBUG_MODE) {
    return;
  }
  console.info('[TTS_DEBUG]', event, {
    currentState: typeof currentState !== 'undefined' ? currentState : 'unknown',
    queueLength: _streamTtsQueue.length,
    processing: _streamTtsProcessing,
    stopped: _streamTtsStopped,
    isPlaying,
    activeSources: _ttsActiveSources.length,
    ...extra,
  });
}

function maybeFinalizeSpeechPlayback() {
  const typewriterActive = !!(window.typewriterState && window.typewriterState.isActive);
  const speechSettled = _streamTtsQueue.length === 0 && !_streamTtsProcessing && !isPlaying;
  if (!speechSettled || typewriterActive) {
    return;
  }

  window.agentOutputAwaitingSpeechCompletion = false;
  if (typeof currentState !== 'undefined' && currentState === 'speaking') {
    setState('idle', { clearCards: false });
  }
}


function getTtsLanguage() {
  const sessionLanguage = window.currentConversationLanguage || window.currentSpeechLanguage;
  if (sessionLanguage && sessionLanguage !== 'auto') {
    return String(sessionLanguage);
  }
  const browserLanguage = navigator.language || navigator.userLanguage || 'zh-TW';
  return String(browserLanguage || 'zh-TW');
}

function getTtsPersona() {
  return 'xiaohua';
}

function getTtsSpeakingRate() {
  return 1.12;
}

function normalizeTextForChirp(text) {
  const source = String(text || '');
  if (!source) return '';

  return source
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/__([^_]+)__/g, '$1')
    .replace(/\*([^*\n]+)\*/g, '$1')
    .replace(/_([^_\n]+)_/g, '$1')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/^\s*[-*]\s+/gm, '')
    .replace(/^\s*\d+\.\s+/gm, '')
    .replace(/[|{}[\]^<>~`]/g, ' ')
    .replace(/\s*[:：]\s*/g, '：')
    .replace(/\s+/g, ' ')
    .replace(/，/g, '，')
    .replace(/。/g, '。')
    .trim();
}

function buildXiaohuaMarkup(text) {
  const source = normalizeTextForChirp(text);
  if (!source) return '';

  const sentenceLike = source
    .replace(/([。！？!?])/g, '$1\n')
    .replace(/([，、；;])/g, '$1[pause short]')
    .split('\n')
    .map(part => part.trim())
    .filter(Boolean);

  return sentenceLike.join('[pause]');
}

function getTtsMarkup(text) {
  return buildXiaohuaMarkup(text);
}

function getTtsCustomPronunciations(language, text = '') {
  const normalized = String(language || '').toLowerCase();
  const sourceText = String(text || '');
  if (normalized.startsWith('zh')) {
    const entries = [];
    if (sourceText.includes('桃園')) {
      entries.push({
        phrase: '桃園',
        pronunciation: 'tao2 yuan2',
        phonetic_encoding: 'PHONETIC_ENCODING_PINYIN'
      });
    }
    if (sourceText.includes('多雲')) {
      entries.push({
        phrase: '多雲',
        pronunciation: 'duo1 yun2',
        phonetic_encoding: 'PHONETIC_ENCODING_PINYIN'
      });
    }
    return entries;
  }

  if (normalized.startsWith('ja')) {
    const entries = [];
    if (sourceText.includes('Bloom Ware')) {
      entries.push({
        phrase: 'Bloom Ware',
        pronunciation: 'ブルームウェア',
        phonetic_encoding: 'PHONETIC_ENCODING_JAPANESE_YOMIGANA'
      });
    }
    return entries;
  }

  if (normalized.startsWith('en')) {
    const entries = [];
    if (sourceText.includes('Bloom Ware')) {
      entries.push({
        phrase: 'Bloom Ware',
        pronunciation: 'bluːm wɛr',
        phonetic_encoding: 'PHONETIC_ENCODING_IPA'
      });
    }
    if (sourceText.includes('Chirp')) {
      entries.push({
        phrase: 'Chirp',
        pronunciation: 'tʃɝːp',
        phonetic_encoding: 'PHONETIC_ENCODING_IPA'
      });
    }
    return entries;
  }

  return [];
}

function float32ToAudioBuffer(float32Array, sampleRate) {
  const ctx = getAudioContext();
  const audioBuffer = ctx.createBuffer(1, float32Array.length, sampleRate);
  audioBuffer.copyToChannel(float32Array, 0);
  return audioBuffer;
}

function pcm16Base64ToFloat32(base64String) {
  const binary = atob(base64String);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  const pcm16 = new Int16Array(bytes.buffer);
  const float32 = new Float32Array(pcm16.length);
  for (let i = 0; i < pcm16.length; i++) {
    float32[i] = pcm16[i] / 0x8000;
  }
  return float32;
}

async function playStreamingTTS(text) {
  if (!text) return false;
  await ensureAudioReady();

  if (ttsStreamSocket) {
    logTtsDebug('socket_replace_close');
    try { ttsStreamSocket.close(); } catch (_) {}
    ttsStreamSocket = null;
  }

  return await new Promise((resolve) => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const socket = new WebSocket(`${protocol}//${window.location.host}/ws/tts`);
    ttsStreamSocket = socket;
    let resolved = false;
    let sampleRate = 24000;
    let receivedChunk = false;

    const finish = (ok) => {
      if (resolved) return;
      resolved = true;
      if (ttsStreamSocket === socket) {
        ttsStreamSocket = null;
      }
      resolve(ok);
    };

    const language = getTtsLanguage();
    const normalizedText = normalizeTextForChirp(text);
    const markup = getTtsMarkup(normalizedText);
    const customPronunciations = getTtsCustomPronunciations(language, normalizedText);

    socket.onopen = () => {
      logTtsDebug('socket_open', { textLength: normalizedText.length, audioContextState: getAudioContext().state });
      ttsStreamNextStartAt = Math.max(getAudioContext().currentTime + 0.05, ttsStreamNextStartAt);
      socket.send(JSON.stringify({
        text: normalizedText,
        voice: 'nova',
        speed: 1.0,
        language,
        persona: getTtsPersona(),
        speaking_rate: getTtsSpeakingRate(),
        markup,
        custom_pronunciations: customPronunciations,
        emotion: window.currentEmotion || 'neutral',
        care_mode: window.isInCareMode || false
      }));
    };

    socket.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.type === 'tts_stream_start') {
        sampleRate = Number(message.sample_rate || 24000);
        logTtsDebug('stream_start', { sampleRate });
        return;
      }
      if (message.type === 'tts_audio_chunk') {
        receivedChunk = true;
        logTtsDebug('audio_chunk', { base64Length: (message.audio_base64 || '').length });
        if (_streamTtsStopped) return; // 已停止播放

        const float32 = pcm16Base64ToFloat32(message.audio_base64);
        const buffer = float32ToAudioBuffer(float32, sampleRate);
        const source = getAudioContext().createBufferSource();
        source.buffer = buffer;
        source.connect(getAudioContext().destination);
        source.start(ttsStreamNextStartAt);
        ttsStreamNextStartAt += buffer.duration;
        
        // 追蹤來源以便停止
        _ttsActiveSources.push(source);
        isPlaying = true;
        logTtsDebug('audio_scheduled', { duration: buffer.duration, nextStartAt: ttsStreamNextStartAt });
        
        source.onended = () => {
          // 移除已結束的來源
          _ttsActiveSources = _ttsActiveSources.filter(s => s !== source);
          if (getAudioContext().currentTime >= ttsStreamNextStartAt - 0.02) {
            isPlaying = false;
          }
          logTtsDebug('audio_ended', { remainingSources: _ttsActiveSources.length });
          maybeFinalizeSpeechPlayback();
        };
        return;
      }
      if (message.type === 'tts_stream_end') {
        logTtsDebug('stream_end', { receivedChunk });
        finish(receivedChunk);
        socket.close();
        return;
      }
      if (message.type === 'tts_error') {
        console.warn('串流 TTS 失敗:', message.error);
        logTtsDebug('stream_error', { error: message.error });
        finish(false);
        socket.close();
      }
    };

    socket.onerror = () => {
      logTtsDebug('socket_error');
      finish(false);
    };
    socket.onclose = (event) => {
      logTtsDebug('socket_close', {
        receivedChunk,
        code: event.code,
        reason: event.reason || '',
        wasClean: event.wasClean,
      });
      finish(receivedChunk);
    };
  });
}

function getAudioContext() {
  if (!audioContext) {
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
  }
  return audioContext;
}

// === Audio Analysis for Flower Animation ===
let ttsAnalyzer = null;
let ttsDataArray = null;
let ttsVisualizerAnimationId = null;

function initAnalyzer() {
  const ctx = getAudioContext();
  if (!ttsAnalyzer) {
    ttsAnalyzer = ctx.createAnalyser();
    ttsAnalyzer.fftSize = 256;
    const bufferLength = ttsAnalyzer.frequencyBinCount;
    ttsDataArray = new Uint8Array(bufferLength);
  }
  return ttsAnalyzer;
}

function connectVisualizer(audioElement) {
  try {
    const ctx = getAudioContext();
    const source = ctx.createMediaElementSource(audioElement);
    const node = initAnalyzer();
    source.connect(node);
    node.connect(ctx.destination);
    
    startVisualizerLoop();
  } catch (err) {
    // MediaElementSource might fail if already connected or other issues
    console.warn('Visualizer connection failed:', err);
  }
}

function startVisualizerLoop() {
  if (ttsVisualizerAnimationId) cancelAnimationFrame(ttsVisualizerAnimationId);
  
  const update = () => {
    if (!isPlaying) {
      document.documentElement.style.setProperty('--core-scale', '1');
      ttsVisualizerAnimationId = null;
      return;
    }
    
    ttsVisualizerAnimationId = requestAnimationFrame(update);
    if (ttsAnalyzer) {
      ttsAnalyzer.getByteFrequencyData(ttsDataArray);
      let sum = 0;
      // Get volume from low-mid frequencies for a better pulse effect
      const count = Math.min(ttsDataArray.length, 32); 
      for (let i = 0; i < count; i++) {
        sum += ttsDataArray[i];
      }
      const average = sum / count;
      // Map volume to scale: 1.0 (silent) to ~1.4 (loud)
      const scale = 1 + (average / 255) * 0.45;
      document.documentElement.style.setProperty('--core-scale', scale.toFixed(3));
    }
  };
  
  update();
}

async function ensureAudioReady() {
  try {
    audioContext = getAudioContext();
    if (audioContext.state === 'suspended') {
      await audioContext.resume();
    }
    userGestureReceived = true;
    return true;
  } catch (error) {
    console.warn('無法解鎖音頻播放:', error);
    return false;
  }
}

async function unlockAudioPlayback() {
  const ready = await ensureAudioReady();
  if (!ready || !pendingAudioUrl) {
    return ready;
  }

  const audioUrl = pendingAudioUrl;
  pendingAudioUrl = null;
  await playAudioUrl(audioUrl);
  return true;
}

function installAudioUnlockListeners() {
  const events = ['pointerdown', 'touchstart', 'keydown'];
  const unlock = () => {
    unlockAudioPlayback();
  };

  events.forEach((eventName) => {
    document.addEventListener(eventName, unlock, {
      passive: true,
      capture: true
    });
  });
}

async function playAudioUrl(audioUrl) {
  stopSpeaking(false);
  try {
    await ensureAudioReady();
    
    currentAudio = new Audio(audioUrl);
    currentAudio.crossOrigin = "anonymous";
    currentAudio.preload = 'auto';
    
    isPlaying = true;
    
    // Connect to visualizer ONLY after context is ready
    connectVisualizer(currentAudio);
    
    await currentAudio.play();
  } catch (playError) {
    isPlaying = false;
    if (playError && playError.name === 'NotAllowedError') {
      pendingAudioUrl = audioUrl;
      console.warn('瀏覽器尚未允許自動播放，已排入下一次使用者手勢播放');
      return;
    }

    setTimeout(() => URL.revokeObjectURL(audioUrl), 1000);
    throw playError;
  }
}

// ============================================================
// 文字清理：去除 Emoji、Markdown 符號，讓 TTS 更自然
// ============================================================
function cleanTextForTTS(text) {
  if (!text) return '';
  return text
    // 移除 Emoji（Supplementary Multilingual Plane）
    .replace(/[\u{1F000}-\u{1FFFF}]/gu, '')
    // 移除 Emoji 和符號（Basic Multilingual Plane）
    .replace(/[\u{2600}-\u{27FF}]/gu, '')
    .replace(/[\u{2B00}-\u{2BFF}]/gu, '')
    .replace(/[\u{FE00}-\u{FEFF}]/gu, '')
    // 移除 Markdown：粗體、斜體
    .replace(/\*{1,3}([^*\n]+)\*{1,3}/g, '$1')
    .replace(/_{1,2}([^_\n]+)_{1,2}/g, '$1')
    // 移除 Markdown：標題符號
    .replace(/^#{1,6}\s+/gm, '')
    // 移除 Markdown：行內程式碼
    .replace(/`([^`]+)`/g, '$1')
    // 移除 Markdown：連結，只保留文字
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    // 移除 Markdown：刪除線
    .replace(/~~([^~]+)~~/g, '$1')
    // 移除多餘空白
    .replace(/\s+/g, ' ')
    .trim();
}

// ============================================================
// 句子串流 TTS 系統：讓每個句子完成後立即開始 TTS 合成
// ============================================================

// 句子邊界：中英文句號、驚嘆號、問號、換行
const SENTENCE_END_RE = /[。！？!?\n]+/g;

/**
 * 從文字中提取完整句子（有句尾標點），回傳 [{text, endIdx}]
 */
function _extractCompleteSentences(text) {
  const sentences = [];
  SENTENCE_END_RE.lastIndex = 0;
  let match;
  let lastIdx = 0;
  while ((match = SENTENCE_END_RE.exec(text)) !== null) {
    const sentence = text.slice(lastIdx, match.index + match[0].length).trim();
    if (sentence) sentences.push(sentence);
    lastIdx = match.index + match[0].length;
  }
  // 回傳最後一個完整句子之後的處理位置
  return { sentences, nextIdx: lastIdx };
}

/**
 * 等待 Audio 播放完畢的 Promise
 */
function _playAndWait(audioUrl) {
  return new Promise((resolve) => {
    ensureAudioReady().then(() => {
      const audio = new Audio(audioUrl);
      audio.crossOrigin = "anonymous";
      audio.preload = 'auto';
      currentAudio = audio;
      
      isPlaying = true;
      
      // Connect to visualizer
      connectVisualizer(audio);

      const cleanup = () => {
        isPlaying = false;
        setTimeout(() => URL.revokeObjectURL(audioUrl), 1000);
        maybeFinalizeSpeechPlayback();
        resolve();
      };

      audio.onended = cleanup;
      audio.onerror = cleanup;

      audio.play().catch(cleanup);
    }).catch((err) => {
      console.error('ensureAudioReady 失敗:', err);
      resolve();
    });
  });
}

/**
 * 合成並播放單一句子（回傳 Promise，播完才 resolve）
 */
async function _synthesizeAndPlay(text) {
  const cleaned = cleanTextForTTS(normalizeTextForChirp(text));
  if (!cleaned) return false;

  try {
    const streamed = await playStreamingTTS(cleaned);
    if (streamed) {
      return true;
    }

    const response = await fetch('/api/tts', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${localStorage.getItem('jwt_token')}`
      },
      body: JSON.stringify({
        text: cleaned,
        voice: 'nova',
        speed: 1.0,
        language: getTtsLanguage(),
        persona: getTtsPersona(),
        speaking_rate: getTtsSpeakingRate()
      })
    });

    if (!response.ok) {
      console.warn('TTS API 錯誤:', response.status);
      return false;
    }

    const audioBlob = await response.blob();
    const audioUrl = URL.createObjectURL(audioBlob);
    await _playAndWait(audioUrl);
    return true;
  } catch (error) {
    console.warn('TTS 合成播放失敗:', error);
    return false;
  }
}

function shouldFallbackToFullTTS() {
  return _streamTtsStopped || (_streamTtsQueuedCount === 0 && !_streamTtsProcessing && !isPlaying);
}

function hasPendingStreamingSpeech() {
  return _streamTtsQueue.length > 0 || _streamTtsProcessing || isPlaying || !!ttsStreamSocket || _ttsActiveSources.length > 0;
}

/**
 * 非同步處理佇列，確保句子按順序播放
 */
async function _runTtsQueue() {
  if (_streamTtsProcessing) return;
  _streamTtsProcessing = true;

  while (_streamTtsQueue.length > 0 && !_streamTtsStopped) {
    const sentence = _streamTtsQueue.shift();
    const played = await _synthesizeAndPlay(sentence);
    if (played) {
      _streamTtsPlayedCount += 1;
    }
  }

  _streamTtsProcessing = false;

  if (_streamTtsFinalText && !_streamTtsFallbackUsed && _streamTtsQueuedCount > 0 && _streamTtsPlayedCount === 0 && !isPlaying) {
    _streamTtsFallbackUsed = true;
    await speakText(_streamTtsFinalText);
    return;
  }

  maybeFinalizeSpeechPlayback();
}

/**
 * 在 bot_delta 串流過程中呼叫，傳入目前全部累積的文字。
 * 偵測到新的完整句子後立即加入 TTS 佇列。
 */
function enqueueStreamingTTS(fullText) {
  if (_streamTtsStopped || !fullText) return;

  // 只處理新增的部分
  const newPart = fullText.slice(_streamTtsProcessedLen);
  if (!newPart) return;

  const { sentences, nextIdx } = _extractCompleteSentences(newPart);

  for (const sentence of sentences) {
    if (sentence.trim()) {
      _streamTtsQueue.push(sentence);
      _streamTtsQueuedCount += 1;
    }
  }
  _streamTtsProcessedLen += nextIdx;

  // 啟動佇列處理（若尚未啟動）
  if (sentences.length > 0) {
    _runTtsQueue();
  }
}

/**
 * 在 bot_message（串流結束）時呼叫，處理最後一段未以標點結尾的文字。
 */
function finalizeStreamingTTS(fullText) {
  if (!fullText) return;
  _streamTtsFinalText = fullText;

  const remaining = fullText.slice(_streamTtsProcessedLen).trim();
  if (remaining) {
    _streamTtsQueue.push(remaining);
    _streamTtsQueuedCount += 1;
    _streamTtsProcessedLen = fullText.length;
    _runTtsQueue();
  }
}

/**
 * 重置串流 TTS 狀態（每次新的對話開始時呼叫）
 */
function resetStreamingTTS() {
  _streamTtsQueue = [];
  _streamTtsProcessedLen = 0;
  _streamTtsStopped = false;
  _streamTtsQueuedCount = 0;
  _streamTtsPlayedCount = 0;
  _streamTtsFinalText = '';
  _streamTtsFallbackUsed = false;
  // 不立即停止正在播放的音訊，讓它自然結束
}

// ============================================================
// 舊有的 speakText（完整文字合成，保留供非串流場景使用）
// ============================================================
async function speakText(text) {
  stopSpeaking();

  const cleaned = cleanTextForTTS(normalizeTextForChirp(text));
  if (!cleaned) return;

  try {
    const streamed = await playStreamingTTS(cleaned);
    if (streamed) {
      return;
    }

    const response = await fetch('/api/tts', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${localStorage.getItem('jwt_token')}`
      },
      body: JSON.stringify({
        text: cleaned,
        voice: 'nova',
        speed: 1.0,
        language: getTtsLanguage(),
        persona: getTtsPersona(),
        speaking_rate: getTtsSpeakingRate()
      })
    });

    if (!response.ok) {
      const error = await response.json();
      console.error('TTS API 錯誤:', error);
      return;
    }

    const audioBlob = await response.blob();
    const audioUrl = URL.createObjectURL(audioBlob);
    await playAudioUrl(audioUrl);
  } catch (error) {
    console.error('TTS 請求失敗:', error);
    isPlaying = false;
  }
}

function stopSpeaking(clearPending = true, reason = 'unspecified') {
  logTtsDebug('stop_speaking', { clearPending, reason });
  window.agentOutputAwaitingSpeechCompletion = false;
  _streamTtsStopped = true;
  _streamTtsQueue = [];

  // 停止所有正在播放或排程中的串流來源
  if (_ttsActiveSources && _ttsActiveSources.length > 0) {
    _ttsActiveSources.forEach(source => {
      try { source.stop(); } catch (_) {}
    });
    _ttsActiveSources = [];
  }

  if (ttsStreamSocket) {
    try { ttsStreamSocket.close(); } catch (_) {}
    ttsStreamSocket = null;
  }
  ttsStreamNextStartAt = 0;

  if (currentAudio) {
    currentAudio.pause();
    currentAudio.currentTime = 0;
    currentAudio = null;
  }
  isPlaying = false;

  if (clearPending && pendingAudioUrl) {
    const urlToRevoke = pendingAudioUrl;
    setTimeout(() => URL.revokeObjectURL(urlToRevoke), 1000);
    pendingAudioUrl = null;
  }
}

installAudioUnlockListeners();
