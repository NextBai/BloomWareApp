
function typewriterEffect(text, speed = 50, enableTTS = true) {
  agentOutput.textContent = '';
  agentOutput.classList.add('active');
  agentOutput.classList.remove('typing-done');

  let index = 0;

  if (typingInterval) {
    clearInterval(typingInterval);
  }

  if (enableTTS && typeof speakText === 'function') {
    speakText(text);  // 語音與打字效果並行
  }

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


function initEmotionSelector() {
  document.getElementById('emotion-select').addEventListener('change', (e) => {
    const emotion = e.target.value;
    background.className = `voice-immersive-background emotion-${emotion} active`;
    emotionIndicator.textContent = `當前情緒: ${emotionEmojis[emotion]}`;
  });
}


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


function initLoginButton() {
  const googleLoginBtn = document.getElementById('googleLoginBtn');
  if (googleLoginBtn) {
    googleLoginBtn.addEventListener('click', handleGoogleLogin);
  }
}


function initLogoutButton() {
  const logoutBtn = document.getElementById('logoutBtn');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', handleLogout);
  }
}

function handleLogout() {

  localStorage.removeItem('jwt_token');

  if (typeof ws !== 'undefined' && ws) {
    ws.close();
  }

  if (typeof stopSpeaking === 'function') {
    stopSpeaking();
  }


  window.location.href = '/login/';
}


let isTextInputMode = false; // 當前是否為文字輸入模式
let textInputElement = null; // 文字輸入框元素

function initChatIcon() {
  const chatIcon = document.getElementById('chatIcon');
  if (chatIcon) {
    chatIcon.addEventListener('click', toggleInputMode);
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

    const originalContent = transcript.textContent;

    transcript.className = 'voice-transcript text-input-mode';
    transcript.innerHTML = '';

    textInputElement = document.createElement('textarea');
    textInputElement.placeholder = '請輸入訊息...';
    textInputElement.id = 'text-input-box';

    textInputElement.addEventListener('keydown', handleTextInput);

    transcript.appendChild(textInputElement);

    setTimeout(() => textInputElement.focus(), 100);

  } else {

    if (textInputElement) {
      textInputElement.removeEventListener('keydown', handleTextInput);
      textInputElement = null;
    }

    transcript.className = 'voice-transcript provisional';
    transcript.textContent = '請說話...';
  }
}

function handleTextInput(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();

    const text = textInputElement.value.trim();
    if (!text) {
      console.warn('⚠️ 訊息為空，不送出');
      return;
    }


    if (typeof wsManager !== 'undefined' && wsManager) {
      const chatId = window.currentChatId || null;
      wsManager.sendUserMessage(text, chatId);

      textInputElement.value = '';

      if (typeof setState === 'function') {
        setState('thinking');
      }

      toggleInputMode();
    } else {
      console.error('❌ WebSocket 未初始化');
    }
  }
}
