// ========== 打字機效果函數 ==========

/**
 * 異步打字機效果（文字與語音並行）
 * 立即開始語音播放，同時顯示打字效果
 * 
 * @param {string} text - 要顯示的完整文字
 * @param {number} speed - 打字速度（毫秒/字元）
 * @param {boolean} enableTTS - 是否啟用語音播放
 */
function typewriterEffect(text, speed = 50, enableTTS = true) {
  agentOutput.textContent = '';
  agentOutput.classList.add('active');
  agentOutput.classList.remove('typing-done');

  let index = 0;

  // 清除之前的打字動畫
  if (typingInterval) {
    clearInterval(typingInterval);
  }

  // 立即開始語音播放（異步並行，不等待打字完成）
  if (enableTTS && typeof speakText === 'function') {
    speakText(text);  // 語音與打字效果並行
  }

  // 打字效果
  typingInterval = setInterval(() => {
    if (index < text.length) {
      agentOutput.textContent += text[index];
      index++;
    } else {
      clearInterval(typingInterval);
      agentOutput.classList.add('typing-done'); // 打字完成，隱藏游標
    }
  }, speed);
}


function hideAgentOutput() {
  if (typingInterval) {
    clearInterval(typingInterval);
  }
  agentOutput.classList.remove('active');
  agentOutput.textContent = '';
}

// ========== 情緒切換 ==========

function initEmotionSelector() {
  document.getElementById('emotion-select').addEventListener('change', (e) => {
    const emotion = e.target.value;
    background.className = `voice-immersive-background emotion-${emotion} active`;
    emotionIndicator.textContent = `當前情緒: ${emotionEmojis[emotion]}`;
  });
}

// ========== 字幕切換 ==========

function initTranscriptControls() {
  document.getElementById('transcript-provisional').addEventListener('click', () => {
    transcript.textContent = '今天天氣怎麼樣';
    transcript.className = 'voice-transcript provisional';
  });

  document.getElementById('transcript-final').addEventListener('click', () => {
    transcript.textContent = '今天天氣怎麼樣？';
    transcript.className = 'voice-transcript final';
  });
}

// ========== 登入按鈕 ==========

function initLoginButton() {
  const googleLoginBtn = document.getElementById('googleLoginBtn');
  if (googleLoginBtn) {
    googleLoginBtn.addEventListener('click', handleGoogleLogin);
  }
}

// ========== 登出按鈕 ==========

function initExitButton() {
  const exitButton = document.querySelector('.exit-button');
  if (exitButton) {
    exitButton.addEventListener('click', handleLogout);
  }
}

async function handleLogout() {
  console.log('🚪 開始登出流程...');

  try {
    // 可選：呼叫後端登出 API（主要由前端清除 token）
    await fetch('/auth/logout', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      }
    });
  } catch (error) {
    console.warn('⚠️ 後端登出失敗（忽略）:', error);
  }

  // 清除本地儲存的 token
  localStorage.removeItem('jwt_token');
  sessionStorage.clear();

  console.log('✅ 登出成功，跳轉至登入頁面...');

  // 跳轉到登入頁面
  window.location.href = '/static/login.html';
}

// ========== 模式切換（語音 ↔ 文字輸入）==========

let isTextInputMode = false;  // 當前是否為文字輸入模式

/**
 * 切換語音模式與文字輸入模式
 */
function toggleInputMode() {
  isTextInputMode = !isTextInputMode;
  
  const modeToggleBtn = document.getElementById('modeToggleBtn');
  const transcript = document.getElementById('transcript');
  const micContainer = document.getElementById('mic-container');
  
  if (isTextInputMode) {
    // === 切換到文字輸入模式 ===
    console.log('🔤 切換到文字輸入模式');
    
    // 停止語音錄音（如果正在錄音）
    if (currentState === 'recording') {
      console.log('⏹️ 停止語音錄音');
      if (typeof stopRealAudioAnalysis === 'function') {
        stopRealAudioAnalysis();
      }
      if (wsManager && typeof wsManager.stopRecording === 'function') {
        wsManager.stopRecording();
      }
      setState('idle');
    }
    
    // 禁用麥克風點擊，並讓麥克風容器變淡（但不影響波形）
    micContainer.style.pointerEvents = 'none';
    // 不要設置整體透明度，讓波形保持可見
    // micContainer.style.opacity = '0.3';
    
    // 添加文字輸入模式標記到body
    document.body.classList.add('text-input-active');
    
    // 啟用文字輸入
    transcript.contentEditable = 'true';
    transcript.classList.add('text-input-mode');
    transcript.classList.remove('provisional', 'final');
    transcript.textContent = '';
    transcript.setAttribute('data-placeholder', '請輸入文字...');
    transcript.focus();
    
    // 更新按鈕樣式
    modeToggleBtn.classList.add('text-mode');
    modeToggleBtn.textContent = '🎤';
    modeToggleBtn.title = '切換為語音模式';
    
    // 監聽 Enter 鍵發送訊息
    transcript.addEventListener('keydown', handleTextInput);
    
  } else {
    // === 切換到語音模式 ===
    console.log('🎙️ 切換到語音模式');
    
    // 移除文字輸入模式標記
    document.body.classList.remove('text-input-active');
    
    // 停用文字輸入
    transcript.contentEditable = 'false';
    transcript.classList.remove('text-input-mode');
    transcript.classList.add('provisional');
    transcript.textContent = '請說話...';
    transcript.removeAttribute('data-placeholder');
    
    // 啟用麥克風
    micContainer.style.pointerEvents = 'auto';
    micContainer.style.opacity = '1';
    
    // 更新按鈕樣式
    modeToggleBtn.classList.remove('text-mode');
    modeToggleBtn.textContent = '💬';
    modeToggleBtn.title = '切換為文字輸入模式';
    
    // 移除文字輸入監聽
    transcript.removeEventListener('keydown', handleTextInput);
  }
}

/**
 * 處理文字輸入（Enter 發送訊息）
 */
function handleTextInput(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();

    const transcript = document.getElementById('transcript');
    const message = transcript.textContent.trim();

    if (!message) {
      console.warn('⚠️ 訊息內容為空');
      return;
    }

    console.log('📤 發送文字訊息:', message);

    // 顯示為 final 狀態（讓用戶看到已發送）
    transcript.classList.remove('provisional');
    transcript.classList.add('final');

    // 發送訊息到 WebSocket
    if (wsManager && wsManager.isConnected()) {
      // 獲取當前 chat_id（從全域變數）
      const chatId = window.currentChatId;

      if (!chatId) {
        console.warn('⚠️ 當前沒有 chat_id，後端將自動創建新對話');
      }

      wsManager.sendUserMessage(message, chatId);

      // 文字輸入模式下也顯示思考狀態（花瓣綻放）
      setState('thinking');

      // 清空輸入框（延遲一下讓用戶看到發送的訊息）
      setTimeout(() => {
        transcript.textContent = '思考中...';
        transcript.classList.remove('final');
        transcript.classList.add('provisional');
      }, 300);
    } else {
      console.error('❌ WebSocket 未連接，無法發送訊息');
      alert('連線已斷開，請重新整理頁面');
    }
  } else if (event.key === 'Enter' && event.shiftKey) {
    // Shift+Enter 換行（contenteditable 預設行為）
    // 不需要特別處理
  }
}

/**
 * 初始化模式切換按鈕
 */
function initModeToggle() {
  const modeToggleBtn = document.getElementById('modeToggleBtn');
  if (modeToggleBtn) {
    modeToggleBtn.addEventListener('click', toggleInputMode);
    console.log('✅ 模式切換按鈕已初始化');
  }
}
