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

function initLogoutButton() {
  const logoutBtn = document.getElementById('logoutBtn');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', handleLogout);
    console.log('✅ 登出按鈕已初始化');
  }
}

function handleLogout() {
  console.log('🚪 執行登出...');

  // 清除 JWT token
  localStorage.removeItem('jwt_token');

  // 停止 WebSocket 連接
  if (typeof ws !== 'undefined' && ws) {
    ws.close();
  }

  // 停止語音播放
  if (typeof stopSpeaking === 'function') {
    stopSpeaking();
  }

  console.log('✅ 登出成功，導向登入頁面');

  // 導向登入頁面
  window.location.href = '/login/';
}

// ========== 輸入模式切換（語音 ↔ 文字）==========

let isTextInputMode = false; // 當前是否為文字輸入模式
let textInputElement = null; // 文字輸入框元素

function initChatIcon() {
  const chatIcon = document.getElementById('chatIcon');
  if (chatIcon) {
    chatIcon.addEventListener('click', toggleInputMode);
    console.log('✅ 輸入模式切換按鈕已初始化');
  }
}

function toggleInputMode() {
  isTextInputMode = !isTextInputMode;
  const transcript = document.getElementById('transcript');

  if (!transcript) {
    console.error('❌ 找不到 transcript 元素');
    return;
  }

  if (isTextInputMode) {
    // 切換到文字輸入模式
    console.log('⌨️ 切換到文字輸入模式');

    // 保存原始內容
    const originalContent = transcript.textContent;

    // 清空並添加 text-input-mode class
    transcript.className = 'voice-transcript text-input-mode';
    transcript.innerHTML = '';

    // 創建 textarea
    textInputElement = document.createElement('textarea');
    textInputElement.placeholder = '請輸入訊息...';
    textInputElement.id = 'text-input-box';

    // 監聽 Enter 鍵送出（Shift+Enter 換行）
    textInputElement.addEventListener('keydown', handleTextInput);

    transcript.appendChild(textInputElement);

    // 自動聚焦
    setTimeout(() => textInputElement.focus(), 100);

  } else {
    // 切換回語音模式
    console.log('🎤 切換到語音模式');

    // 移除 textarea
    if (textInputElement) {
      textInputElement.removeEventListener('keydown', handleTextInput);
      textInputElement = null;
    }

    // 恢復原始樣式
    transcript.className = 'voice-transcript provisional';
    transcript.textContent = '請說話...';
  }
}

function handleTextInput(event) {
  // Enter 送出（Shift+Enter 換行）
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();

    const text = textInputElement.value.trim();
    if (!text) {
      console.warn('⚠️ 訊息為空，不送出');
      return;
    }

    console.log('📤 送出文字訊息:', text);

    // 送出到 WebSocket
    if (typeof wsManager !== 'undefined' && wsManager) {
      // 取得當前對話 ID（如果沒有，後端會自動建立新對話）
      const chatId = window.currentChatId || null;
      wsManager.sendUserMessage(text, chatId);

      // 清空輸入框
      textInputElement.value = '';

      // 切換到思考狀態
      if (typeof setState === 'function') {
        setState('thinking');
      }

      // 切換回語音模式
      toggleInputMode();
    } else {
      console.error('❌ WebSocket 未初始化');
    }
  }
}
