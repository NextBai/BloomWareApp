window.currentState = 'idle';
window.thinkingTimeout = null;
window.stateBufferTimeout = null;

/**
 * 設置 Agent 狀態，加入緩衝機制防止動畫閃爍
 */
function setState(newState, options = {}) {
  if (window.currentState === newState && !window.stateBufferTimeout) {
    return;
  }

  // 如果有待處理的狀態轉換，先清除它
  if (window.stateBufferTimeout) {
    clearTimeout(window.stateBufferTimeout);
    window.stateBufferTimeout = null;
  }

  // 針對進入 idle 狀態加入微小延遲，避免在快速切換（如 speaking -> idle -> recording）時花瓣動畫跳轉
  if (newState === 'idle') {
    window.stateBufferTimeout = setTimeout(() => {
      window.stateBufferTimeout = null;
      applyStateChange('idle', options);
    }, 150);
  } else {
    applyStateChange(newState, options);
  }
}

/**
 * 實際執行狀態變更與 UI 更新
 */
function applyStateChange(newState, options) {
  const oldState = window.currentState;
  window.currentState = newState;
  console.log(`🔄 狀態切換: ${oldState} -> ${newState}`);

  // 清除之前的思考超時計時器
  if (window.thinkingTimeout) {
    clearTimeout(window.thinkingTimeout);
    window.thinkingTimeout = null;
  }

  // 更新麥克風容器樣式
  micContainer.classList.remove('recording', 'thinking', 'speaking', 'disconnected');

  switch(newState) {
    case 'idle':
      // idle 狀態不應主動隱藏輸出，讓使用者能看清最後的回覆
      if (typeof stopSpeaking === 'function') {
        stopSpeaking(true, 'state_idle');
      }
      if (options.clearCards !== false) {
        clearAllCards();
      }
      break;

    case 'recording':
      micContainer.classList.add('recording');
      if (!options.keepOutput) {
        hideAgentOutput();
      }
      if (!options.keepCards) {
        clearAllCards();
      }
      transcript.textContent = '聆聽中...';
      transcript.className = 'voice-transcript provisional';
      break;

    case 'thinking':
      micContainer.classList.add('thinking');
      hideAgentOutput();
      if (typeof stopSpeaking === 'function') {
        stopSpeaking(true, 'state_thinking');
      }
      
      // 設定思考超時重置 (45秒)
      window.thinkingTimeout = setTimeout(() => {
        if (window.currentState === 'thinking') {
          console.warn('⚠️ 思考時間過長，自動重置');
          showErrorNotification('抱歉，處理時間過長，請再試一次。');
          resetAgent({clearCards: false});
        }
      }, 45000);
      break;

    case 'speaking':
      micContainer.classList.add('speaking');
      if (options.outputText) {
        typewriterEffect(options.outputText, 40, options.enableTTS);
      }
      break;

    case 'disconnected':
      micContainer.classList.add('disconnected');
      hideAgentOutput();
      if (typeof stopSpeaking === 'function') {
        stopSpeaking(true, 'state_disconnected');
      }
      clearAllCards();
      break;

    default:
      console.error(`❌ 未知狀態: ${newState}`);
  }
}

window.currentEmotion = 'neutral';
window.isInCareMode = false;

function applyEmotion(emotion, careMode = null) {
    if (careMode !== null) {
        window.isInCareMode = !!careMode;
    }
  const validEmotions = ['neutral', 'happy', 'sad', 'angry', 'fear', 'surprise'];
  
  // 🎯 支援多語言/原始標籤映射，確保 100% 信心
  const mapping = {
    '悲傷(sad)': 'sad', '悲傷': 'sad',
    '開心(happy)': 'happy', '開心': 'happy',
    '生氣(angry)': 'angry', '生氣': 'angry',
    '恐懼(fear)': 'fear', '恐懼': 'fear',
    '驚訝(surprise)': 'surprise', '驚訝': 'surprise',
    '中性(neutral)': 'neutral', '中性': 'neutral'
  };
  
  if (mapping[emotion]) {
    emotion = mapping[emotion];
  }

  if (!validEmotions.includes(emotion)) {
    emotion = 'neutral';
  }

  background.className = `voice-immersive-background emotion-${emotion} active`;
  emotionIndicator.textContent = `當前情緒: ${emotionEmojis[emotion]}`;
  
  // 🎯 保存到全域狀態，供 TTS 使用
  window.currentEmotion = emotion;
}

