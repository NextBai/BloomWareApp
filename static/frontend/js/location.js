

let watchId = null;
let lastPosition = null;
let lastSentPosition = null;  // 上次發送的位置
let lastSendTime = 0;         // 上次發送時間
let isTracking = false;

const MIN_SEND_INTERVAL = 60000;  // 最小發送間隔：60 秒
const MIN_DISTANCE_CHANGE = 100;  // 最小距離變化：100 米

async function startLocationTracking() {
  if (isTracking) {
    return;
  }

  if (!navigator.geolocation) {
    console.warn('⚠️ 此瀏覽器不支援定位功能');
    return;
  }


  try {
    const position = await new Promise((resolve, reject) => {
      navigator.geolocation.getCurrentPosition(resolve, reject, {
        enableHighAccuracy: false, // 不需要高精度（省電）
        timeout: 10000,
        maximumAge: 60000 // 接受 1 分鐘內的快取位置
      });
    });

    handlePositionUpdate(position);

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

  } catch (error) {
    handlePositionError(error);
  }
}

function stopLocationTracking() {
  if (watchId !== null) {
    navigator.geolocation.clearWatch(watchId);
    watchId = null;
    isTracking = false;
  }
}

function calculateDistance(lat1, lon1, lat2, lon2) {
  const R = 6371000; // 地球半徑（米）
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(dLat/2) * Math.sin(dLat/2) +
            Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
            Math.sin(dLon/2) * Math.sin(dLon/2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
  return R * c;
}

function shouldSendUpdate(newPosition) {
  const now = Date.now();

  if (!lastSentPosition) return true;

  const timeSinceLast = now - lastSendTime;
  if (timeSinceLast < MIN_SEND_INTERVAL) return false;

  const distance = calculateDistance(
    lastSentPosition.lat, lastSentPosition.lon,
    newPosition.lat, newPosition.lon
  );

  return distance >= MIN_DISTANCE_CHANGE;
}

function handlePositionUpdate(position) {
  const { latitude, longitude, accuracy, heading, speed } = position.coords;
  const timestamp = position.timestamp;

  lastPosition = {
    lat: latitude,
    lon: longitude,
    accuracy: accuracy,
    heading: heading || 0,
    speed: speed || 0,
    timestamp: timestamp
  };

  if (shouldSendUpdate(lastPosition)) {
    sendEnvironmentSnapshot(lastPosition);
    lastSentPosition = { ...lastPosition };
    lastSendTime = Date.now();
  }
}

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

  sendEnvironmentSnapshot({
    lat: null,
    lon: null,
    error: errorMessage,
    timestamp: Date.now()
  });
}

function sendEnvironmentSnapshot(positionData) {
  if (!wsManager || !wsManager.isConnected()) {
    return; // 靜默跳過
  }

  const snapshot = {
    lat: positionData.lat,
    lon: positionData.lon,
    accuracy_m: positionData.accuracy,
    heading_deg: positionData.heading,
    speed: positionData.speed,
    timestamp: positionData.timestamp || Date.now(),
    tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
    locale: navigator.language,
    device: {
      user_agent: navigator.userAgent,
      platform: navigator.platform,
      screen_width: window.screen.width,
      screen_height: window.screen.height,
      viewport_width: window.innerWidth,
      viewport_height: window.innerHeight
    },
    error: positionData.error || null
  };

  wsManager.send({ type: 'env_snapshot', ...snapshot });
  if (window.DEBUG_MODE) {
  }
}

async function requestLocationUpdate() {
  if (!navigator.geolocation) {
    console.warn('⚠️ 此瀏覽器不支援定位功能');
    return null;
  }


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

function getLastKnownPosition() {
  return lastPosition;
}
