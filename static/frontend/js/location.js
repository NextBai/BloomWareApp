// ========== 位置追蹤與環境感知 ==========

/**
 * 位置追蹤管理器
 * 負責：
 * 1. 請求瀏覽器定位權限
 * 2. 定期追蹤用戶位置
 * 3. 發送 env_snapshot 到後端
 */

let watchId = null;
let lastPosition = null;
let isTracking = false;

/**
 * 啟動位置追蹤
 */
async function startLocationTracking() {
  if (isTracking) {
    console.log('📍 位置追蹤已經在運行');
    return;
  }

  if (!navigator.geolocation) {
    console.warn('⚠️ 此瀏覽器不支援定位功能');
    return;
  }

  console.log('📍 請求位置權限...');

  try {
    // 首次獲取位置（觸發權限請求）
    const position = await new Promise((resolve, reject) => {
      navigator.geolocation.getCurrentPosition(resolve, reject, {
        enableHighAccuracy: false, // 不需要高精度（省電）
        timeout: 10000,
        maximumAge: 60000 // 接受 1 分鐘內的快取位置
      });
    });

    console.log('✅ 位置權限已授予');
    handlePositionUpdate(position);

    // 開始持續追蹤（每 30 秒更新一次）
    watchId = navigator.geolocation.watchPosition(
      handlePositionUpdate,
      handlePositionError,
      {
        enableHighAccuracy: false,
        timeout: 10000,
        maximumAge: 60000
      }
    );

    isTracking = true;
    console.log('📍 位置追蹤已啟動（每 30 秒更新）');

  } catch (error) {
    handlePositionError(error);
  }
}

/**
 * 停止位置追蹤
 */
function stopLocationTracking() {
  if (watchId !== null) {
    navigator.geolocation.clearWatch(watchId);
    watchId = null;
    isTracking = false;
    console.log('🛑 位置追蹤已停止');
  }
}

/**
 * 處理位置更新
 */
function handlePositionUpdate(position) {
  const { latitude, longitude, accuracy, heading, speed } = position.coords;
  const timestamp = position.timestamp;

  console.log('📍 位置更新:', {
    lat: latitude.toFixed(6),
    lon: longitude.toFixed(6),
    accuracy: Math.round(accuracy) + 'm'
  });

  lastPosition = {
    lat: latitude,
    lon: longitude,
    accuracy: accuracy,
    heading: heading || 0,
    speed: speed || 0,
    timestamp: timestamp
  };

  // 發送環境快照到後端
  sendEnvironmentSnapshot(lastPosition);
}

/**
 * 處理定位錯誤
 */
function handlePositionError(error) {
  let errorMessage = '';

  switch (error.code) {
    case error.PERMISSION_DENIED:
      errorMessage = '用戶拒絕定位權限';
      console.warn('⚠️ 位置權限被拒絕，部分功能（如查詢附近公車）將無法使用');
      break;
    case error.POSITION_UNAVAILABLE:
      errorMessage = '無法取得位置資訊';
      console.warn('⚠️ 位置資訊暫時無法取得');
      break;
    case error.TIMEOUT:
      errorMessage = '定位請求逾時';
      console.warn('⚠️ 定位請求逾時');
      break;
    default:
      errorMessage = '未知錯誤';
      console.warn('⚠️ 定位發生未知錯誤:', error);
  }

  // 即使定位失敗，也發送一個沒有位置的快照（包含時間等資訊）
  sendEnvironmentSnapshot({
    lat: null,
    lon: null,
    error: errorMessage,
    timestamp: Date.now()
  });
}

/**
 * 發送環境快照到後端
 * 欄位名稱需與後端 EnvironmentContextService 期望的一致
 */
function sendEnvironmentSnapshot(positionData) {
  if (!wsManager || !wsManager.isConnected()) {
    console.warn('⚠️ WebSocket 未連線，跳過環境快照發送');
    return;
  }

  // 構建環境快照資料（欄位名稱對應後端 context_service.py）
  const snapshot = {
    // 位置資訊（後端期望的欄位名稱）
    lat: positionData.lat,
    lon: positionData.lon,
    accuracy_m: positionData.accuracy,      // 後端期望 accuracy_m
    heading_deg: positionData.heading,      // 後端期望 heading_deg
    speed: positionData.speed,
    timestamp: positionData.timestamp || Date.now(),

    // 時區與語系（後端期望的欄位名稱）
    tz: Intl.DateTimeFormat().resolvedOptions().timeZone,  // 後端期望 tz
    locale: navigator.language,             // 後端期望 locale

    // 裝置資訊（後端期望 device 物件）
    device: {
      user_agent: navigator.userAgent,
      platform: navigator.platform,
      screen_width: window.screen.width,
      screen_height: window.screen.height,
      viewport_width: window.innerWidth,
      viewport_height: window.innerHeight
    },

    // 錯誤資訊（如果有）
    error: positionData.error || null
  };

  // 發送 WebSocket 訊息
  wsManager.send({
    type: 'env_snapshot',
    ...snapshot
  });

  console.log('📤 環境快照已發送:', {
    lat: snapshot.lat?.toFixed(6),
    lon: snapshot.lon?.toFixed(6),
    accuracy_m: snapshot.accuracy_m,
    tz: snapshot.tz
  });
}

/**
 * 手動觸發位置更新（用於用戶主動請求）
 */
async function requestLocationUpdate() {
  if (!navigator.geolocation) {
    console.warn('⚠️ 此瀏覽器不支援定位功能');
    return null;
  }

  console.log('📍 手動請求位置更新...');

  try {
    const position = await new Promise((resolve, reject) => {
      navigator.geolocation.getCurrentPosition(resolve, reject, {
        enableHighAccuracy: true, // 手動請求時使用高精度
        timeout: 10000,
        maximumAge: 0 // 不使用快取
      });
    });

    handlePositionUpdate(position);
    return lastPosition;

  } catch (error) {
    handlePositionError(error);
    return null;
  }
}

/**
 * 取得最後已知位置
 */
function getLastKnownPosition() {
  return lastPosition;
}
