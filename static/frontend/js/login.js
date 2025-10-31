// ========== Google OAuth PKCE 登入流程 ==========

/**
 * 生成 PKCE code_verifier 和 code_challenge
 */
async function generatePKCE() {
  // 生成符合 RFC 7636 規範的 code_verifier
  // 必須是 43-128 字元，只能包含 [A-Za-z0-9-._~]
  const array = new Uint8Array(32);
  crypto.getRandomValues(array);

  // 轉換為 base64url 格式（RFC 7636 要求）
  const base64 = btoa(String.fromCharCode(...array));
  const codeVerifier = base64
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=/g, '');

  // 計算 code_challenge = base64url(SHA256(code_verifier))
  const encoder = new TextEncoder();
  const data = encoder.encode(codeVerifier);
  const hashBuffer = await crypto.subtle.digest('SHA-256', data);

  // 轉換 hash 為 base64url
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  const hashBase64 = btoa(String.fromCharCode(...hashArray));
  const codeChallenge = hashBase64
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=/g, '');

  console.log('🔐 PKCE 生成:', {
    verifierLength: codeVerifier.length,
    challengeLength: codeChallenge.length
  });

  return { codeVerifier, codeChallenge };
}

/**
 * Google OAuth 登入（使用後端生成 PKCE）
 */
async function handleGoogleLogin() {
  try {
    console.log('🚀 開始 Google OAuth 登入流程...');

    // 從後端獲取授權 URL 和 PKCE 參數
    const response = await fetch('/auth/google/url');
    const data = await response.json();

    if (!data.success) {
      throw new Error(data.error || '獲取授權 URL 失敗');
    }

    console.log('✅ 獲取授權 URL 成功');

    // 存儲 PKCE 參數到 sessionStorage
    sessionStorage.setItem('oauth_state', data.state);
    sessionStorage.setItem('oauth_code_verifier', data.code_verifier);

    console.log('🔐 PKCE 參數已存儲:', {
      state: data.state.substring(0, 8) + '...',
      codeVerifier: data.code_verifier.substring(0, 8) + '...'
    });

    // 重定向到 Google 授權頁面
    console.log('🌐 重定向到 Google 授權頁面...');

    const inIframe = window.self !== window.top;
    if (inIframe) {
      // HuggingFace 主頁會以 iframe 方式載入 Space，直接跳轉會被瀏覽器阻擋
      window.open(data.auth_url, '_blank', 'noopener,noreferrer');
    } else {
      window.location.href = data.auth_url;
    }

  } catch (error) {
    console.error('❌ OAuth 初始化失敗:', error);
    alert('Google 登入初始化失敗，請稍後再試');
  }
}

/**
 * 處理 OAuth Callback
 */
async function handleOAuthCallback() {
  const urlParams = new URLSearchParams(window.location.search);
  const code = urlParams.get('code');
  const state = urlParams.get('state');

  if (!code || !state) return;

  // 嘗試讀取 state，若不存在則讓流程繼續改由後端驗證
  let savedState = null;
  try {
    savedState = sessionStorage.getItem('oauth_state');
  } catch (err) {
    console.warn('⚠️ 無法存取 sessionStorage:', err);
  }

  if (savedState && state !== savedState) {
    console.warn('⚠️ State 不匹配，可能是跨分頁或 session 過期，交給後端再次驗證');
  }

  try {
    // 取得 code_verifier（使用後端生成的）
    let codeVerifier = null;
    try {
      codeVerifier = sessionStorage.getItem('oauth_code_verifier');
    } catch (err) {
      console.warn('⚠️ 無法讀取 code_verifier:', err);
    }

    console.log('🔍 OAuth 回調驗證:', {
      hasCode: !!code,
      hasState: !!state,
      hasCodeVerifier: !!codeVerifier,
      stateMatch: savedState ? state === savedState : 'skip'
    });

    if (!codeVerifier) {
      console.error('❌ 缺少 code_verifier，可能是頁面刷新或 session 過期');
      alert('登入會話已過期，請重新登入');
      sessionStorage.clear();
      window.location.href = '/static/login.html';
      return;
    }

    console.log('📤 發送授權碼到後端...');

    // 調用後端交換 token
    const response = await fetch('/auth/google/callback', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        code: code,
        code_verifier: codeVerifier,
        state: state
      })
    });

    if (response.ok) {
      const data = await response.json();

      // 儲存 JWT token（後端返回 access_token）
      if (!data.access_token) {
        throw new Error('後端未返回 access_token');
      }
      localStorage.setItem('jwt_token', data.access_token);

      // 清理 sessionStorage
      sessionStorage.removeItem('oauth_code_verifier');
      sessionStorage.removeItem('oauth_state');

      console.log('✅ 登入成功！導向聊天室...');
      console.log('🔑 JWT Token 已存儲，長度:', data.access_token.length);

      // 導向聊天室
      window.location.href = '/static/index.html';
    } else {
      throw new Error('Token 交換失敗');
    }

  } catch (error) {
    console.error('❌ OAuth callback 處理失敗:', error);
    alert('登入失敗，請重新登入');
    window.location.href = '/static/login.html';
  }
}

