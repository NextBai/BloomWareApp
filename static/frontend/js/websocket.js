/**
 * Bloom Ware WebSocket 通訊管理模組（完整版）
 * 處理 WebSocket 連接、訊息收發、重連機制
 */

// ========== WebSocket 連接管理 ==========

class WebSocketManager {
  constructor(wsUrl) {
    this.wsUrl = wsUrl;
    this.ws = null;
    this.isConnecting = false;
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 5;
    this.reconnectDelay = 2000;

    // 狀態管理回調
    this.onlineCallbacks = [];
    this.messageCallbacks = [];

    // 音訊錄製相關
    this.audioContext = null;
    this.audioStream = null;
    this.audioProcessor = null;
    this.audioSource = null;
    this.isRecording = false;

    // 綁定方法上下文
    this.connect = this.connect.bind(this);
    this.handleOpen = this.handleOpen.bind(this);
    this.handleMessage = this.handleMessage.bind(this);
    this.handleClose = this.handleClose.bind(this);
    this.handleError = this.handleError.bind(this);
    this.startRecording = this.startRecording.bind(this);
    this.stopRecording = this.stopRecording.bind(this);
  }

  // 建立 WebSocket 連接
  async connect() {
    if (this.isConnecting || (this.ws && this.ws.readyState === WebSocket.OPEN)) {
      console.log('⚠️ WebSocket 已連接或正在連接中');
      return;
    }

    try {
      this.isConnecting = true;
      console.log('🔌 開始建立 WebSocket 連接:', this.wsUrl);

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

  // 處理 WebSocket 開啟事件
  handleOpen() {
    console.log('✅ WebSocket 連接已建立');
    this.isConnecting = false;
    this.reconnectAttempts = 0;
    this.notifyOnlineState(true);

    // 若已有目前對話，告知後端綁定 chat_id
    const cid = window.currentChatId;
    if (cid) {
      this.send({ type: 'chat_focus', chat_id: cid });
    }
  }

  // 處理 WebSocket 訊息
  handleMessage(event) {
    try {
      const data = JSON.parse(event.data);
      console.log('📩 收到 WebSocket 訊息:', data.type);

      // 通知所有訊息回調
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

  // 處理 WebSocket 關閉事件
  handleClose(event) {
    console.log('🔌 WebSocket 連接已關閉', event);
    this.notifyOnlineState(false);
    this.isConnecting = false;

    // 檢查是否為認證失敗（code 1008 或 1006 表示異常關閉）
    // code 1006: 連接異常關閉（通常是握手失敗）
    // code 1008: 違反政策（認證失敗）
    const isAuthError = event.code === 1008 || 
                        event.code === 1006 || 
                        event.reason?.includes('認證') || 
                        event.reason?.includes('令牌') ||
                        event.reason?.includes('Forbidden');

    if (isAuthError) {
      console.error('❌ 認證失敗，清除 token 並跳轉到登入頁面');
      // 清除過期的 token
      localStorage.removeItem('jwt_token');
      // 跳轉到登入頁
      setTimeout(() => {
        window.location.href = '/static/login.html';
      }, 500);
      return;
    }

    // 其他情況才嘗試重連
    this.scheduleReconnect();
  }

  // 處理 WebSocket 錯誤事件
  handleError(error) {
    console.error('❌ WebSocket 連接錯誤:', error);
    this.notifyOnlineState(false);
    this.isConnecting = false;
    
    // WebSocket 錯誤通常會伴隨 close 事件，但為了安全起見也檢查 token
    // 如果連接失敗，可能是認證問題
    setTimeout(() => {
      if (this.reconnectAttempts > 0) {
        // 已經嘗試重連，檢查 token 是否有效
        const token = localStorage.getItem('jwt_token');
        if (token) {
          try {
            const payload = JSON.parse(atob(token.split('.')[1]));
            const currentTime = Math.floor(Date.now() / 1000);
            
            if (payload.exp && payload.exp < currentTime) {
              console.error('❌ Token 已過期，跳轉到登入頁面');
              localStorage.removeItem('jwt_token');
              window.location.href = '/static/login.html';
            }
          } catch (e) {
            console.error('❌ Token 解析失敗，跳轉到登入頁面');
            localStorage.removeItem('jwt_token');
            window.location.href = '/static/login.html';
          }
        }
      }
    }, 1000);
  }

  // 排程重連
  scheduleReconnect() {
    // 如果重連次數超過 3 次，檢查是否為認證問題
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
            window.location.href = '/static/login.html';
            return;
          }
        } catch (error) {
          console.error('❌ Token 解析失敗，可能已損壞');
        }
      }
      
      // 如果重連次數達到上限，清除 token 並跳轉
      if (this.reconnectAttempts >= this.maxReconnectAttempts) {
        console.error('❌ WebSocket 重連次數已達上限，可能是認證問題，清除 token 並跳轉登入頁');
        localStorage.removeItem('jwt_token');
        window.location.href = '/static/login.html';
        return;
      }
    }

    this.reconnectAttempts++;
    const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);

