

class WebSocketManager {
  constructor(wsUrl) {
    this.wsUrl = wsUrl;
    this.ws = null;
    this.isConnecting = false;
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 5;
    this.reconnectDelay = 2000;

    this.onlineCallbacks = [];
    this.messageCallbacks = [];

    this.audioContext = null;
    this.audioStream = null;
    this.audioProcessor = null;
    this.audioSource = null;
    this.isRecording = false;

    this.connect = this.connect.bind(this);
    this.handleOpen = this.handleOpen.bind(this);
    this.handleMessage = this.handleMessage.bind(this);
    this.handleClose = this.handleClose.bind(this);
    this.handleError = this.handleError.bind(this);
    this.startRecording = this.startRecording.bind(this);
    this.stopRecording = this.stopRecording.bind(this);
  }

  async connect() {
    if (this.isConnecting || (this.ws && this.ws.readyState === WebSocket.OPEN)) {
      return;
    }

    try {
      this.isConnecting = true;

      this.ws = new WebSocket(this.wsUrl);
      this.notifyOnlineState(false);

      this.ws.addEventListener('open', this.handleOpen);
      this.ws.addEventListener('message', this.handleMessage);
      this.ws.addEventListener('close', this.handleClose);
      this.ws.addEventListener('error', this.handleError);

    } catch (error) {
      console.error('❌ WebSocket 連接失敗:', error);
      this.isConnecting = false;
      this.scheduleReconnect();
    }
  }

  handleOpen() {
    this.isConnecting = false;
    this.reconnectAttempts = 0;
    this.notifyOnlineState(true);

    const cid = window.currentChatId;
    if (cid) {
      this.send({ type: 'chat_focus', chat_id: cid });
    }

    if (typeof startLocationTracking === 'function') {
      startLocationTracking();
    } else {
      console.warn('⚠️ startLocationTracking 函數未定義');
    }
  }

  handleMessage(event) {
    try {
      const data = JSON.parse(event.data);

      const silentTypes = ['env_ack', 'typing', 'stt_partial', 'stt_delta'];
      if (!silentTypes.includes(data.type)) {
        if (window.DEBUG_MODE) {
        }
      }

      this.messageCallbacks.forEach(callback => {
        try {
          callback(data);
        } catch (error) {
          console.error('❌ WebSocket 訊息回調錯誤:', error);
        }
      });

    } catch (error) {
      console.error('❌ 解析 WebSocket 訊息失敗:', error);
    }
  }

  handleClose(event) {
    this.notifyOnlineState(false);
    this.isConnecting = false;

    const isAuthError = event.code === 1008 || 
                        event.code === 1006 || 
                        event.reason?.includes('認證') || 
                        event.reason?.includes('令牌') ||
                        event.reason?.includes('Forbidden');

    if (isAuthError) {
      console.error('❌ 認證失敗，清除 token 並跳轉到登入頁面');
      localStorage.removeItem('jwt_token');
      setTimeout(() => {
        window.location.href = '/login/';
      }, 500);
      return;
    }

    this.scheduleReconnect();
  }

  handleError(error) {
    console.error('❌ WebSocket 連接錯誤:', error);
    this.notifyOnlineState(false);
    this.isConnecting = false;
    
    setTimeout(() => {
      if (this.reconnectAttempts > 0) {
        const token = localStorage.getItem('jwt_token');
        if (token) {
          try {
            const payload = JSON.parse(atob(token.split('.')[1]));
            const currentTime = Math.floor(Date.now() / 1000);
            
            if (payload.exp && payload.exp < currentTime) {
              console.error('❌ Token 已過期，跳轉到登入頁面');
              localStorage.removeItem('jwt_token');
              window.location.href = '/login/';
            }
          } catch (e) {
            console.error('❌ Token 解析失敗，跳轉到登入頁面');
            localStorage.removeItem('jwt_token');
            window.location.href = '/login/';
          }
        }
      }
    }, 1000);
  }

  scheduleReconnect() {
    if (this.reconnectAttempts >= 3) {
      console.warn('⚠️ 多次重連失敗，檢查 token 有效性...');
      
      const token = localStorage.getItem('jwt_token');
      if (token) {
        try {
          const payload = JSON.parse(atob(token.split('.')[1]));
          const currentTime = Math.floor(Date.now() / 1000);
          
          if (payload.exp && payload.exp < currentTime) {
            console.error('❌ Token 已過期，跳轉到登入頁面');
            localStorage.removeItem('jwt_token');
            window.location.href = '/login/';
            return;
          }
        } catch (error) {
          console.error('❌ Token 解析失敗，可能已損壞');
        }
      }
      
      if (this.reconnectAttempts >= this.maxReconnectAttempts) {
        console.error('❌ WebSocket 重連次數已達上限，可能是認證問題，清除 token 並跳轉登入頁');
        localStorage.removeItem('jwt_token');
        window.location.href = '/login/';
        return;
      }
    }

    this.reconnectAttempts++;
    const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);


