// ========== 登入狀態檢查 ==========

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
    window.location.href = data.auth_url;

  } catch (error) {
    console.error('❌ OAuth 初始化失敗:', error);
    alert('Google 登入初始化失敗，請稍後再試');
  }
}

/**
 * 檢查登入狀態，未登入則導向 login.html
 */
async function checkLoginStatus() {
  const token = localStorage.getItem('jwt_token');
  if (!token) {
    // 未登入，導向登入頁面
    console.log('⚠️ 未登入，導向登入頁面...');
    window.location.href = '/login/';
    return false;
  }

  // 驗證 token 是否有效（解碼 JWT 檢查過期時間）
  try {
    const payload = JSON.parse(atob(token.split('.')[1]));
    const currentTime = Math.floor(Date.now() / 1000);
    
    if (payload.exp && payload.exp < currentTime) {
      console.error('❌ Token 已過期，跳轉到登入頁面');
      localStorage.removeItem('jwt_token');
      window.location.href = '/login/';
      return false;
    }
    
    console.log('✅ Token 有效，初始化應用...');
  } catch (error) {
    console.error('❌ Token 解析失敗:', error);
    localStorage.removeItem('jwt_token');
    window.location.href = '/login/';
    return false;
  }

  console.log('✅ 已登入，初始化應用...');
  initializeApp(token);
  return true;
}

/**
 * 初始化應用（登入後）
 */
async function initializeApp(token) {
  console.log('🚀 初始化應用...');

  // 初始化各個模組的事件監聽器
  initLoginButton();
  initLogoutButton();
  initChatIcon();
  initEmotionSelector();
  initTranscriptControls();
  initToolCardControls();
  initAgentControls();
  initToolDrawer(); // 初始化工具抽屜

  // 同步 MCP 工具 metadata
  syncToolMetadata();

  // 請求必要權限（麥克風 + 地理位置）
  await requestRequiredPermissions();

  // 初始化 WebSocket
  initializeWebSocket(token);

  console.log('✅ 應用初始化完成');
}

/**
 * 請求必要權限（麥克風 + 地理位置）
 */
async function requestRequiredPermissions() {
  console.log('🔐 請求必要權限...');
  
  // 1. 請求麥克風權限
  try {
    console.log('🎤 請求麥克風權限...');
    const stream = await navigator.mediaDevices.getUserMedia({ 
      audio: { channelCount: 1, sampleRate: 48000 } 
    });
    // 立即停止串流（只是為了觸發權限請求）
    stream.getTracks().forEach(track => track.stop());
    console.log('✅ 麥克風權限已授予');
  } catch (error) {
    console.warn('⚠️ 麥克風權限被拒絕:', error);
    if (typeof showErrorNotification === 'function') {
      showErrorNotification('需要麥克風權限才能使用語音功能，請在瀏覽器設定中允許');
    } else {
      alert('需要麥克風權限才能使用語音功能，請在瀏覽器設定中允許');
    }
  }

  // 2. 請求地理位置權限
  if (navigator.geolocation) {
    try {
      console.log('📍 請求地理位置權限...');
      await new Promise((resolve, reject) => {
        navigator.geolocation.getCurrentPosition(
          (position) => {
            console.log('✅ 地理位置權限已授予');
            resolve(position);
          },
          (error) => {
            console.warn('⚠️ 地理位置權限被拒絕:', error);
            reject(error);
          },
          { enableHighAccuracy: false, timeout: 10000, maximumAge: 0 }
        );
      });
    } catch (error) {
      console.warn('⚠️ 地理位置權限被拒絕，部分功能（如查詢附近公車）將無法使用');
      if (typeof showErrorNotification === 'function') {
        showErrorNotification('建議允許地理位置權限以使用完整功能（如查詢附近公車、天氣等）');
      }
    }
  } else {
    console.warn('⚠️ 此瀏覽器不支援地理位置功能');
  }

  console.log('✅ 權限請求完成');
}

// ========== 頁面初始化 ==========

// 只在聊天室頁面（/static/）執行登入檢查
console.log('📍 當前路徑:', window.location.pathname);
if (window.location.pathname.startsWith('/static')) {
  console.log('✅ 在聊天室頁面，執行登入檢查');
  checkLoginStatus();
} else {
  console.log('⏭️ 不在聊天室頁面，跳過登入檢查');
}

console.log('💡 WebSocket 整合已載入');
console.log('📝 部署時請執行: initializeWebSocket(your_jwt_token)');

// ========== 提示訊息 ==========
console.log('%c Bloom Ware 語音沉浸式 - 多層蓮花版', 'color: #16A34A; font-size: 16px; font-weight: bold;');
console.log('%c✨ 核心特色:\n- 8片蓮花瓣設計（clip-path 打造自然曲線）\n- 多層次花蕊（radial gradient + 光澤細節）\n- 花瓣中心脈絡增加真實感\n- 待機狀態：花瓣完全閉合（含苞待放）\n- Agent 思考中：8片花瓣順時針依序綻放\n- 斷線/重連：花瓣逆時針綻放變紅色警示\n- 錄音中：花蕊變紅脈衝，花瓣保持閉合\n- 品牌特色：優雅、精緻、現代', 'color: rgba(0,0,0,0.7); font-size: 12px;');


