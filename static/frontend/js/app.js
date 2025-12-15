
async function handleGoogleLogin() {
  try {

    const response = await fetch('/auth/google/url');
    const data = await response.json();

    if (!data.success) {
      throw new Error(data.error || '獲取授權 URL 失敗');
    }


    sessionStorage.setItem('oauth_state', data.state);
    sessionStorage.setItem('oauth_code_verifier', data.code_verifier);


    window.location.href = data.auth_url;

  } catch (error) {
    console.error('❌ OAuth 初始化失敗:', error);
    alert('Google 登入初始化失敗，請稍後再試');
  }
}

async function checkLoginStatus() {
  const token = localStorage.getItem('jwt_token');
  if (!token) {
    window.location.href = '/login/';
    return false;
  }

  try {
    const payload = JSON.parse(atob(token.split('.')[1]));
    const currentTime = Math.floor(Date.now() / 1000);
    
    if (payload.exp && payload.exp < currentTime) {
      console.error('❌ Token 已過期，跳轉到登入頁面');
      localStorage.removeItem('jwt_token');
      window.location.href = '/login/';
      return false;
    }
    
  } catch (error) {
    console.error('❌ Token 解析失敗:', error);
    localStorage.removeItem('jwt_token');
    window.location.href = '/login/';
    return false;
  }

  initializeApp(token);
  return true;
}

async function initializeApp(token) {

  initLoginButton();
  initLogoutButton();
  initChatIcon();
  initEmotionSelector();
  initTranscriptControls();
  initToolCardControls();
  initAgentControls();
  initToolDrawer(); // 初始化工具抽屜

  syncToolMetadata();

  await requestRequiredPermissions();

  initializeWebSocket(token);

}

async function requestRequiredPermissions() {
  
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ 
      audio: { channelCount: 1, sampleRate: 48000 } 
    });
    stream.getTracks().forEach(track => track.stop());
  } catch (error) {
    console.warn('⚠️ 麥克風權限被拒絕:', error);
    if (typeof showErrorNotification === 'function') {
      showErrorNotification('需要麥克風權限才能使用語音功能，請在瀏覽器設定中允許');
    } else {
      alert('需要麥克風權限才能使用語音功能，請在瀏覽器設定中允許');
    }
  }

  if (navigator.geolocation) {
    try {
      await new Promise((resolve, reject) => {
        navigator.geolocation.getCurrentPosition(
          (position) => {
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

}


if (window.location.pathname.startsWith('/static')) {
  checkLoginStatus();
} else {
}