    setTimeout(() => {
      this.connect();
    }, delay);
  }

  send(data) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
      const silentTypes = ['audio_chunk', 'env_snapshot'];
      if (window.DEBUG_MODE && !silentTypes.includes(data.type)) {
      }
      return true;
    }
    console.warn('⚠️ WebSocket 未連接');
    return false;
  }

  sendUserMessage(text, chatId) {
    if (!text || !this.isConnected()) {
      console.warn('⚠️ WebSocket 未連接或訊息為空');
      return false;
    }

    if (!chatId) {
      console.warn('⚠️ 缺少 chat_id');
      return false;
    }

    const payload = {
      type: 'user_message',
      message: text,
      chat_id: chatId
    };

    return this.send(payload);
  }

  isConnected() {
    return this.ws && this.ws.readyState === WebSocket.OPEN;
  }

  disconnect() {
    if (this.ws) {
      this.ws.removeEventListener('open', this.handleOpen);
      this.ws.removeEventListener('message', this.handleMessage);
      this.ws.removeEventListener('close', this.handleClose);
      this.ws.removeEventListener('error', this.handleError);

      this.ws.close();
      this.ws = null;
    }
    this.notifyOnlineState(false);
  }

  onOnlineStateChange(callback) {
    this.onlineCallbacks.push(callback);
  }

  onMessage(callback) {
    this.messageCallbacks.push(callback);
  }

  notifyOnlineState(isOnline) {

    this.onlineCallbacks.forEach(callback => {
      try {
        callback(isOnline);
      } catch (error) {
        console.error('❌ 在線狀態回調錯誤:', error);
      }
    });
  }


  async startRecording() {
    if (this.isRecording) {
      console.warn('⚠️ 已經在錄音中');
      return false;
    }

    if (!this.isConnected()) {
      console.error('❌ WebSocket 未連接，無法開始錄音');
      return false;
    }

    try {

      if (typeof unlockAudioPlayback === 'function') {
        unlockAudioPlayback();
      }

      this.audioStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        }
      });

      this.audioContext = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: 16000
      });

      this.audioSource = this.audioContext.createMediaStreamSource(this.audioStream);
      this.audioProcessor = this.audioContext.createScriptProcessor(4096, 1, 1);

      this.audioSource.connect(this.audioProcessor);
      this.audioProcessor.connect(this.audioContext.destination);

      this.send({
        type: 'audio_start',
        sample_rate: 16000,
        mode: 'realtime_chat',  // 即時轉錄模式（使用 OpenAI Realtime API）
        language: 'auto'  // 自動檢測語言（支援：zh/en/id/ja/vi）
      });
      

      this.isRecording = true;

      this.audioProcessor.onaudioprocess = (e) => {
        if (!this.isRecording) return;

        try {
          const inputData = e.inputBuffer.getChannelData(0);

          const pcm16 = new Int16Array(inputData.length);
          for (let i = 0; i < inputData.length; i++) {
            let sample = Math.max(-1, Math.min(1, inputData[i]));
            pcm16[i] = sample < 0 ? sample * 0x8000 : sample * 0x7FFF;
          }

          const bytes = new Uint8Array(pcm16.buffer);
          const b64 = btoa(String.fromCharCode(...bytes));

          this.send({ 
            type: 'audio_chunk', 
            pcm16_base64: b64 
          });

        } catch (error) {
          console.error('❌ 音訊處理錯誤:', error);
        }
      };

      return true;

    } catch (error) {
      console.error('❌ 開始錄音失敗:', error);
      
      if (error.name === 'NotAllowedError') {
        if (typeof showErrorNotification === 'function') {
          showErrorNotification('需要麥克風權限才能使用語音功能');
        }
      }
      
      this.isRecording = false;
      return false;
    }
  }

  stopRecording() {
    if (!this.isRecording) {
      console.warn('⚠️ 目前沒有在錄音');
      return;
    }


    if (this.audioProcessor) {
      this.audioProcessor.disconnect();
      this.audioProcessor = null;
    }

    if (this.audioSource) {
      try {
        this.audioSource.disconnect();
      } catch (e) {
        console.warn('⚠️ 斷開音訊源失敗:', e);
      }
      this.audioSource = null;
    }

    if (this.audioStream) {
      this.audioStream.getTracks().forEach(track => track.stop());
      this.audioStream = null;
    }

    if (this.audioContext) {
      this.audioContext.close();
      this.audioContext = null;
    }

    this.send({
      type: 'audio_stop',
      mode: 'realtime_chat'  // 即時轉錄模式
    });

    this.isRecording = false;
  }
}