// ========== iOS 設備檢測與權限管理 ==========

/**
 * 檢測是否為 iOS 設備
 */
function isIOSDevice() {
  const userAgent = navigator.userAgent || navigator.vendor || window.opera;
  
  // 檢測 iPhone/iPad/iPod
  const isIOS = /iPad|iPhone|iPod/.test(userAgent) && !window.MSStream;
  
  // 檢測 iPad on iOS 13+ (在桌面模式下)
  const isIPadOS = navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1;
  
  return isIOS || isIPadOS;
}

/**
 * iOS 設備權限請求管理器
 */
class IOSPermissionManager {
  constructor() {
    this.permissionsGranted = false;
    this.audioStream = null;
  }

  /**
   * 請求麥克風和揚聲器權限（使用原生 Safari 彈窗）
   */
  async requestPermissions() {
    if (this.permissionsGranted) {
      console.log('✅ iOS 權限已授予');
      return true;
    }

    try {
      console.log('🍎 檢測到 iOS 設備，請求原生權限...');

      // 使用原生的 getUserMedia API 請求麥克風權限
      // Safari 會自動顯示系統級別的權限彈窗
      this.audioStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        }
      });

      console.log('✅ iOS 麥克風權限已授予');

      // 測試音頻播放權限（揚聲器）
      // iOS 需要用戶互動才能播放音頻，但 getUserMedia 成功後通常就可以播放了
      try {
        const audioContext = new (window.AudioContext || window.webkitAudioContext)();
        await audioContext.resume();
        console.log('✅ iOS 音頻播放權限已授予');
        audioContext.close();
      } catch (err) {
        console.warn('⚠️ 音頻播放權限測試失敗（不影響麥克風功能）:', err);
      }

      this.permissionsGranted = true;

      // 顯示成功提示
      this.showPermissionStatus('✅ 權限已授予，可以使用語音功能', 'success');

      return true;

    } catch (error) {
      console.error('❌ iOS 權限請求失敗:', error);

      let errorMessage = '❌ 無法獲取麥克風權限';
      
      if (error.name === 'NotAllowedError') {
        errorMessage = '❌ 您拒絕了麥克風權限，請在 Safari 設定中允許';
      } else if (error.name === 'NotFoundError') {
        errorMessage = '❌ 未找到麥克風設備';
      } else if (error.name === 'NotReadableError') {
        errorMessage = '❌ 麥克風正在被其他應用使用';
      }

      this.showPermissionStatus(errorMessage, 'error');

      // 顯示詳細指引
      this.showIOSPermissionGuide();

      return false;
    }
  }

  /**
   * 顯示 iOS 權限設定指引
   */
  showIOSPermissionGuide() {
    const guide = `
📱 如何在 Safari 中啟用麥克風權限：

1. 開啟「設定」App
2. 下滑找到「Safari」
3. 點選「麥克風」
4. 選擇「詢問」或「允許」
5. 重新載入此頁面

或者：點擊網址列左側的「aA」圖示 → 網站設定 → 麥克風 → 允許
    `;

    // 在控制台顯示指引
    console.log(guide);

    // 可選：使用原生 alert 顯示（iOS 上更友善）
    if (confirm('無法獲取麥克風權限。是否查看設定指引？')) {
      alert(guide);
    }
  }

  /**
   * 顯示權限狀態訊息
   */
  showPermissionStatus(message, type = 'info') {
    // 尋找狀態顯示元素
    const statusElement = document.getElementById('iosPermissionStatus') || 
                         document.getElementById('voiceLoginStatus');
    
    if (statusElement) {
      statusElement.textContent = message;
      statusElement.style.display = 'block';
      statusElement.style.color = type === 'error' ? '#f5576c' :
                                  type === 'success' ? '#10b981' :
                                  'rgba(0,0,0,0.6)';

      // 成功訊息 3 秒後自動隱藏
      if (type === 'success') {
        setTimeout(() => {
          statusElement.style.display = 'none';
        }, 3000);
      }
    }
  }

  /**
   * 清理音頻流
   */
  cleanup() {
    if (this.audioStream) {
      this.audioStream.getTracks().forEach(track => track.stop());
      this.audioStream = null;
    }
  }
}