    console.log(`🔄 WebSocket 將在 ${delay}ms 後重連（第 ${this.reconnectAttempts}/${this.maxReconnectAttempts} 次）`);

    setTimeout(() => {
      console.log(`🔄 WebSocket 重連嘗試 ${this.reconnectAttempts}/${this.maxReconnectAttempts}`);
      this.connect();
    }, delay);
  }

  // 發送訊息（通用）
  send(data) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
      console.log('📤 發送 WebSocket 訊息:', data.type);
      return true;
    }
    console.warn('⚠️ WebSocket 未連接，無法發送訊息');
    return false;
  }

  // 發送用戶輸入
  sendUserMessage(text, chatId) {
    if (!text || !text.trim()) {
      console.warn('⚠️ 訊息內容為空');
      return false;
    }

    // chatId 可以為空，後端會自動創建或使用最新對話
    if (!chatId) {
      console.log('📝 發送訊息（無 chat_id，後端將自動處理）');
    }

    const payload = {
      type: 'user_message',
      message: text,
      chat_id: chatId || null
    };

    return this.send(payload);
  }

  // 檢查連接狀態
  isConnected() {
    return this.ws && this.ws.readyState === WebSocket.OPEN;
  }

  // 斷開連接
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

  // 添加在線狀態回調
  onOnlineStateChange(callback) {
    this.onlineCallbacks.push(callback);
  }

  // 添加訊息回調
  onMessage(callback) {
    this.messageCallbacks.push(callback);
  }

  // 通知在線狀態變化
  notifyOnlineState(isOnline) {
    console.log(`🌐 WebSocket 狀態: ${isOnline ? '已連線' : '斷線'}`);

    this.onlineCallbacks.forEach(callback => {
      try {
        callback(isOnline);
      } catch (error) {
        console.error('❌ 在線狀態回調錯誤:', error);
      }
    });
  }

  // ========== 音訊錄製功能 ==========

  /**
   * 開始錄音（用於對話模式）
   */
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
      console.log('🎙️ 開始錄音...');

      // 🔓 解鎖音頻播放（利用用戶點擊麥克風的手勢）
      if (typeof unlockAudioPlayback === 'function') {
        unlockAudioPlayback();
      }

      // 請求麥克風權限
      this.audioStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        }
      });

      // 創建音訊上下文
      this.audioContext = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: 16000
      });

      // 創建音訊處理節點
      this.audioSource = this.audioContext.createMediaStreamSource(this.audioStream);
      this.audioProcessor = this.audioContext.createScriptProcessor(4096, 1, 1);

      // 連接音訊節點
      this.audioSource.connect(this.audioProcessor);
      this.audioProcessor.connect(this.audioContext.destination);

      // 發送開始錄音信號
      this.send({ 
        type: 'audio_start', 
        sample_rate: 16000,
        mode: 'chat'  // 對話模式（非語音登入）
      });

      this.isRecording = true;

      // 處理音訊數據
      this.audioProcessor.onaudioprocess = (e) => {
        if (!this.isRecording) return;

        try {
          const inputData = e.inputBuffer.getChannelData(0);

          // Float32 轉 Int16 PCM
          const pcm16 = new Int16Array(inputData.length);
          for (let i = 0; i < inputData.length; i++) {
            let sample = Math.max(-1, Math.min(1, inputData[i]));
            pcm16[i] = sample < 0 ? sample * 0x8000 : sample * 0x7FFF;
          }

          // 轉為 Uint8Array 並 Base64 編碼
          const bytes = new Uint8Array(pcm16.buffer);
          const b64 = btoa(String.fromCharCode(...bytes));

          // 發送音訊塊
          this.send({ 
            type: 'audio_chunk', 
            pcm16_base64: b64 
          });

        } catch (error) {
          console.error('❌ 音訊處理錯誤:', error);
        }
      };

      console.log('✅ 錄音已開始');
      return true;

    } catch (error) {
      console.error('❌ 開始錄音失敗:', error);
      
      // 顯示錯誤提示
      if (error.name === 'NotAllowedError') {
        if (typeof showErrorNotification === 'function') {
          showErrorNotification('需要麥克風權限才能使用語音功能');
        }
      }
      
      this.isRecording = false;
      return false;
    }
  }

  /**
   * 停止錄音
   */
  stopRecording() {
    if (!this.isRecording) {
      console.warn('⚠️ 目前沒有在錄音');
      return;
    }

    console.log('🛑 停止錄音...');

    // 停止音訊處理
    if (this.audioProcessor) {
      this.audioProcessor.disconnect();
      this.audioProcessor = null;
    }

    // 斷開音訊源
    if (this.audioSource) {
      try {
        this.audioSource.disconnect();
      } catch (e) {
        console.warn('⚠️ 斷開音訊源失敗:', e);
      }
      this.audioSource = null;
    }

    // 停止麥克風軌道
    if (this.audioStream) {
      this.audioStream.getTracks().forEach(track => track.stop());
      this.audioStream = null;
    }

    // 關閉音訊上下文
    if (this.audioContext) {
      this.audioContext.close();
      this.audioContext = null;
    }

    // 發送停止錄音信號
    this.send({
      type: 'audio_stop',
      mode: 'chat'  // 對話模式
    });

    this.isRecording = false;
    console.log('✅ 錄音已停止');
  }

  // ========== 語音綁定專用錄音功能 ==========

  /**
   * 開始語音綁定錄音（專用於綁定流程）
   */
  async startVoiceBindingRecording() {
    if (this.isRecording) {
      console.warn('⚠️ 已經在錄音中');
      return false;
    }

    if (!this.isConnected()) {
      console.error('❌ WebSocket 未連接，無法開始錄音');
      return false;
    }

    try {
      console.log('🎙️ 開始語音綁定錄音...');

      // 🔓 解鎖音頻播放
      if (typeof unlockAudioPlayback === 'function') {
        unlockAudioPlayback();
      }

      // 請求麥克風權限
      this.audioStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        }
      });

      // 創建音訊上下文
      this.audioContext = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: 16000
      });

      // 創建音訊處理節點
      this.audioSource = this.audioContext.createMediaStreamSource(this.audioStream);
      this.audioProcessor = this.audioContext.createScriptProcessor(4096, 1, 1);

      // 連接音訊節點
      this.audioSource.connect(this.audioProcessor);
      this.audioProcessor.connect(this.audioContext.destination);

      // 發送開始錄音信號（語音綁定模式）
      this.send({
        type: 'audio_start',
        sample_rate: 16000,
        mode: 'binding'  // 語音綁定模式
      });

      this.isRecording = true;

      // 處理音訊數據
      this.audioProcessor.onaudioprocess = (e) => {
        if (!this.isRecording) return;

        try {
          const inputData = e.inputBuffer.getChannelData(0);

          // Float32 轉 Int16 PCM
          const pcm16 = new Int16Array(inputData.length);
          for (let i = 0; i < inputData.length; i++) {
            let sample = Math.max(-1, Math.min(1, inputData[i]));
            pcm16[i] = sample < 0 ? sample * 0x8000 : sample * 0x7FFF;
          }

          // 轉為 Uint8Array 並 Base64 編碼
          const bytes = new Uint8Array(pcm16.buffer);
          const b64 = btoa(String.fromCharCode(...bytes));

          // 發送音訊塊
          this.send({
            type: 'audio_chunk',
            pcm16_base64: b64
          });

        } catch (error) {
          console.error('❌ 音訊處理錯誤:', error);
        }
      };

      console.log('✅ 語音綁定錄音已開始');
      return true;

    } catch (error) {
      console.error('❌ 開始語音綁定錄音失敗:', error);

      // 顯示錯誤提示
      if (error.name === 'NotAllowedError') {
        if (typeof showErrorNotification === 'function') {
          showErrorNotification('需要麥克風權限才能使用語音綁定功能');
        }
      }

      this.isRecording = false;
      return false;
    }
  }

  /**
   * 停止語音綁定錄音
   */
  stopVoiceBindingRecording() {
    if (!this.isRecording) {
      console.warn('⚠️ 目前沒有在錄音');
      return;
    }

    console.log('🛑 停止語音綁定錄音...');

    // 停止音訊處理
    if (this.audioProcessor) {
      this.audioProcessor.disconnect();
      this.audioProcessor = null;
    }

    // 斷開音訊源
    if (this.audioSource) {
      try {
        this.audioSource.disconnect();
      } catch (e) {
        console.warn('⚠️ 斷開音訊源失敗:', e);
      }
      this.audioSource = null;
    }

    // 停止麥克風軌道
    if (this.audioStream) {
      this.audioStream.getTracks().forEach(track => track.stop());
      this.audioStream = null;
    }

    // 關閉音訊上下文
    if (this.audioContext) {
      this.audioContext.close();
      this.audioContext = null;
    }

    // 發送停止錄音信號（語音綁定模式）
    this.send({
      type: 'audio_stop',
      mode: 'binding'  // 語音綁定模式
    });

    this.isRecording = false;
    console.log('✅ 語音綁定錄音已停止');
  }
}

