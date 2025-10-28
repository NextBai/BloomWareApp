/**
 * Bloom Ware WebSocket 通訊管理模組
 * 處理 WebSocket 連接、訊息收發、重連機制、語音功能
 */

import { safeStorage, safeExecute, getCurrentUserId } from './utils.js';

// ========== WebSocket 連接管理 ==========

export class WebSocketManager {
  constructor(authManager) {
    this.auth = authManager;
    this.ws = null;
    this.isConnecting = false;
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 5;
    this.reconnectDelay = 2000;

    // 狀態管理回調
    this.onlineCallbacks = [];
    this.messageCallbacks = [];

    // 綁定方法上下文
    this.connect = this.connect.bind(this);
    this.handleOpen = this.handleOpen.bind(this);
    this.handleMessage = this.handleMessage.bind(this);
    this.handleClose = this.handleClose.bind(this);
    this.handleError = this.handleError.bind(this);
  }

  // 生成 WebSocket URL
  getWsUrl() {
    // 使用認證管理器獲取JWT token
    let jwtToken = this.auth.getJwtToken();

    console.log('🔍 WebSocket URL生成 - token檢查:', { 
      hasToken: !!jwtToken, 
      isAuthenticated: this.auth.isAuthenticated() 
    });

    // 檢查 token 是否存在
    if (!jwtToken) {
      console.error('❌ WebSocket 連線失敗：沒有 JWT token');
      throw new Error('Missing JWT token');
    }

    // 檢查 token 是否過期（使用更寬鬆的檢查，避免剛登入就被判定過期）
    const isExpired = this.auth.isTokenExpired();
    if (isExpired) {
      console.error('❌ WebSocket 連線失敗：JWT token 已過期');
      throw new Error('JWT token expired');
    }

    // 根據當前頁面協議確定WebSocket協議
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;

    // 構建WebSocket URL
    const url = new URL(`${protocol}//${host}/ws`);
    url.searchParams.set('token', jwtToken);

    console.log('✅ WebSocket URL已生成');
    return url.toString();
  }

  // 建立 WebSocket 連接
  async connect() {
    if (this.isConnecting || (this.ws && this.ws.readyState === WebSocket.OPEN)) {
      return;
    }

    try {
      this.isConnecting = true;
      const wsUrl = this.getWsUrl();

      this.ws = new WebSocket(wsUrl);
      this.notifyOnlineState(false);

      this.ws.addEventListener('open', this.handleOpen);
      this.ws.addEventListener('message', this.handleMessage);
      this.ws.addEventListener('close', this.handleClose);
      this.ws.addEventListener('error', this.handleError);

    } catch (error) {
      console.error('WebSocket 連接失敗:', error);
      this.isConnecting = false;
      this.scheduleReconnect();
    }
  }

  // 處理 WebSocket 開啟事件
  async handleOpen() {
    console.log('WebSocket 連接已建立');
    this.isConnecting = false;
    this.reconnectAttempts = 0;
    this.notifyOnlineState(true);

    // 若已有目前對話，告知後端綁定 chat_id
    const cid = window.currentChatId;
    if (cid) {
      this.send({ type: 'chat_focus', chat_id: cid });
    }

    // 如果用戶已登入但沒有當前對話，檢查是否需要創建初始對話
    if (this.auth.user && !window.currentChatId) {
      setTimeout(async () => {
        await this.handleInitialChatSetup();
      }, 500);
    }
  }

  // 處理初始對話設置
  async handleInitialChatSetup() {
    try {
      const chats = await this.getUserChats(this.auth.user.id);

      if (!chats || chats.length === 0) {
        // 用戶沒有任何對話，創建初始對話
        await this.createInitialChat(this.auth.user);
      } else {
        // 用戶有對話，使用最新的對話
        const latestChat = chats[0];
        window.currentChatId = latestChat.chat_id;
      }

      // 刷新對話清單
      if (window.refreshChats) {
        window.refreshChats();
      }
    } catch (error) {
      console.error('WebSocket連接後檢查對話失敗:', error);
    }
  }

  // 處理 WebSocket 訊息
  handleMessage(event) {
    try {
      const data = JSON.parse(event.data);

      // 通知所有訊息回調
      this.messageCallbacks.forEach(callback => {
        safeExecute(() => callback(data), null, 'WebSocket 訊息回調');
      });

      // 處理不同類型的訊息
      switch (data.type) {
        case 'bot_message':
          this.handleBotMessage(data);
          break;
        case 'chat_history':
          this.handleChatHistory(data);
          break;
        case 'voice_login_status':
          this.handleVoiceLoginStatus(data);
          break;
        case 'voice_login_result':
          this.handleVoiceLoginResult(data);
          break;
        case 'new_chat_created':
          this.handleNewChatCreated(data);
          break;
        case 'error':
          this.handleError(data);
          break;
        case 'system':
        case 'message':
          // 這些訊息類型直接由 app.js 的回調處理
          // 不需要額外處理，已經在上面的 forEach 中處理了
          break;
        default:
          console.log('收到未知類型的訊息:', data.type);
      }
    } catch (error) {
      console.error('解析 WebSocket 訊息失敗:', error);
    }
  }