// 全域 iOS 權限管理器實例
const iosPermissionManager = new IOSPermissionManager();

// ========== 頁面初始化 ==========

// 檢查是否已登入
const token = localStorage.getItem('jwt_token');
if (token && !window.location.search.includes('code=')) {
  // 已登入，直接導向聊天室
  window.location.href = '/static/index.html';
}

// 檢查是否為 OAuth callback
if (window.location.search.includes('code=')) {
  handleOAuthCallback();
}

// iOS 設備自動請求權限
if (isIOSDevice()) {
  console.log('🍎 偵測到 iOS 設備');
  
  // 等待頁面完全載入後再請求權限
  window.addEventListener('load', async () => {
    // 延遲 500ms，確保 UI 完全載入
    setTimeout(async () => {
      console.log('🍎 自動請求 iOS 權限...');
      await iosPermissionManager.requestPermissions();
    }, 500);
  });
}

// ========== 語音登入功能 ==========

class VoiceLoginManager {
  constructor() {
    this.ws = null;
    this.audioContext = null;
    this.audioStream = null;
    this.audioProcessor = null;
    this.isRecording = false;
    this.chunkCount = 0; // 添加chunk計數器

    this.statusElement = document.getElementById('voiceLoginStatus');
    this.btnElement = document.getElementById('voiceLoginBtn');
    this.btnTextElement = document.getElementById('voiceLoginBtnText');
  }