/**
 * 初始化 WebSocket 連接（由 app.js 呼叫）
 * @param {string} token - JWT token
 */
function initializeWebSocket(token) {
  console.log('🚀 初始化 WebSocket 連接...');

  // 根據當前頁面協議確定WebSocket協議
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;

  // 構建WebSocket URL
  const wsUrl = `${protocol}//${host}/ws?token=${token}`;

  // 創建 WebSocket 管理器
  wsManager = new WebSocketManager(wsUrl);

  // 監聽訊息（原本在 js/websocket.js 中的邏輯）
  wsManager.onMessage((data) => {
    console.log('📩 收到 WebSocket 訊息:', data);

    switch(data.type) {
      case 'system':
        // 系統訊息（歡迎詞、連線成功）
        console.log('🔔 系統訊息:', data.message);
        
        // 如果系統訊息包含 chat_id，儲存它
        if (data.chat_id) {
          currentChatId = data.chat_id;
          window.currentChatId = currentChatId;
          console.log('✅ 已設置 chat_id:', currentChatId);
        }
        
        if (data.message) {
          setState('speaking', {
            outputText: data.message,
            enableTTS: false,  // 歡迎詞不使用 TTS
            persistent: true   // 持續顯示直到用戶發起請求
          });
          // 系統訊息不自動轉回 idle，保持顯示狀態
          // 用戶發起請求時會自動清除
        }
        break;

      case 'typing':
        // 思考中提示
        if (data.message === 'thinking') {
          setState('thinking');
        }
        break;

      case 'bot_message':
        // AI 回應完成 - 使用異步方式（文字與語音並行）
        console.log('💬 AI 回應:', data.message);
        console.log('🔧 工具資訊:', {
          tool_name: data.tool_name,
          tool_data: data.tool_data,
          has_tool_data: !!data.tool_data,
          tool_data_keys: data.tool_data ? Object.keys(data.tool_data) : null
        });
        
        // 同時啟動：文字打字效果 + 語音播放
        setState('speaking', {
          outputText: data.message,
          enableTTS: true  // 啟用語音（異步並行）
        });

        // 如果有工具資料，顯示對應卡片
        if (data.tool_name && data.tool_data) {
          console.log('📊 準備顯示工具卡片:', data.tool_name);
          displayToolCard(data.tool_name, data.tool_data);
        } else {
          console.log('⚠️ 無工具資料，不顯示卡片');
        }

        // 不自動返回 idle，保持回應顯示
        // 用戶下次點擊麥克風時會自動開始新的請求
        console.log('✅ AI 回應已顯示（保持狀態直到下次請求）');
        break;

      case 'stt_partial':
        // STT 臨時結果（用戶還在說話）
        console.log('🎙️ STT 臨時結果:', data.text);
        transcript.textContent = data.text;
        transcript.className = 'voice-transcript provisional';
        break;

      case 'stt_final':
        // STT 最終結果（用戶停止說話）
        console.log('✅ STT 最終結果:', data.text);
        transcript.textContent = data.text;
        transcript.className = 'voice-transcript final';
        
        // 應用情緒主題（如果有的話）
        if (data.emotion && typeof applyEmotion === 'function') {
          const emotionValue = typeof data.emotion === 'string' ? data.emotion : data.emotion.label;
          console.log('😊 應用情緒主題:', emotionValue);
          applyEmotion(emotionValue);
        }
        break;

      case 'emotion_detected':
        // 文字情緒偵測結果（新增）
        console.log('😊 偵測到情緒:', data.emotion, 'care_mode:', data.care_mode);
        if (data.emotion && typeof applyEmotion === 'function') {
          const emotionValue = typeof data.emotion === 'string' ? data.emotion : data.emotion.label;
          applyEmotion(emotionValue);
        }
        if (data.care_mode) {
          console.log('💙 進入關懷模式');
        }
        break;

      case 'new_chat_created':
        // 新對話建立
        currentChatId = data.chat_id;
        window.currentChatId = currentChatId;  // 確保全域變數也更新
        console.log('✅ 新對話建立:', currentChatId, '標題:', data.title);
        break;

      case 'error':
        // 錯誤訊息
        console.error('❌ 後端錯誤:', data.message);
        setState('idle');
        showErrorNotification(data.message);
        break;

      case 'voice_login_result':
        // 語音登入結果
        handleVoiceLoginResult(data);
        break;

      case 'voice_login_status':
        // 語音登入狀態更新
        console.log('🎙️ 語音登入狀態:', data.message);
        break;

      case 'voice_binding_ready':
        // 語音綁定準備就緒 - 自動開始錄音 5 秒
        console.log('🎙️ 收到 voice_binding_ready，準備錄音 5 秒...');
        handleVoiceBindingReady();
        break;

      default:
        console.log('🔍 未處理的訊息類型:', data.type);
    }
  });

  // 監聽連線狀態變化
  wsManager.onOnlineStateChange((isOnline) => {
    console.log(`🌐 WebSocket 狀態: ${isOnline ? '已連線' : '斷線'}`);
    if (!isOnline) {
      setState('disconnected');
    } else if (currentState === 'disconnected') {
      setState('idle');
    }
  });

  // 開始連接
  wsManager.connect();

  console.log('✅ WebSocket 管理器已初始化');
}