  // 處理機器人訊息
  handleBotMessage(data) {
    if (window.addMessage) {
      window.addMessage('assistant', data.message || '');
    }
  }

  // 處理聊天歷史
  handleChatHistory(data) {
    if (Array.isArray(data.messages) && window.addMessage) {
      data.messages.forEach(m => {
        window.addMessage(
          m.role === 'assistant' ? 'assistant' : 'user',
          m.content || ''
        );
      });
    }
  }

  // 處理語音登入狀態
  handleVoiceLoginStatus(data) {
    const statusEl = document.getElementById('voice-login-status');
    if (statusEl) {
      statusEl.textContent = '錄製中…';
    }
  }

  // 處理語音登入結果
  async handleVoiceLoginResult(data) {
    const statusEl = document.getElementById('voice-login-status');
    const success = !!data.success;

    if (success && data.user) {
      // 語音登入成功
      if (window.handleAuthenticatedUser) {
        window.handleAuthenticatedUser(data.user, data.access_token);
      }

      await this.handleVoiceLoginSuccess(data);
    } else {
      // 語音登入失敗
      const reason = data.error || '未知錯誤';
      console.error('語音登入失敗:', reason);

      if (window.UIStateManager?.showError) {
        window.UIStateManager.showError(`語音登入失敗：${reason}`);
      }
    }

    if (statusEl) {
      statusEl.textContent = success ? '完成' : '失敗';
    }
  }

  // 處理語音登入成功
  async handleVoiceLoginSuccess(data) {
    try {
      const userId = data.user.id;
      const chats = await this.getUserChats(userId);

      if (chats && chats.length > 0) {
        // 使用現有對話
        const latestChat = chats[0];
        window.currentChatId = latestChat.chat_id;

        this.clearChatAndShowWelcome(data.welcome);
        await this.saveWelcomeMessage(data.welcome, latestChat.chat_id);

        if (window.refreshChats) {
          window.refreshChats();
        }
      } else {
        // 創建新對話
        await this.createVoiceChatSession(userId, data.welcome);
      }
    } catch (error) {
      console.error('語音登入處理對話失敗:', error);
      this.clearChatAndShowWelcome(data.welcome);
    }
  }

