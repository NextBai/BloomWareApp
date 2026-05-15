let typewriterTextNode = null;
let lastRenderedAgentText = '';
let typewriterFrameId = null;
window.agentOutputAwaitingSpeechCompletion = false;
window.agentOutputHasAnswerStream = false;
window.typewriterState = {
  text: '',
  position: 0,
  isActive: false,
  frameId: null
};

/**
 * 取消當前的打字機動畫
 */
function cancelTypewriterAnimation() {
  if (window.typewriterState.frameId) {
    cancelAnimationFrame(window.typewriterState.frameId);
    window.typewriterState.frameId = null;
  }
  typewriterFrameId = null;
  window.typewriterState.isActive = false;
}

function setTypewriterContent(text) {
  const nextText = String(text || '');
  if (lastRenderedAgentText === nextText) {
    return;
  }
  lastRenderedAgentText = nextText;
  renderAgentMarkdown(nextText);
}



function typewriterEffect(text, speed = 40, enableTTS = true, options = {}) {
  const sourceText = String(text || '').trim();
  
  // 如果新文字是舊文字的延續，且正在打字中，我們不重頭開始，而是更新目標
  if (window.typewriterState.isActive && sourceText.startsWith(window.typewriterState.text)) {
    window.typewriterState.text = sourceText;
    return;
  }

  cancelTypewriterAnimation();
  
  window.typewriterState = {
    text: sourceText,
    position: 0,
    isActive: true,
    frameId: null
  };
  const awaitSpeechCompletion = options.awaitSpeechCompletion === true || !!enableTTS;
  window.agentOutputAwaitingSpeechCompletion = awaitSpeechCompletion;

  setAgentOutputMode('final');
  if (!agentOutput.dataset.temporary) {
    agentOutput.dataset.temporary = 'false';
  }
  agentOutput.classList.add('active');
  agentOutput.classList.add('typing-active');
  agentOutput.classList.remove('typing-done');

  if (enableTTS && typeof speakText === 'function') {
    speakText(sourceText);
  }

  setState('speaking');

  const charsPerMs = speed > 0 ? 1 / speed : 2;
  let startTime = null;

  function step(timestamp) {
    if (startTime === null) startTime = timestamp;
    const elapsed = timestamp - startTime;
    
    // 計算理論上應該打到哪裡
    let nextPos = Math.floor(elapsed * charsPerMs);
    
    // 如果落後目標太多，僅進行溫和追趕，避免瞬間跳轉
    const lag = window.typewriterState.text.length - nextPos;
    if (lag > 20) {
      // 每幀額外追趕一些字元，而不是直接跳到底
      startTime -= (lag * 0.3) * (1 / charsPerMs); 
      nextPos = Math.floor((timestamp - startTime) * charsPerMs);
    }

    window.typewriterState.position = Math.min(window.typewriterState.text.length, nextPos);
    
    setTypewriterContent(window.typewriterState.text.slice(0, window.typewriterState.position));
    agentOutput.scrollTop = agentOutput.scrollHeight;

    if (window.typewriterState.position < window.typewriterState.text.length) {
      window.typewriterState.frameId = requestAnimationFrame(step);
      typewriterFrameId = window.typewriterState.frameId;
      return;
    }

    // 結束打字
    completeTypewriter();
  }

  window.typewriterState.frameId = requestAnimationFrame(step);
  typewriterFrameId = window.typewriterState.frameId;
}

function completeTypewriter() {
  window.typewriterState.isActive = false;
  window.typewriterState.frameId = null;
  typewriterFrameId = null;
  agentOutput.classList.remove('typing-active');
  agentOutput.classList.add('typing-done');
  setTypewriterContent(window.typewriterState.text);
  agentOutput.scrollTop = agentOutput.scrollHeight;

  if (agentOutput.dataset.temporary === 'true') {
    return;
  }

  if (typeof hasPendingStreamingSpeech === 'function' && hasPendingStreamingSpeech()) {
    window.agentOutputAwaitingSpeechCompletion = true;
    return;
  }

  if (window.agentOutputAwaitingSpeechCompletion) {
    return;
  }

  setState('idle', {clearCards: false});
}



const agentProgressSteps = [];

function renderAgentProgressStep(text) {
  const safeText = text || '正在處理...';
  const nextIndex = agentProgressSteps.length + 1;
  agentProgressSteps.push(safeText);
  if (agentProgressSteps.length > 4) {
    agentProgressSteps.shift();
  }
  const rows = agentProgressSteps.map((step, index) => {
    const isLatest = index === agentProgressSteps.length - 1;
    const className = isLatest ? 'agent-progress-row current' : 'agent-progress-row';
    return `<div class="${className}"><span class="agent-progress-dot" aria-hidden="true"></span><span>${escapeHtml(step)}</span></div>`;
  });
  return `<div class="agent-progress-stack">${rows.join('')}</div>`;
}