function initializeWebSocket(token) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;

  const voiceEmotion = localStorage.getItem('voice_login_emotion');

  let wsUrl = `${protocol}//${host}/ws?token=${token}`;
  if (voiceEmotion) {
    wsUrl += `&emotion=${encodeURIComponent(voiceEmotion)}`;
    localStorage.removeItem('voice_login_emotion');

    if (typeof applyEmotion === 'function') {
      applyEmotion(voiceEmotion);
    }
  }

  wsManager = new WebSocketManager(wsUrl);

  wsManager.onMessage((data) => {
    switch(data.type) {
      case 'system':
        if (data.chat_id) {
          window.currentChatId = data.chat_id;
        }
        if (data.message) {
          setState('speaking', {
            outputText: data.message,
            enableTTS: false,
            persistent: true
          });
        }
        break;

      case 'typing':
        if (data.message === 'thinking') {
          setState('thinking');
          if (typeof hideToolCards === 'function') {
            hideToolCards();
          }
        }
        break;

      case 'bot_message':
        // 【統一】不在此處套用情緒，只由 emotion_detected 事件控制
        // 保留情緒資訊在 data 中供調試使用

        if (data.care_mode && typeof hideToolCards === 'function') {
          hideToolCards();
        }

        setState('speaking', {
          outputText: data.message,
          enableTTS: true
        });

        if (data.tool_name && data.tool_data) {
          displayToolCard(data.tool_name, data.tool_data);
        }
        break;

      case 'stt_partial':
        transcript.textContent = data.text;
        transcript.className = 'voice-transcript provisional';
        break;

      case 'stt_delta':
        if (!window.realtimeTranscript) {
          window.realtimeTranscript = '';
        }
        window.realtimeTranscript += data.text;
        transcript.textContent = window.realtimeTranscript;
        transcript.className = 'voice-transcript realtime';
        break;

      case 'stt_final':
        transcript.textContent = data.text;
        transcript.className = 'voice-transcript final';
        window.realtimeTranscript = '';
        // 【統一】不在此處套用情緒，只由 emotion_detected 事件控制
        break;

      case 'realtime_stt_status':
        if (data.status === 'connected') {
          window.realtimeTranscript = '';
        }
        break;

      case 'chat_ready':
        window.currentChatId = data.chat_id;
        break;

      case 'error':
        console.error('❌ 後端錯誤:', data.message);
        setState('idle');
        showErrorNotification(data.message);
        break;

      case 'voice_login_result':
        handleVoiceLoginResult(data);
        break;

      case 'voice_login_status':
        break;

      case 'emotion_detected':
        if (data.emotion && typeof applyEmotion === 'function') {
          applyEmotion(data.emotion);
        }
        if (data.care_mode && typeof hideToolCards === 'function') {
          hideToolCards();
        }
        break;

      case 'audio_emotion_detected':
        // 【統一】不在此處套用情緒，只由 emotion_detected 事件控制
        // 後端會融合音頻和文字情緒後統一發送 emotion_detected
        break;

      case 'env_ack':
        break;

      default:
        if (window.DEBUG_MODE) {
        }
    }
  });

  wsManager.onOnlineStateChange((isOnline) => {
    if (!isOnline) {
      setState('disconnected');
    } else if (currentState === 'disconnected') {
      setState('idle');
    }
  });

  wsManager.connect();
}

function handleVoiceLoginResult(data) {
  if (data.success && data.user) {
    currentUserId = data.user.id;

    if (data.emotion && data.emotion.label) {
      applyEmotion(data.emotion.label);
    }

    if (data.welcome) {
      setState('speaking', {
        outputText: data.welcome,
        enableTTS: true
      });
      setTimeout(() => setState('idle'), 5000);
    }

  } else {
    console.warn('⚠️ 語音登入失敗:', data.error);
    showErrorNotification(`語音登入失敗: ${data.error || '未知錯誤'}`);
  }
}