  // 創建語音聊天會話
  async createVoiceChatSession(userId, welcome) {
    const now = new Date();
    const title = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')} ${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}`;

    const response = await fetch('/api/chats', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, title })
    });

    const result = await response.json();
    if (result && result.chat_id) {
      window.currentChatId = result.chat_id;
      if (window.refreshChats) {
        window.refreshChats();
      }
    }

    this.clearChatAndShowWelcome(welcome);
    await this.saveWelcomeMessage(welcome, window.currentChatId);
  }

  // 清除聊天並顯示歡迎訊息
  clearChatAndShowWelcome(welcome) {
    if (window.clearChat) {
      window.clearChat();
    }
    if (welcome && window.addSystem) {
      window.addSystem(String(welcome));
    }
  }

  // 保存歡迎訊息
  async saveWelcomeMessage(welcome, chatId) {
    if (!welcome || !chatId) return;

    try {
      await fetch(`/api/chats/${encodeURIComponent(chatId)}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sender: 'assistant',
          content: String(welcome)
        })
      });
    } catch (error) {
      console.warn('保存歡迎訊息失敗:', error);
    }
  }

  // 處理新對話創建
  handleNewChatCreated(data) {
    window.currentChatId = data.chat_id;
    if (window.addSystem) {
      window.addSystem(`已創建新對話：${data.title || '新對話'}`);
    }
    if (window.refreshChats) {
      window.refreshChats();
    }
  }

  // 處理 WebSocket 關閉事件
  handleClose() {
    console.log('WebSocket 連接已關閉');
    this.notifyOnlineState(false);
    this.isConnecting = false;
    this.scheduleReconnect();
  }

  // 處理 WebSocket 錯誤事件
  handleError(error) {
    console.error('WebSocket 連接錯誤:', error);
    this.notifyOnlineState(false);
    this.isConnecting = false;
  }

  // 排程重連
  scheduleReconnect() {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('WebSocket 重連次數已達上限');
      return;
    }

    this.reconnectAttempts++;
    const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);

    setTimeout(() => {
      console.log(`WebSocket 重連嘗試 ${this.reconnectAttempts}/${this.maxReconnectAttempts}`);
      this.connect();
    }, delay);
  }

  // 發送訊息（通用）
  send(data) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
      return true;
    }
    return false;
  }

  // 發送用戶輸入
  sendUserMessage(text, chatId) {
    if (!text || !this.isConnected()) return false;

    // 檢查認證狀態
    if (!this.auth.isAuthenticated()) {
      if (window.addSystem) {
        window.addSystem('❌ 請先使用 Google 登入');
      }
      return false;
    }

    // 檢查對話ID
    if (!chatId) {
      if (window.addSystem) {
        window.addSystem('❌ 請先選擇或創建一個對話');
      }
      return false;
    }

    const payload = {
      type: 'user_message',
      message: text,
      user_id: getCurrentUserId(),
      chat_id: chatId
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
    this.onlineCallbacks.forEach(callback => {
      safeExecute(() => callback(isOnline), null, '在線狀態回調');
    });

    // 更新DOM狀態指示器
    if (window.setOnline) {
      window.setOnline(isOnline);
    }
  }

  // 獲取用戶對話列表
  async getUserChats(userId) {
    try {
      const response = await fetch(`/api/chats/${userId}`);
      const data = await response.json();
      return data.success ? data.chats : [];
    } catch (error) {
      console.error('獲取用戶對話失敗:', error);
      return [];
    }
  }

  // 創建初始對話
  async createInitialChat(user) {
    if (window.createInitialChat) {
      return window.createInitialChat(user);
    }
  }
}

// ========== 語音登入管理 ==========

export class VoiceLoginManager {
  constructor(wsManager) {
    this.ws = wsManager;
    this.isRecording = false;
  }

  // 開始語音登入
  async startVoiceLogin() {
    if (this.isRecording) return;

    try {
      // 確保 WebSocket 連接
      if (!this.ws.isConnected()) {
        await this.ws.connect();
        await new Promise(resolve => setTimeout(resolve, 300));
      }

      // 啟動錄音
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, sampleRate: 48000 },
        video: false
      });

      const audioCtx = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: 16000
      });
      const source = audioCtx.createMediaStreamSource(stream);
      const processor = audioCtx.createScriptProcessor(4096, 1, 1);

      source.connect(processor);
      processor.connect(audioCtx.destination);

      this.isRecording = true;
      this.updateStatus('準備錄製…');
      this.ws.send({ type: 'audio_start', sample_rate: 16000 });

      let collectedMs = 0;
      const targetMs = 4000; // 4 秒錄音

      processor.onaudioprocess = (e) => {
        try {
          const input = e.inputBuffer.getChannelData(0);

          // float32 -> int16 PCM，小端
          const pcm16 = new Int16Array(input.length);
          for (let i = 0; i < input.length; i++) {
            let s = Math.max(-1, Math.min(1, input[i]));
            pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
          }

          const bytes = new Uint8Array(pcm16.buffer);
          const b64 = btoa(String.fromCharCode(...bytes));

          this.ws.send({ type: 'audio_chunk', pcm16_base64: b64 });

          collectedMs += (input.length / 16000) * 1000;
          this.updateStatus(`錄製中… ${(collectedMs/1000).toFixed(1)}s / 4.0s`);

          if (collectedMs >= targetMs) {
            // 停止錄音
            this.stopRecording(processor, source, stream);
          }
        } catch (error) {
          console.error('音頻處理錯誤:', error);
        }
      };

    } catch (error) {
      console.error('語音登入啟動失敗:', error);
      this.updateStatus('無法取得麥克風權限');

      if (window.UIStateManager?.showError) {
        window.UIStateManager.showError('無法啟動語音登入：麥克風不可用');
      }
    }
  }

  // 停止錄音
  stopRecording(processor, source, stream) {
    processor.disconnect();

    try {
      source.disconnect();
    } catch(e) {
      console.warn('斷開音頻源失敗:', e);
    }

    try {
      stream.getTracks().forEach(track => track.stop());
    } catch(e) {
      console.warn('停止音頻軌道失敗:', e);
    }

    this.ws.send({ type: 'audio_stop' });
    this.isRecording = false;
  }

  // 更新狀態顯示
  updateStatus(message) {
    const statusEl = document.getElementById('voice-login-status');
    if (statusEl) {
      statusEl.textContent = message;
    }
  }
}

console.log('✅ Bloom Ware WebSocket 模組已載入');