/**
 * 處理語音登入結果
 */
function handleVoiceLoginResult(data) {
  if (data.success && data.user) {
    currentUserId = data.user.id;

    // 套用情緒主題
    if (data.emotion) {
      const emotionValue = typeof data.emotion === 'string' ? data.emotion : data.emotion.label;
      applyEmotion(emotionValue);
    }

    // 顯示歡迎詞
    if (data.welcome) {
      setState('speaking', {
        outputText: data.welcome,
        enableTTS: true
      });
      setTimeout(() => setState('idle'), 5000);
    }

    console.log('✅ 語音登入成功:', data.user.name);
  } else {
    console.warn('⚠️ 語音登入失敗:', data.error);
    showErrorNotification(`語音登入失敗: ${data.error || '未知錯誤'}`);
  }
}

/**
 * 處理語音綁定準備就緒訊息
 * 自動切換到花蕊錄音狀態，錄製 5 秒語音
 */
async function handleVoiceBindingReady() {
  console.log('🌸 開始語音綁定流程：自動錄音 5 秒');

  // 更新提示文字
  if (typeof transcript !== 'undefined') {
    transcript.textContent = '請開始說話（錄音 5 秒）...';
    transcript.className = 'voice-transcript provisional';
  }

  // 切換到錄音狀態（花蕊綻放）
  if (typeof setState === 'function') {
    setState('recording', {
      keepOutput: false,
      keepCards: false
    });
  }

  // 啟動音訊視覺化
  if (typeof startRealAudioAnalysis === 'function') {
    await startRealAudioAnalysis();
  }

  // 啟動語音綁定專用錄音
  if (wsManager && typeof wsManager.startVoiceBindingRecording === 'function') {
    const success = await wsManager.startVoiceBindingRecording();

    if (!success) {
      console.error('❌ 語音綁定錄音啟動失敗');
      setState('idle');
      if (typeof stopRealAudioAnalysis === 'function') {
        stopRealAudioAnalysis();
      }
      showErrorNotification('麥克風啟動失敗，請檢查權限設定');
      return;
    }

    console.log('⏱️ 開始倒數 5 秒錄音...');

    // 倒數計時提示
    let countdown = 5;
    const countdownInterval = setInterval(() => {
      countdown--;
      if (countdown > 0 && typeof transcript !== 'undefined') {
        transcript.textContent = `請繼續說話（剩餘 ${countdown} 秒）...`;
        transcript.className = 'voice-transcript provisional';
      }
    }, 1000);

    // 5 秒後自動停止錄音
    setTimeout(() => {
      clearInterval(countdownInterval);
      console.log('⏹️ 5 秒錄音完成，自動停止');

      // 停止音訊視覺化
      if (typeof stopRealAudioAnalysis === 'function') {
        stopRealAudioAnalysis();
      }

      // 停止語音綁定錄音
      if (wsManager && typeof wsManager.stopVoiceBindingRecording === 'function') {
        wsManager.stopVoiceBindingRecording();
      }

      // 切換到思考狀態
      if (typeof setState === 'function') {
        setState('thinking');
      }

      // 更新提示
      if (typeof transcript !== 'undefined') {
        transcript.textContent = '正在處理語音綁定...';
        transcript.className = 'voice-transcript provisional';
      }

    }, 5000);  // 5 秒錄音時長
  } else {
    console.error('❌ WebSocket 管理器未初始化');
    showErrorNotification('系統錯誤：WebSocket 未連接');
  }
}

console.log('✅ WebSocket 模組已載入（完整版）');
