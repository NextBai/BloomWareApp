let currentState = 'idle';

function setState(newState, options = {}) {
  if (currentState === newState) {
    return;
  }

  const oldState = currentState;
  currentState = newState;

  micContainer.classList.remove('recording', 'thinking', 'speaking', 'disconnected');

  switch(newState) {
    case 'idle':
      hideAgentOutput();
      if (typeof stopSpeaking === 'function') {
        stopSpeaking();
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
        stopSpeaking();
      }
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
        stopSpeaking();
      }
      clearAllCards();
      break;

    default:
      console.error(`❌ 未知狀態: ${newState}`);
  }
}

function applyEmotion(emotion) {
  const validEmotions = ['neutral', 'happy', 'sad', 'angry', 'fear', 'surprise'];
  if (!validEmotions.includes(emotion)) {
    emotion = 'neutral';
  }

  background.className = `voice-immersive-background emotion-${emotion} active`;
  emotionIndicator.textContent = `當前情緒: ${emotionEmojis[emotion]}`;
}

function showErrorNotification(message) {
  console.error('🚨 錯誤:', message);

  setState('speaking', {
    outputText: `抱歉，發生錯誤：${message}`,
    enableTTS: false
  });

  setTimeout(() => setState('idle'), 3000);
}


let isThinking = false;
let isDisconnected = false;
let isRecording = false;
let isSpeaking = false;

function initAgentControls() {
  micContainer.addEventListener('click', async () => {
    
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
        stopSpeaking();
      }
      
      isRecording = true;
      setState('recording', {
        keepOutput: true,  // 保留前次 Agent 回應
        keepCards: true    // 保留前次工具卡片
      });
      
      if (typeof startRealAudioAnalysis === 'function') {
        await startRealAudioAnalysis();
      }
      
      if (wsManager && typeof wsManager.startRecording === 'function') {
        const success = await wsManager.startRecording();
        if (!success) {
          console.error('❌ 錄音啟動失敗');
          setState('idle');
          isRecording = false;
          if (typeof stopRealAudioAnalysis === 'function') {
            stopRealAudioAnalysis();
          }
        }
      } else {
        console.error('❌ WebSocket 管理器未初始化');
        setState('idle');
        isRecording = false;
        if (typeof stopRealAudioAnalysis === 'function') {
          stopRealAudioAnalysis();
        }
      }
    }
  });

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