function showErrorNotification(message) {
  console.error('🚨 錯誤:', message);

  // 立即重置 Agent 狀態（關閉花朵，停止錄音/語音）
  resetAgent({ clearCards: false });

  // 顯示錯誤訊息於輸出區域，但不切換到 speaking 狀態（讓花朵保持 idle）
  if (typeof typewriterEffect === 'function') {
    typewriterEffect(`抱歉，發生錯誤：${message}`, 40, false);
  }
  
  // 3秒後自動隱藏錯誤訊息
  setTimeout(() => {
    if (currentState === 'idle') {
      hideAgentOutput();
    }
  }, 5000);
}


let isThinking = false;
let isDisconnected = false;
let isRecording = false;
let isSpeaking = false;

function resetAgent(options = {}) {
  isRecording = false;
  isThinking = false;
  isSpeaking = false;
  isDisconnected = false;
  
  if (typeof stopSpeaking === 'function') {
    stopSpeaking(true, 'reset_agent');
  }
  
  if (typeof stopRealAudioAnalysis === 'function') {
    stopRealAudioAnalysis();
  }
  
  if (wsManager && typeof wsManager.stopRecording === 'function') {
    wsManager.stopRecording();
  }
  
  if (typeof transcript !== 'undefined' && transcript) {
    transcript.textContent = '';
  }
  
  setState('idle', options);
}

function initAgentControls() {
  const handleMicInteraction = async () => {
    if (currentState === 'recording') {
      isRecording = false;
      
      if (typeof stopRealAudioAnalysis === 'function') {
        stopRealAudioAnalysis();
      }
      
      if (wsManager && typeof wsManager.stopRecording === 'function') {
        wsManager.stopRecording();
      }
      
      setState('thinking');
      return;
    }
    
    if (currentState === 'idle' || currentState === 'disconnected' || currentState === 'speaking') {
      if (currentState === 'speaking' && typeof stopSpeaking === 'function') {
        stopSpeaking(true, 'mic_interrupt');
      }
      
      isRecording = true;
      setState('recording', {
        keepOutput: true,  // 保留前次 Agent 回應
        keepCards: true,   // 保留前次工具卡片
        detect_timeout: 20.0,   // 考量到 Function Calling 可能較慢
        feature_timeout: 30.0,  // MCP 工具內部超時
        ai_timeout: 25.0       // 配合 Streaming
      });
      
      if (typeof startRealAudioAnalysis === 'function') {
        await startRealAudioAnalysis();
      }
      
      if (wsManager && typeof wsManager.startRecording === 'function') {
        const success = await wsManager.startRecording();
        if (!success) {
          console.error('❌ 錄音啟動失敗');
          resetAgent();
        }
      } else {
        console.error('❌ WebSocket 管理器未初始化');
        resetAgent();
      }
    }
  };

  // 點擊麥克風中心
  micContainer.addEventListener('click', handleMicInteraction);
  
  // 點擊波形容器（較大區域）也觸發交互，提高可用性
  const waveformContainer = document.querySelector('.voice-waveform-container');
  if (waveformContainer) {
    waveformContainer.style.cursor = 'pointer';
    waveformContainer.addEventListener('click', (e) => {
      // 如果點擊的是 micContainer 內部，就不重複觸發（事件冒泡）
      if (e.target === micContainer || micContainer.contains(e.target)) {
        return;
      }
      handleMicInteraction();
    });
  }

  document.getElementById('toggle-recording').addEventListener('click', async () => {
    isRecording = !isRecording;
    if (isRecording) {
      setState('recording');
      await startRealAudioAnalysis();
    } else {
      setState('idle');
      stopRealAudioAnalysis();
    }
  });

  document.getElementById('toggle-thinking').addEventListener('click', () => {
    isThinking = !isThinking;
    if (isThinking) {
      setState('thinking');
    } else {
      setState('idle', {clearCards: false}); // 保留工具卡片
    }
  });

  document.getElementById('toggle-speaking').addEventListener('click', () => {
    isSpeaking = !isSpeaking;
    if (isSpeaking) {
      clearAllCards();
      setTimeout(() => addToolCard('weather'), 300);

      const responseText = '根據目前的天氣資料，台北今天氣溫約 23°C，天氣晴朗，濕度 65%。建議您外出時可以穿著輕便舒適的衣物，並記得攜帶太陽眼鏡。';
      setState('speaking', {outputText: responseText});
    } else {
      setState('idle', {clearCards: false}); // 保留工具卡片
    }
  });

  document.getElementById('toggle-disconnected').addEventListener('click', () => {
    isDisconnected = !isDisconnected;
    if (isDisconnected) {
      setState('disconnected');
    } else {
      setState('idle');
    }
  });
}