function setAgentOutputMode(mode) {
  agentOutput.classList.remove('progress-mode', 'output-mode-processing', 'output-mode-streaming', 'output-mode-final');
  if (mode === 'processing') {
    agentOutput.classList.add('progress-mode', 'output-mode-processing');
  } else if (mode === 'streaming') {
    agentOutput.classList.add('output-mode-streaming');
  } else if (mode === 'final') {
    agentOutput.classList.add('output-mode-final');
  }
}

function setAgentOutputContent(html) {
  let shell = agentOutput.querySelector('.agent-output-shell');
  if (!shell) {
    agentOutput.innerHTML = '<div class="agent-output-shell"><div class="agent-output-content"></div></div>';
    shell = agentOutput.querySelector('.agent-output-shell');
  }
  const contentNode = shell.querySelector('.agent-output-content');
  
  // 在打字機模式下，我們加上一個光標元素
  const isTyping = agentOutput.classList.contains('typing-active');
  const cursorHtml = isTyping ? '<span class="typing-cursor"></span>' : '';
  
  contentNode.innerHTML = html + cursorHtml;
  typewriterTextNode = null;
  agentOutput.scrollTop = agentOutput.scrollHeight;
}

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function renderInlineMarkdown(text) {
  return escapeHtml(text)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/__([^_]+)__/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')
    .replace(/_([^_]+)_/g, '<em>$1</em>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
    .replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>');
}

function renderAgentMarkdown(markdown) {
  const text = String(markdown || '').replace(/\r\n/g, '\n');
  const blocks = [];
  const codePattern = /```([\s\S]*?)```/g;
  let cursor = 0;
  let match;

  while ((match = codePattern.exec(text)) !== null) {
    blocks.push({type: 'markdown', value: text.slice(cursor, match.index)});
    blocks.push({type: 'code', value: match[1].replace(/^\w+\n/, '')});
    cursor = match.index + match[0].length;
  }
  blocks.push({type: 'markdown', value: text.slice(cursor)});

  const rendered = blocks.map(block => {
    if (block.type === 'code') {
      return `<pre><code>${escapeHtml(block.value.trim())}</code></pre>`;
    }
    return renderMarkdownBlock(block.value);
  }).join('');
  setAgentOutputContent(rendered);
}

function renderMarkdownBlock(value) {
  const lines = String(value || '').split('\n');
  const html = [];
  let listItems = [];

  function flushList() {
    if (!listItems.length) return;
    html.push(`<ul>${listItems.map(item => `<li>${renderInlineMarkdown(item)}</li>`).join('')}</ul>`);
    listItems = [];
  }

  lines.forEach(line => {
    const trimmed = line.trim();
    if (!trimmed) {
      flushList();
      return;
    }
    const heading = trimmed.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      flushList();
      const level = heading[1].length;
      html.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`);
      return;
    }
    const bullet = trimmed.match(/^([-*]|\d+\.)\s+(.+)$/);
    if (bullet) {
      listItems.push(bullet[2]);
      return;
    }
    flushList();
    html.push(`<p>${renderInlineMarkdown(trimmed)}</p>`);
  });
  flushList();
  return html.join('');
}

function editAgentOutput(text, temporary = false, options = {}) {
  const nextText = String(text || '').trim();
  
  if (temporary) {
    if (options.progress === true && window.agentOutputHasAnswerStream) {
      return;
    }
    if (options.progress !== true) {
      window.agentOutputHasAnswerStream = true;
    }
    agentOutput.dataset.temporary = 'true';
    // 串流模式：使用增量打字效果
    typewriterEffect(nextText, 30, false);
    
    if (options.progress === true) {
      setAgentOutputMode('processing');
    } else {
      setAgentOutputMode('streaming');
    }
  } else {
    // 非串流模式（例如狀態更新）：直接更新文字
    cancelTypewriterAnimation();
    setTypewriterContent(nextText);
    agentOutput.dataset.temporary = 'false';
    agentOutput.classList.add('active');
    setAgentOutputMode('final');
  }
}


function finishAgentOutput(text, enableTTS = true, options = {}) {
  // 結束時不需要重啟打字機，只需確保目標文字是最新的，並完成剩餘部分
  window.agentOutputHasAnswerStream = false;
  agentOutput.dataset.temporary = 'false';
  typewriterEffect(text || '', 24, enableTTS, options);
}


function hideAgentOutput() {
  cancelTypewriterAnimation();
  window.agentOutputHasAnswerStream = false;
  agentOutput.classList.remove('active');
  agentOutput.classList.remove('typing-active');
  agentOutput.classList.add('typing-done');
  setAgentOutputMode(null);
  agentOutput.innerHTML = '';
  typewriterTextNode = null;
  lastRenderedAgentText = '';
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
    stopSpeaking(true, 'logout');
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

      // 確保重置錄音與波形，允許接著交互
      if (typeof stopRealAudioAnalysis === 'function') {
        stopRealAudioAnalysis();
      }
      if (typeof isRecording !== 'undefined') {
        isRecording = false;
      }

      toggleInputMode();
    } else {
      console.error('❌ WebSocket 未初始化');
    }
  }
}