  // 建立 WebSocket 連線（匿名，用於語音登入）
  async connectWebSocket() {
    return new Promise((resolve, reject) => {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${protocol}//${window.location.host}/ws?token=anonymous_voice_login`;

      console.log('🔌 建立語音登入 WebSocket:', wsUrl);

      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        console.log('✅ WebSocket 已連線');
        resolve();
      };

      this.ws.onerror = (error) => {
        console.error('❌ WebSocket 連線失敗:', error);
        reject(error);
      };

      this.ws.onmessage = (event) => {
        this.handleWebSocketMessage(JSON.parse(event.data));
      };

      // 10 秒超時
      setTimeout(() => reject(new Error('WebSocket 連線超時')), 10000);
    });
  }

  // 處理 WebSocket 訊息
  handleWebSocketMessage(data) {
    console.log('📩 收到訊息:', data.type);

    switch (data.type) {
      case 'voice_login_status':
        if (data.message === 'recording_started') {
          this.showStatus('🎙️ 開始錄音，請說話 5 秒...');
        }
        break;

      case 'voice_login_result':
        this.handleVoiceLoginResult(data);
        break;

      default:
        console.log('📩 收到其他訊息:', data);
    }
  }

  // 處理語音登入結果
  async handleVoiceLoginResult(data) {
    if (data.success) {
      console.log('✅ 語音登入成功！');
      console.log('👤 用戶:', data.user.name);
      console.log('😊 情緒:', data.emotion?.label);
      console.log('💬 歡迎詞:', data.welcome);

      // 成功僅提示登入完成，不在登入頁顯示歡迎詞
      this.showStatus('✅ 登入成功，正在跳轉…', 'success');

      // 模擬生成 JWT（實際應該從後端取得）
      // 這裡假設後端已經將 JWT 包含在 voice_login_result 中
      if (data.token) {
        localStorage.setItem('jwt_token', data.token);
      } else {
        console.warn('⚠️ 後端未返回 JWT');
      }

      // 將辨識到的情緒帶到聊天室主題（由 agent.js 啟動時套用）
      try {
        const emo = (data.emotion && (data.emotion.label || data.emotion)) || '';
        if (emo) localStorage.setItem('lastEmotion', String(emo));
      } catch (_) {}

      // 關閉 WS 與音訊資源，避免殘留
      try { this.ws && this.ws.readyState === WebSocket.OPEN && this.ws.close(1000, 'voice login done'); } catch(_) {}
      this.cleanup();

      // 快速跳轉到聊天室（縮短等待體感更順）
      setTimeout(() => {
        window.location.href = '/static/index.html';
      }, 800);

    } else {
      console.error('❌ 語音登入失敗:', data.error);
      if (data.detail) {
        console.error('🔍 語音登入錯誤細節:', data.detail);
      }

      let errorMsg = '語音登入失敗';
      switch (data.error) {
        case 'USER_NOT_BOUND':
          errorMsg = '❌ 語音未綁定！請先點擊上方 Google 登入按鈕登入，然後在聊天室中綁定您的語音';
          // 顯示額外的指引
          setTimeout(() => {
            this.showStatus('💡 步驟：1.Google登入 → 2.進入聊天室 → 3.說「綁定語音」或使用語音註冊功能', 'info');
          }, 3000);
          break;
        case 'LOW_SNR':
          errorMsg = '❌ 環境太吵或聲音太小，請重試';
          break;
        case 'AUDIO_TOO_SHORT':
          errorMsg = '❌ 錄音時間不足，請說話至少 5 秒';
          break;
        default:
          errorMsg = `❌ ${data.error || '未知錯誤'}`;
      }

      this.showStatus(errorMsg, 'error');
      this.stopRecording();
    }
  }

  // 開始錄音
  async startRecording() {
    try {
      this.showStatus('🔌 正在連線...');

      // 建立 WebSocket 連線
      await this.connectWebSocket();

      // iOS 設備檢查權限
      if (isIOSDevice()) {
        if (!iosPermissionManager.permissionsGranted) {
          console.log('🍎 iOS 設備需要先授權權限');
          this.showStatus('🍎 正在請求麥克風權限...', 'info');
          
          const granted = await iosPermissionManager.requestPermissions();
          if (!granted) {
            this.showStatus('❌ 權限未授予，無法使用語音登入', 'error');
            this.cleanup();
            return;
          }
        }
      }

      // 請求麥克風權限（iOS 已經在上面授權過了）
      this.audioStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true  // iOS 優化
        }
      });

      // 建立 AudioContext
      this.audioContext = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: 16000
      });

      const source = this.audioContext.createMediaStreamSource(this.audioStream);

      // 使用 ScriptProcessor 或 AudioWorklet
      if (this.audioContext.audioWorklet) {
        // 使用更現代的 AudioWorklet（暫時先用 ScriptProcessor）
        this.audioProcessor = this.audioContext.createScriptProcessor(4096, 1, 1);
      } else {
        this.audioProcessor = this.audioContext.createScriptProcessor(4096, 1, 1);
      }

      this.audioProcessor.onaudioprocess = (e) => {
        if (!this.isRecording) return;

        const inputData = e.inputBuffer.getChannelData(0);
        const pcm16 = this.float32ToPCM16(inputData);
        const base64 = this.arrayBufferToBase64(pcm16);

        // 發送音頻塊
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
          this.ws.send(JSON.stringify({
            type: 'audio_chunk',
            pcm16_base64: base64
          }));
          this.chunkCount++;
          console.log(`🎤 發送音頻chunk #${this.chunkCount}，大小: ${pcm16.byteLength} bytes`);
        } else {
          console.warn('⚠️ WebSocket未連接，無法發送音頻chunk');
        }
      };

      source.connect(this.audioProcessor);
      this.audioProcessor.connect(this.audioContext.destination);

      // 發送開始錄音訊號
      this.ws.send(JSON.stringify({
        type: 'audio_start',
        sample_rate: 16000
      }));

      this.isRecording = true;
      this.chunkCount = 0; // 重置chunk計數器
      this.btnElement.classList.add('recording');
      this.btnTextElement.textContent = '錄音中...（5 秒）';

      // 5 秒後自動停止（增加時間確保數據完整）
      setTimeout(() => {
        if (this.isRecording) {
          this.stopRecording();
        }
      }, 5000);

    } catch (error) {
      console.error('❌ 啟動錄音失敗:', error);
      
      // iOS 特定錯誤處理
      if (isIOSDevice()) {
        if (error.name === 'NotAllowedError') {
          this.showStatus('❌ 麥克風權限被拒絕，請檢查 Safari 設定', 'error');
          iosPermissionManager.showIOSPermissionGuide();
        } else {
          this.showStatus('❌ 無法啟動麥克風: ' + error.message, 'error');
        }
      } else {
        this.showStatus('❌ 無法啟動麥克風，請檢查權限', 'error');
      }
      
      this.cleanup();
    }
  }

  // 停止錄音
  stopRecording() {
    if (!this.isRecording) return;

    console.log(`🎤 停止錄音請求，共發送 ${this.chunkCount} 個音頻chunk`);

    // 先標記為停止錄音，但不立即清理資源
    this.isRecording = false;

    // 等待一小段時間，讓最後的音頻數據被處理完
    setTimeout(() => {
      console.log(`🎤 錄音完全結束，準備發送停止訊號`);

      this.btnElement.classList.remove('recording');
      this.btnTextElement.textContent = '使用語音登入';

      // 發送停止訊號
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({
          type: 'audio_stop',
          mode: 'voice_login'
        }));
      }

      this.showStatus('🔄 正在辨識身份與情緒...');

      // 清理音頻資源（延遲 1 秒，讓後端處理完）
      setTimeout(() => this.cleanup(), 1000);
    }, 200); // 等待200ms讓最後的chunk被處理
  }

  // 清理資源
  cleanup() {
    if (this.audioProcessor) {
      this.audioProcessor.disconnect();
      this.audioProcessor = null;
    }

    if (this.audioStream) {
      this.audioStream.getTracks().forEach(track => track.stop());
      this.audioStream = null;
    }

    if (this.audioContext && this.audioContext.state !== 'closed') {
      this.audioContext.close();
      this.audioContext = null;
    }
  }

  // Float32 轉 PCM16
  float32ToPCM16(float32Array) {
    const pcm16 = new Int16Array(float32Array.length);
    for (let i = 0; i < float32Array.length; i++) {
      const s = Math.max(-1, Math.min(1, float32Array[i]));
      pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    return pcm16.buffer;
  }

  // ArrayBuffer 轉 Base64
  arrayBufferToBase64(buffer) {
    let binary = '';
    const bytes = new Uint8Array(buffer);
    for (let i = 0; i < bytes.byteLength; i++) {
      binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary);
  }

  // 顯示狀態訊息
  showStatus(message, type = 'info') {
    this.statusElement.textContent = message;
    this.statusElement.style.display = 'block';
    this.statusElement.style.color = type === 'error' ? '#f5576c' :
                                      type === 'success' ? '#10b981' :
                                      'rgba(0,0,0,0.6)';
  }

  // 切換錄音狀態
  toggle() {
    if (this.isRecording) {
      this.stopRecording();
    } else {
      this.startRecording();
    }
  }
}

// 初始化語音登入管理器
const voiceLoginManager = new VoiceLoginManager();

// 註冊登入按鈕事件
document.getElementById('googleLoginBtn').addEventListener('click', handleGoogleLogin);
document.getElementById('voiceLoginBtn').addEventListener('click', () => {
  voiceLoginManager.toggle();
});

console.log('🪷 Bloom Ware 登入頁面已載入（含語音登入）');
