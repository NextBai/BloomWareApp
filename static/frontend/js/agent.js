// ========== Agent 狀態管理（單一狀態機）==========
// 狀態定義：idle | recording | thinking | speaking | disconnected
let currentState = 'idle';

/**
 * 狀態轉換函數
 * @param {string} newState - 新狀態 (idle | recording | thinking | speaking | disconnected)
 * @param {object} options - 選項 {clearCards, showOutput, outputText, enableTTS}
 */
function setState(newState, options = {}) {
  // 防止重複設置相同狀態
  if (currentState === newState) {
    console.log(`⚠️ 狀態已經是 ${newState}，忽略`);
    return;
  }

  const oldState = currentState;
  currentState = newState;
  console.log(`🔄 狀態轉換: ${oldState} → ${newState}`);

  // 移除所有狀態 class
  micContainer.classList.remove('recording', 'thinking', 'speaking', 'disconnected');

  // 套用新狀態
  switch(newState) {
    case 'idle':
      // 閒置狀態：清除所有動畫
      hideAgentOutput();
      if (typeof stopSpeaking === 'function') {
        stopSpeaking();
      }
      if (options.clearCards !== false) {
        clearAllCards();
      }
      break;

    case 'recording':
      // 錄音狀態：紅色脈動核心
      micContainer.classList.add('recording');
      // 不清除 Agent 輸出,保留前次回應
      if (!options.keepOutput) {
        hideAgentOutput();
      }
      // 不清除工具卡片,保留前次結果
      if (!options.keepCards) {
        clearAllCards();
      }
      // 清除舊的 transcript,顯示錄音提示
      transcript.textContent = '聆聽中...';
      transcript.className = 'voice-transcript provisional';
      break;

    case 'thinking':
      // 思考中狀態：花瓣順時針綻放
      micContainer.classList.add('thinking');
      hideAgentOutput();
      if (typeof stopSpeaking === 'function') {
        stopSpeaking();
      }
      break;

    case 'speaking':
      // 回覆中狀態：完全綻放 + 打字機效果
      micContainer.classList.add('speaking');
      if (options.outputText) {
        // typewriterEffect 內部會自動調用 speakText（如果 enableTTS 為 true）
        typewriterEffect(options.outputText, 40, options.enableTTS);
      }
      break;

    case 'disconnected':
      // 斷線狀態：花瓣逆時針變紅
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

/**
 * 應用情緒主題
 */
function applyEmotion(emotion) {
  const validEmotions = ['neutral', 'happy', 'sad', 'angry', 'fear', 'surprise'];
  if (!validEmotions.includes(emotion)) {
    emotion = 'neutral';
  }

  background.className = `voice-immersive-background emotion-${emotion} active`;
  emotionIndicator.textContent = `當前情緒: ${emotionEmojis[emotion]}`;
}

/**
 * 顯示錯誤通知
 */
function showErrorNotification(message) {
  // 簡單的錯誤提示（可以改為更友善的 UI）
  console.error('🚨 錯誤:', message);

  // 使用打字機效果顯示錯誤
  setState('speaking', {
    outputText: `抱歉，發生錯誤：${message}`,
    enableTTS: false
  });

  setTimeout(() => setState('idle'), 3000);
}

// ========== 測試按鈕事件監聽器 ==========

// 舊變數保留（向後兼容）
let isThinking = false;
let isDisconnected = false;
let isRecording = false;
let isSpeaking = false;

function initAgentControls() {
  // === 真實的麥克風點擊事件（非測試按鈕）=== 
  micContainer.addEventListener('click', async () => {
    console.log('🎤 用戶點擊麥克風，當前狀態:', currentState);
    
    // 如果正在錄音，停止錄音
    if (currentState === 'recording') {
      console.log('⏹️ 停止錄音');
      isRecording = false;
      
      // 停止視覺化
      if (typeof stopRealAudioAnalysis === 'function') {
        stopRealAudioAnalysis();
      }
      
      // 停止 WebSocket 錄音
      if (wsManager && typeof wsManager.stopRecording === 'function') {
        wsManager.stopRecording();
      }
      
      // 轉換為思考狀態（等待 STT 和 Agent 回應）
      setState('thinking');
      return;
    }
    
    // 開始錄音狀態（不清除之前的回應，保留顯示）
    if (currentState === 'idle' || currentState === 'disconnected' || currentState === 'speaking') {
      // 如果在 speaking 狀態，先停止 TTS 播放
      if (currentState === 'speaking' && typeof stopSpeaking === 'function') {
        stopSpeaking();
      }
      
      isRecording = true;
      setState('recording', {
        keepOutput: true,  // 保留前次 Agent 回應
        keepCards: true    // 保留前次工具卡片
      });
      console.log('🎙️ 開始錄音（保留前次回應顯示）');
      
      // 啟動視覺化
      if (typeof startRealAudioAnalysis === 'function') {
        await startRealAudioAnalysis();
      }
      
      // 啟動 WebSocket 錄音（實際傳輸音訊數據）
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

  // 錄音狀態（改用狀態機 + 真實音訊分析）
  document.getElementById('toggle-recording').addEventListener('click', async () => {
    isRecording = !isRecording;
    if (isRecording) {
      setState('recording');
      // 啟動真實音訊分析
      await startRealAudioAnalysis();
    } else {
      setState('idle');
      // 停止真實音訊分析
      stopRealAudioAnalysis();
    }
  });

  // 思考中狀態（改用狀態機）
  document.getElementById('toggle-thinking').addEventListener('click', () => {
    isThinking = !isThinking;
    if (isThinking) {
      setState('thinking');
    } else {
      setState('idle', {clearCards: false}); // 保留工具卡片
    }
  });

  // 回覆中狀態（改用狀態機）
  document.getElementById('toggle-speaking').addEventListener('click', () => {
    isSpeaking = !isSpeaking;
    if (isSpeaking) {
      // 回覆開始：顯示工具卡片
      clearAllCards();
      setTimeout(() => addToolCard('weather'), 300);

      // 模擬 Agent 回覆文字
      const responseText = '根據目前的天氣資料，台北今天氣溫約 23°C，天氣晴朗，濕度 65%。建議您外出時可以穿著輕便舒適的衣物，並記得攜帶太陽眼鏡。';
      setState('speaking', {outputText: responseText});
    } else {
      setState('idle', {clearCards: false}); // 保留工具卡片
    }
  });

  // 斷線狀態（改用狀態機）
  document.getElementById('toggle-disconnected').addEventListener('click', () => {
    isDisconnected = !isDisconnected;
    if (isDisconnected) {
      setState('disconnected');
    } else {
      setState('idle');
    }
  });
}
