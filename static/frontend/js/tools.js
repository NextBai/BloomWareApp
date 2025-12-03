// ========== 工具卡片管理（改良版：支援抽屜面板）==========

const positions = ['pos-top-right', 'pos-top-left', 'pos-bottom-right', 'pos-bottom-left'];
let usedPositions = [];
const MAX_CARDS = 4;

// 抽屜相關元素
let toolDrawer = null;
let toolDrawerToggle = null;
let toolDrawerContent = null;
let toolDrawerOverlay = null;
let toolDrawerClose = null;
let isDrawerOpen = false;

/**
 * 初始化工具抽屜
 */
function initToolDrawer() {
  toolDrawer = document.getElementById('toolDrawer');
  toolDrawerToggle = document.getElementById('toolDrawerToggle');
  toolDrawerContent = document.getElementById('toolDrawerContent');
  toolDrawerOverlay = document.getElementById('toolDrawerOverlay');
  toolDrawerClose = document.getElementById('toolDrawerClose');

  if (!toolDrawer || !toolDrawerToggle) {
    console.warn('⚠️ 工具抽屜元素未找到');
    return;
  }

  // 綁定切換按鈕事件
  toolDrawerToggle.addEventListener('click', toggleToolDrawer);

  // 綁定關閉按鈕事件
  if (toolDrawerClose) {
    toolDrawerClose.addEventListener('click', hideToolDrawer);
  }

  // 綁定遮罩層點擊關閉
  if (toolDrawerOverlay) {
    toolDrawerOverlay.addEventListener('click', hideToolDrawer);
  }

  console.log('✅ 工具抽屜已初始化');
}

/**
 * 顯示工具抽屜切換按鈕（有工具結果時調用）
 */
function showToolDrawerToggle() {
  if (toolDrawerToggle) {
    toolDrawerToggle.classList.add('visible');
    console.log('📊 工具抽屜按鈕已顯示');
  }
}

/**
 * 隱藏工具抽屜切換按鈕
 */
function hideToolDrawerToggle() {
  if (toolDrawerToggle) {
    toolDrawerToggle.classList.remove('visible');
    toolDrawerToggle.classList.remove('open');
  }
}

/**
 * 切換工具抽屜開關
 */
function toggleToolDrawer() {
  if (isDrawerOpen) {
    hideToolDrawer();
  } else {
    showToolDrawer();
  }
}

/**
 * 打開工具抽屜
 */
function showToolDrawer() {
  if (toolDrawer) {
    toolDrawer.classList.add('open');
    toolDrawerToggle?.classList.add('open');
    toolDrawerOverlay?.classList.add('visible');
    isDrawerOpen = true;
    console.log('📂 工具抽屜已打開');
  }
}

/**
 * 關閉工具抽屜
 */
function hideToolDrawer() {
  if (toolDrawer) {
    toolDrawer.classList.remove('open');
    toolDrawerToggle?.classList.remove('open');
    toolDrawerOverlay?.classList.remove('visible');
    isDrawerOpen = false;
    console.log('📁 工具抽屜已關閉');
  }
}

/**
 * 隱藏工具卡片（下一個請求或關懷模式時調用）
 */
function hideToolCards() {
  // 隱藏抽屜
  hideToolDrawer();
  // 隱藏切換按鈕
  hideToolDrawerToggle();
  // 清空抽屜內容
  if (toolDrawerContent) {
    toolDrawerContent.innerHTML = '';
  }
  // 清空桌面端卡片容器
  clearAllCards();
  console.log('🗑️ 工具卡片已隱藏');
}

function getNextPosition() {
  // 如果卡片數量已達上限，不允許新增
  if (usedPositions.length >= MAX_CARDS) {
    console.warn('⚠️ 卡片數量已達上限（4張），請先清除現有卡片');
    return null;
  }

  for (const pos of positions) {
    if (!usedPositions.includes(pos)) {
      usedPositions.push(pos);
      return pos;
    }
  }
  return null;
}

function addToolCard(type) {
  const position = getNextPosition();

  // 如果沒有可用位置，直接返回
  if (!position) {
    return;
  }

  const card = document.createElement('div');
  card.className = `voice-tool-card ${position}`;
  card.dataset.type = type;

  if (type === 'weather') {
    card.innerHTML = `
      <div class="card-header">
        <div class="card-icon">🌤️</div>
        <h3>台北天氣</h3>
      </div>
      <div class="card-content">
        <div class="data-row">
          <span class="data-label">溫度</span>
          <span class="data-value">23°C</span>
        </div>
        <div class="data-row">
          <span class="data-label">狀況</span>
          <span class="data-value">晴朗</span>
        </div>
        <div class="data-row">
          <span class="data-label">濕度</span>
          <span class="data-value">65%</span>
        </div>
      </div>
    `;
  } else if (type === 'news') {
    card.innerHTML = `
      <div class="card-header">
        <div class="card-icon">📰</div>
        <h3>今日科技新聞</h3>
      </div>
      <div class="card-content">
        <div class="data-row">
          <span style="font-size: 13px; line-height: 1.6;">
            • OpenAI 發布新模型<br>
            • 蘋果推出 Vision Pro 2<br>
            • 台積電宣布 2nm 製程
          </span>
        </div>
      </div>
    `;
  } else if (type === 'health') {
    card.innerHTML = `
      <div class="card-header">
        <div class="card-icon">❤️</div>
        <h3>健康數據</h3>
      </div>
      <div class="card-content">
        <div class="data-row">
          <span class="data-label">心率</span>
          <span class="data-value">72 bpm</span>
        </div>
        <div class="data-row">
          <span class="data-label">步數</span>
          <span class="data-value">8,542</span>
        </div>
        <div class="data-row">
          <span class="data-label">血氧</span>
          <span class="data-value">98%</span>
        </div>
      </div>
    `;
  }

  cardsContainer.appendChild(card);
}

function clearAllCards() {
  const cards = cardsContainer.querySelectorAll('.voice-tool-card');
  cards.forEach(card => {
    card.classList.add('exiting');
    setTimeout(() => card.remove(), 300);
  });
  usedPositions = [];
}

// 模擬工具調用事件監聽（延遲初始化）
function initToolCardControls() {
  document.getElementById('simulate-weather').addEventListener('click', () => {
    clearAllCards();
    setTimeout(() => addToolCard('weather'), 100);
  });

  document.getElementById('simulate-news').addEventListener('click', () => {
    clearAllCards();
    setTimeout(() => addToolCard('news'), 100);
  });

  document.getElementById('simulate-health').addEventListener('click', () => {
    clearAllCards();
    setTimeout(() => addToolCard('health'), 100);
  });

  document.getElementById('simulate-next-input').addEventListener('click', () => {
    clearAllCards();
    transcript.textContent = '請說話...';
    transcript.className = 'voice-transcript provisional';
  });
}

// ========== MCP 工具 Metadata 同步 ==========

/**
 * 從後端同步工具 metadata
 */
async function syncToolMetadata() {
  try {
    const response = await fetch('/api/mcp/tools', {
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('jwt_token')}`
      }
    });

    if (response.ok) {
      const data = await response.json();
      if (data.success && data.tools) {
        // 將工具 metadata 儲存到全域變數（定義在 config.js）
        toolsMetadata = {};
        data.tools.forEach(tool => {
          toolsMetadata[tool.name] = tool;
        });
        console.log(`✅ 同步 ${data.count} 個 MCP 工具 metadata`);
      }
    }
  } catch (error) {
    console.error('❌ 同步工具 metadata 失敗:', error);
  }
}

/**
 * 根據分類/工具名稱自動分配圖示
 */
function getIconForTool(toolName, category) {
  const iconMap = {
    // 分類映射
    '健康': '❤️',
    '天氣': '🌤️',
    '新聞': '📰',
    '匯率': '💱',
    '時間': '⏰',
    '提醒': '⏰',
    '日曆': '📅',
    '音樂': '🎵',
    '地圖': '🗺️',
    '翻譯': '🌐',
    '計算': '🔢',
    '道路運輸': '🚌',
    '軌道運輸': '🚇',
    '地理定位': '📍',

    // 工具名稱映射
    'healthkit_query': '❤️',
    'weather_query': '🌤️',
    'news_query': '📰',
    'exchange_rate': '💱',
    'time_query': '⏰',
    'reminder': '⏰',
    'calendar': '📅',
    'tdx_bus_arrival': '🚌',
    'tdx_metro': '🚇',
    'reverse_geocode': '📍',
    'forward_geocode': '📍',
    'directions': '🗺️'
  };

  // 優先使用工具名稱匹配
  if (iconMap[toolName]) {
    return iconMap[toolName];
  }

  // 其次使用分類匹配
  if (category && iconMap[category]) {
    return iconMap[category];
  }

  // 預設圖示
  return '🔧';
}

/**
 * 動態顯示工具卡片（通用版本，支援所有 MCP 工具）
 * 優先渲染到抽屜面板（手機端），同時保留桌面端卡片
 */
function displayToolCard(toolName, toolData) {
  // 清除舊卡片
  clearAllCards();

  // 獲取工具 metadata
  const toolMeta = toolsMetadata[toolName] || {};
  const category = toolMeta.category || '未知';
  const icon = getIconForTool(toolName, category);

  // 渲染卡片內容（處理後的結果，非 raw data）
  const contentHTML = renderCardContent(toolName, toolData);

  // 創建卡片元素
  const card = document.createElement('div');
  card.className = 'voice-tool-card';
  card.dataset.type = toolName;

  card.innerHTML = `
    <div class="card-header">
      <div class="card-icon">${icon}</div>
      <h3>${category}</h3>
    </div>
    <div class="card-content" style="max-height: 300px; overflow-y: auto; overflow-x: hidden; padding-right: 8px;">${contentHTML}</div>
  `;

  // 渲染到抽屜面板
  if (toolDrawerContent) {
    toolDrawerContent.innerHTML = '';
    toolDrawerContent.appendChild(card.cloneNode(true));
    // 顯示抽屜切換按鈕
    showToolDrawerToggle();
    console.log(`📊 工具卡片已渲染到抽屜: ${toolName} (${category})`);
  }

  // 同時渲染到桌面端卡片容器（保留原有邏輯）
  const position = getNextPosition();
  if (position && cardsContainer) {
    card.classList.add(position);
    cardsContainer.appendChild(card);
    console.log(`🃏 工具卡片已渲染到桌面: ${toolName} (${category})`);
  }
}

/**
 * 根據工具數據結構自動渲染內容
 */
function renderCardContent(toolName, toolData) {
  console.log('🔍 renderCardContent 被調用:', {toolName, toolData});
  
  if (!toolData) {
    console.warn('⚠️ toolData 為空');
    return '<p class="data-row">無數據</p>';
  }

  // 模式 1：health_data 陣列（直接或在 raw_data 中）
  const healthData = toolData.health_data || toolData.raw_data?.health_data;
  if (healthData && Array.isArray(healthData)) {
    console.log('✅ 匹配到模式 1: health_data');
    return renderHealthMetrics(healthData);
  }

  // 模式 2：articles 陣列（直接或在 raw_data 中）
  const articlesData = toolData.articles || toolData.raw_data?.articles;
  if (articlesData && Array.isArray(articlesData)) {
    console.log('✅ 匹配到模式 2: articles');
    return renderNewsList(articlesData);
  }

  // 模式 3：天氣數據（直接檢查，無論是否包在 raw_data 中）
  const weatherData = toolData.raw_data || toolData;
  if (weatherData.main && weatherData.weather) {
    console.log('✅ 匹配到模式 3: 天氣數據');
    return renderWeatherData(weatherData);
  }

  // 模式 4：公車到站資訊
  if (toolData.arrivals && Array.isArray(toolData.arrivals)) {
    console.log('✅ 匹配到模式 4: 公車到站資訊');
    return renderBusArrivals(toolData.arrivals, toolData.route_name);
  }

  // 模式 5：附近公車站點
  if (toolData.stops && Array.isArray(toolData.stops)) {
    console.log('✅ 匹配到模式 5: 附近公車站點');
    return renderNearbyStops(toolData.stops);
  }

  // 模式 6：匯率數據（直接或在 raw_data 中）
  const exchangeData = toolData.raw_data || toolData;
  if (exchangeData.rate !== undefined && exchangeData.from_currency !== undefined) {
    console.log('✅ 匹配到模式 6: 匯率數據');
    return renderExchangeRate(exchangeData);
  }

  // 模式 7：火車列車資訊
  if (toolData.trains && Array.isArray(toolData.trains)) {
    console.log('✅ 匹配到模式 7: 火車列車資訊');
    return renderTrainList(toolData.trains);
  }

  // 模式 8：YouBike 站點資訊（需要確認是 YouBike 工具）
  if (toolData.stations && Array.isArray(toolData.stations) && 
      (toolName === 'tdx_youbike' || toolData.stations[0]?.available_bikes !== undefined)) {
    console.log('✅ 匹配到模式 8: YouBike 站點資訊');
    return renderYouBikeStations(toolData.stations);
  }
  
  // 模式 8.5：火車站點資訊（tdx_train 的 stations）
  if (toolData.stations && Array.isArray(toolData.stations) && toolName === 'tdx_train') {
    console.log('✅ 匹配到模式 8.5: 火車站點資訊');
    return renderTrainStations(toolData.stations);
  }

  // 模式 9：地理反查資訊（reverse_geocode）
  if (toolData.display_name && toolData.lat && toolData.lon && toolName === 'reverse_geocode') {
    console.log('✅ 匹配到模式 9: 地理反查資訊');
    return renderReverseGeocode(toolData);
  }

  // 模式 10：導航路線（directions）
  if ((toolData.distance_m !== undefined || toolData.duration_s !== undefined) && 
      (toolName === 'directions' || toolData.polyline !== undefined)) {
    console.log('✅ 匹配到模式 10: 導航路線');
    return renderDirections(toolData);
  }

  // 模式 11：捷運到站資訊（tdx_metro arrivals）
  if (toolData.arrivals && Array.isArray(toolData.arrivals) && toolName === 'tdx_metro') {
    console.log('✅ 匹配到模式 11: 捷運到站資訊');
    return renderMetroArrivals(toolData.arrivals);
  }

  // 模式 12：捷運站點資訊（tdx_metro stations）
  if (toolData.stations && Array.isArray(toolData.stations) && toolName === 'tdx_metro') {
    console.log('✅ 匹配到模式 12: 捷運站點資訊');
    return renderMetroStations(toolData.stations);
  }

  // 模式 13：正向地理編碼（forward_geocode）
  if (toolData.lat && toolData.lon && toolData.display_name && toolName === 'forward_geocode') {
    console.log('✅ 匹配到模式 13: 正向地理編碼');
    return renderForwardGeocode(toolData);
  }

  // 模式 14：通用 raw_data 物件
  if (toolData.raw_data && typeof toolData.raw_data === 'object') {
    console.log('✅ 匹配到模式 14: 通用 raw_data');
    return renderKeyValuePairs(toolData.raw_data);
  }

  // Fallback：顯示 JSON
  console.warn('⚠️ 未匹配任何模式，使用 JSON fallback');
  console.log('📋 toolData 結構:', Object.keys(toolData));
  return renderJSONFallback(toolData);
}

/**
 * 渲染天氣數據
 */
function renderWeatherData(data) {
  const main = data.main || {};
  const weather = data.weather?.[0] || {};
  const wind = data.wind || {};
  const sys = data.sys || {};
  
  // 格式化時間
  const formatTime = (timestamp) => {
    if (!timestamp) return '--:--';
    const date = new Date(timestamp * 1000);
    return date.toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' });
  };
  
  return `
    <div class="data-row">
      <span class="data-label">🌡️ 溫度</span>
      <span class="data-value">${main.temp?.toFixed(1) || '--'}°C</span>
    </div>
    <div class="data-row">
      <span class="data-label">🤔 體感</span>
      <span class="data-value">${main.feels_like?.toFixed(1) || '--'}°C</span>
    </div>
    <div class="data-row">
      <span class="data-label">☁️ 狀況</span>
      <span class="data-value">${weather.description || '--'}</span>
    </div>
    <div class="data-row">
      <span class="data-label">💧 濕度</span>
      <span class="data-value">${main.humidity || '--'}%</span>
    </div>
    <div class="data-row">
      <span class="data-label">🌪️ 風速</span>
      <span class="data-value">${wind.speed?.toFixed(1) || '--'} m/s</span>
    </div>
    <div class="data-row">
      <span class="data-label">📊 氣壓</span>
      <span class="data-value">${main.pressure || '--'} hPa</span>
    </div>
    <div class="data-row">
      <span class="data-label">🌅 日出</span>
      <span class="data-value">${formatTime(sys.sunrise)}</span>
    </div>
    <div class="data-row">
      <span class="data-label">🌇 日落</span>
      <span class="data-value">${formatTime(sys.sunset)}</span>
    </div>
  `;
}

/**
 * 渲染健康指標
 */
function renderHealthMetrics(healthData) {
  if (!healthData || healthData.length === 0) {
    return '<p class="data-row">無健康數據</p>';
  }

  const metricNames = {
    heart_rate: '❤️ 心率',
    step_count: '👟 步數',
    oxygen_level: '🫁 血氧',
    respiratory_rate: '💨 呼吸',
    sleep_analysis: '😴 睡眠'
  };

  const metricIcons = {
    heart_rate: '❤️',
    step_count: '👟',
    oxygen_level: '🫁',
    respiratory_rate: '💨',
    sleep_analysis: '😴'
  };

  // 按指標類型分組
  const grouped = {};
  healthData.forEach(item => {
    const metric = item.metric || item.type;
    if (!grouped[metric]) {
      grouped[metric] = [];
    }
    grouped[metric].push(item);
  });

  let html = '<div class="health-metrics">';

  // 渲染每種指標
  Object.entries(grouped).forEach(([metric, items], index) => {
    const icon = metricIcons[metric] || '📊';
    const label = metricNames[metric]?.replace(/^.+\s/, '') || metric;
    const latestItem = items[0]; // 最新的數據
    const value = latestItem.value;
    const unit = latestItem.unit || '';
    
    // 格式化時間
    let timeStr = '';
    if (latestItem.timestamp) {
      try {
        const date = new Date(latestItem.timestamp);
        timeStr = date.toLocaleString('zh-TW', { 
          month: 'numeric', 
          day: 'numeric', 
          hour: '2-digit', 
          minute: '2-digit' 
        });
      } catch (e) {
        timeStr = '';
      }
    }

    html += `
      <div class="health-metric-item" style="border-bottom: 1px solid #eee; padding: 10px 0; ${index === Object.keys(grouped).length - 1 ? 'border-bottom: none;' : ''}">
        <div class="data-row">
          <span class="data-label">${icon} ${label}</span>
          <span class="data-value" style="font-weight: bold;">${value} ${unit}</span>
        </div>
        ${timeStr ? `
        <div class="data-row" style="opacity: 0.7;">
          <span class="data-label" style="font-size: 0.85em;">記錄時間</span>
          <span class="data-value" style="font-size: 0.85em;">${timeStr}</span>
        </div>
        ` : ''}
        ${items.length > 1 ? `
        <div class="data-row" style="opacity: 0.6;">
          <span class="data-label" style="font-size: 0.8em;">平均值</span>
          <span class="data-value" style="font-size: 0.8em;">${(items.reduce((sum, i) => sum + i.value, 0) / items.length).toFixed(1)} ${unit}</span>
        </div>
        ` : ''}
      </div>
    `;
  });

  html += '</div>';
  return html;
}

/**
 * 渲染新聞列表
 */
function renderNewsList(articles) {
  let html = '';
  articles.slice(0, 3).forEach(article => {
    html += `
      <div class="data-row" style="flex-direction: column; align-items: flex-start; margin-bottom: 10px;">
        <span class="data-label" style="font-weight: bold;">${article.title || '無標題'}</span>
        <span class="data-value" style="font-size: 0.85em; opacity: 0.8;">${article.source?.name || article.source || ''}</span>
      </div>
    `;
  });

  return html || '<p>無新聞</p>';
}

/**
 * 渲染鍵值對（天氣等）
 */
function renderKeyValuePairs(data) {
  const keyMap = {
    city: '城市',
    temp: '溫度',
    temperature: '溫度',
    condition: '狀況',
    weather: '天氣',
    humidity: '濕度',
    wind_speed: '風速',
    description: '描述'
  };

  let html = '';
  for (const [key, value] of Object.entries(data)) {
    if (typeof value === 'object') continue; // 跳過巢狀物件

    const label = keyMap[key] || key;
    let displayValue = value;

    // 特殊處理溫度
    if (key.includes('temp') && typeof value === 'number') {
      displayValue = `${value}°C`;
    }

    html += `
      <div class="data-row">
        <span class="data-label">${label}</span>
        <span class="data-value">${displayValue}</span>
      </div>
    `;
  }

  return html || '<p>無數據</p>';
}

/**
 * 渲染匯率資訊
 */
/**
 * 渲染匯率信息
 */
function renderExchangeRate(data) {
  const currencySymbols = {
    "USD": "$", "TWD": "NT$", "JPY": "¥", "EUR": "€", 
    "GBP": "£", "CNY": "¥", "KRW": "₩", "HKD": "HK$"
  };
  
  const fromCurrency = data.from_currency || "USD";
  const toCurrency = data.to_currency || "TWD";
  const fromSymbol = currencySymbols[fromCurrency] || fromCurrency;
  const toSymbol = currencySymbols[toCurrency] || toCurrency;
  
  let html = '';

  // 匯率
  if (data.rate !== undefined) {
    html += `
      <div class="data-row">
        <span class="data-label">💰 匯率</span>
        <span class="data-value">1 ${fromCurrency} = ${data.rate.toFixed(4)} ${toCurrency}</span>
      </div>
    `;
  }

  // 轉換金額
  if (data.amount && data.converted_amount !== undefined) {
    html += `
      <div class="data-row">
        <span class="data-label">🔄 轉換</span>
        <span class="data-value">${fromSymbol}${data.amount.toFixed(2)} = ${toSymbol}${data.converted_amount.toFixed(2)}</span>
      </div>
    `;
  }
  
  // 查詢時間
  if (data.raw_data?.metadata?.timestamp) {
    const time = new Date(data.raw_data.metadata.timestamp).toLocaleString('zh-TW');
    html += `
      <div class="data-row">
        <span class="data-label">⏰ 時間</span>
        <span class="data-value">${time}</span>
      </div>
    `;
  }

  return html || '<p>無匯率數據</p>';
}

/**
 * 渲染火車列車資訊
 */
function renderTrainList(trains) {
  if (!trains || trains.length === 0) {
    return '<p class="data-row">查無列車資訊</p>';
  }

  let html = '<div class="train-list">';

  trains.forEach((train, index) => {
    const trainType = train.train_type || '未知';
    const trainNo = train.train_no || '---';
    const departTime = train.departure_time ? train.departure_time.substring(0, 5) : '--:--';
    const arriveTime = train.arrival_time ? train.arrival_time.substring(0, 5) : '--:--';
    const duration = train.duration_min ? `${train.duration_min}分鐘` : '未知';
    const originStation = train.origin_station || '未知';
    const destStation = train.destination_station || '未知';

    html += `
      <div class="train-item" style="border-bottom: 1px solid #eee; padding: 12px 0; ${index === trains.length - 1 ? 'border-bottom: none;' : ''}">
        <div class="data-row" style="margin-bottom: 8px;">
          <span class="data-label" style="font-weight: bold; color: #0066cc;">🚂 ${trainType} ${trainNo}次</span>
        </div>
        <div class="data-row">
          <span class="data-label">📍 起訖站</span>
          <span class="data-value">${originStation} → ${destStation}</span>
        </div>
        <div class="data-row">
          <span class="data-label">⏰ 出發</span>
          <span class="data-value">${departTime}</span>
        </div>
        <div class="data-row">
          <span class="data-label">⏱️ 抵達</span>
          <span class="data-value">${arriveTime}</span>
        </div>
        <div class="data-row">
          <span class="data-label">🕐 行駛時間</span>
          <span class="data-value">${duration}</span>
        </div>
      </div>
    `;
  });

  html += '</div>';
  return html;
}

/**
 * 渲染火車站點資訊
 */
function renderTrainStations(stations) {
  if (!stations || stations.length === 0) {
    return '<p class="data-row">查無車站資訊</p>';
  }

  let html = '<div class="station-list">';

  stations.forEach((station, index) => {
    const stationName = station.station_name || station.name || '未知車站';
    const distance = station.distance_m ? `${Math.round(station.distance_m)}公尺` : '';
    const walkTime = station.walking_time_min ? `步行約${station.walking_time_min}分鐘` : '';

    html += `
      <div class="station-item" style="border-bottom: 1px solid #eee; padding: 12px 0; ${index === stations.length - 1 ? 'border-bottom: none;' : ''}">
        <div class="data-row" style="margin-bottom: 4px;">
          <span class="data-label" style="font-weight: bold; color: #0066cc;">🚉 ${stationName}</span>
        </div>
        ${distance ? `
        <div class="data-row">
          <span class="data-label">📏 距離</span>
          <span class="data-value">${distance}</span>
        </div>
        ` : ''}
        ${walkTime ? `
        <div class="data-row">
          <span class="data-label">🚶 步行時間</span>
          <span class="data-value">${walkTime}</span>
        </div>
        ` : ''}
      </div>
    `;
  });

  html += '</div>';
  return html;
}

/**
 * 渲染 YouBike 站點資訊
 */
function renderYouBikeStations(stations) {
  if (!stations || stations.length === 0) {
    return '<p class="data-row">附近無 YouBike 站點</p>';
  }

  let html = '<div class="youbike-list">';

  stations.forEach((station, index) => {
    const stationName = station.station_name || '未知站點';
    const availableBikes = station.available_bikes ?? 0;
    const availableSpaces = station.available_spaces ?? 0;
    const distance = station.distance_m || 0;
    const walkingTime = station.walking_time_min || 0;
    const bikeType = station.bike_type || 'YouBike';
    const serviceStatus = station.service_status === 1 ? '營運中' : '暫停服務';

    // 可借車輛狀態：0 = 紅色，1-3 = 橘色，>3 = 綠色
    let bikeStatusColor = '#e74c3c'; // 紅色
    let bikeStatusIcon = '🚫';
    if (availableBikes > 3) {
      bikeStatusColor = '#27ae60'; // 綠色
      bikeStatusIcon = '✅';
    } else if (availableBikes > 0) {
      bikeStatusColor = '#f39c12'; // 橘色
      bikeStatusIcon = '⚠️';
    }

    html += `
      <div class="youbike-item" style="border-bottom: 1px solid #eee; padding: 12px 0; ${index === stations.length - 1 ? 'border-bottom: none;' : ''}">
        <div class="data-row" style="margin-bottom: 8px;">
          <span class="data-label" style="font-weight: bold; color: #e67e22;">🚲 ${stationName}</span>
        </div>
        <div class="data-row">
          <span class="data-label">📍 距離</span>
          <span class="data-value">${distance}m (步行約 ${walkingTime} 分鐘)</span>
        </div>
        <div class="data-row">
          <span class="data-label">🚴 可借車輛</span>
          <span class="data-value" style="color: ${bikeStatusColor}; font-weight: bold;">${bikeStatusIcon} ${availableBikes} 輛</span>
        </div>
        <div class="data-row">
          <span class="data-label">🅿️ 可還空位</span>
          <span class="data-value">${availableSpaces} 個</span>
        </div>
        <div class="data-row">
          <span class="data-label">ℹ️ 類型</span>
          <span class="data-value">${bikeType} (${serviceStatus})</span>
        </div>
      </div>
    `;
  });

  html += '</div>';
  return html;
}

/**
 * 渲染公車到站資訊
 */
function renderBusArrivals(arrivals, routeName) {
  if (!arrivals || arrivals.length === 0) {
    return '<p>目前無到站資訊</p>';
  }

  let html = '';
  
  // 按站點分組
  const stopGroups = {};
  arrivals.forEach(arr => {
    const stopName = arr.stop_name || '未知站點';
    if (!stopGroups[stopName]) {
      stopGroups[stopName] = [];
    }
    stopGroups[stopName].push(arr);
  });

  // 渲染每個站點
  Object.entries(stopGroups).slice(0, 3).forEach(([stopName, stopArrivals], index) => {
    const firstArr = stopArrivals[0];
    const distance = firstArr.distance_m ? `${Math.round(firstArr.distance_m)}m` : '';
    
    html += `
      <div class="data-row" style="flex-direction: column; align-items: flex-start; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid rgba(0,0,0,0.05);">
        <div style="display: flex; justify-content: space-between; width: 100%; margin-bottom: 4px;">
          <span class="data-label" style="font-weight: 600;">🚏 ${stopName}</span>
          ${distance ? `<span class="data-value" style="font-size: 0.85em; opacity: 0.7;">${distance}</span>` : ''}
        </div>
    `;
    
    stopArrivals.forEach(arr => {
      const direction = arr.direction === 0 ? '往 ↑' : '返 ↓';
      const status = arr.status || '未知';
      html += `
        <div style="display: flex; justify-content: space-between; width: 100%; padding: 2px 0;">
          <span style="font-size: 0.9em; opacity: 0.8;">${direction}</span>
          <span class="data-value" style="font-size: 0.9em;">${status}</span>
        </div>
      `;
    });
    
    html += `</div>`;
  });

  return html;
}

/**
 * 渲染地理反查資訊（reverse_geocode）
 */
function renderReverseGeocode(data) {
  const displayName = data.display_name || '未知地點';
  const city = data.city || '';
  const road = data.road || '';
  const houseNumber = data.house_number || '';
  const suburb = data.suburb || '';
  const admin = data.admin || '';
  const countryCode = data.country_code || '';
  const lat = data.lat?.toFixed(6) || '';
  const lon = data.lon?.toFixed(6) || '';

  // 組合詳細地址
  let detailedAddress = [];
  if (city) detailedAddress.push(city);
  if (admin && admin !== city) detailedAddress.push(admin);
  if (suburb) detailedAddress.push(suburb);
  if (road) detailedAddress.push(road);
  if (houseNumber) detailedAddress.push(houseNumber);

  const addressText = detailedAddress.length > 0 ? detailedAddress.join(', ') : displayName;

  // 生成 Google Maps 連結
  const mapsUrl = `https://www.google.com/maps?q=${lat},${lon}`;

  return `
    <div class="data-row">
      <span class="data-label">📍 位置</span>
      <span class="data-value" style="font-weight: bold;">${displayName}</span>
    </div>
    ${city ? `
    <div class="data-row">
      <span class="data-label">🏙️ 城市</span>
      <span class="data-value">${city}</span>
    </div>
    ` : ''}
    ${road ? `
    <div class="data-row">
      <span class="data-label">🛣️ 道路</span>
      <span class="data-value">${road}${houseNumber ? ' ' + houseNumber : ''}</span>
    </div>
    ` : ''}
    ${suburb ? `
    <div class="data-row">
      <span class="data-label">🏘️ 區域</span>
      <span class="data-value">${suburb}</span>
    </div>
    ` : ''}
    <div class="data-row">
      <span class="data-label">🌐 座標</span>
      <span class="data-value" style="font-size: 0.85em;">${lat}, ${lon}</span>
    </div>
    <div class="data-row" style="margin-top: 8px;">
      <a href="${mapsUrl}" target="_blank" style="color: #0066cc; text-decoration: none; font-size: 0.9em;">
        🗺️ 在 Google Maps 中查看 →
      </a>
    </div>
  `;
}

/**
 * 渲染附近公車站點
 */
function renderNearbyStops(stops) {
  if (!stops || stops.length === 0) {
    return '<p>附近沒有公車站</p>';
  }

  let html = '';
  stops.slice(0, 5).forEach((stop, index) => {
    const stopName = stop.stop_name || '未知站點';
    const distance = stop.distance_m ? `${Math.round(stop.distance_m)}m` : '';
    const walkTime = stop.walking_time_min ? `步行 ${stop.walking_time_min} 分` : '';
    
    html += `
      <div class="data-row" style="margin-bottom: 8px;">
        <div style="flex: 1;">
          <div style="font-weight: 600; margin-bottom: 2px;">🚏 ${stopName}</div>
          <div style="font-size: 0.85em; opacity: 0.7;">${walkTime} ${distance ? `(${distance})` : ''}</div>
        </div>
      </div>
    `;
  });

  return html;
}

/**
 * 渲染導航路線（directions）
 */
function renderDirections(data) {
  const originLabel = data.origin_label || '起點';
  const destLabel = data.dest_label || '目的地';
  const distanceM = data.distance_m;
  const durationS = data.duration_s;
  
  // 格式化距離
  let distanceStr = '--';
  if (distanceM !== undefined) {
    distanceStr = distanceM >= 1000 
      ? `${(distanceM / 1000).toFixed(1)} 公里` 
      : `${Math.round(distanceM)} 公尺`;
  }
  
  // 格式化時間
  let durationStr = '--';
  if (durationS !== undefined) {
    const minutes = Math.round(durationS / 60);
    if (minutes >= 60) {
      const hours = Math.floor(minutes / 60);
      const mins = minutes % 60;
      durationStr = mins > 0 ? `${hours} 小時 ${mins} 分鐘` : `${hours} 小時`;
    } else {
      durationStr = `${minutes} 分鐘`;
    }
  }
  
  // 生成 Google Maps 連結（如果有座標）
  let mapsLink = '';
  if (data.origin_lat && data.origin_lon && data.dest_lat && data.dest_lon) {
    const mapsUrl = `https://www.google.com/maps/dir/${data.origin_lat},${data.origin_lon}/${data.dest_lat},${data.dest_lon}`;
    mapsLink = `
      <div class="data-row" style="margin-top: 8px;">
        <a href="${mapsUrl}" target="_blank" style="color: #0066cc; text-decoration: none; font-size: 0.9em;">
          🗺️ 在 Google Maps 中查看 →
        </a>
      </div>
    `;
  }
  
  return `
    <div class="data-row">
      <span class="data-label">📍 起點</span>
      <span class="data-value">${originLabel}</span>
    </div>
    <div class="data-row">
      <span class="data-label">🎯 目的地</span>
      <span class="data-value">${destLabel}</span>
    </div>
    <div class="data-row">
      <span class="data-label">📏 距離</span>
      <span class="data-value">${distanceStr}</span>
    </div>
    <div class="data-row">
      <span class="data-label">⏱️ 預估時間</span>
      <span class="data-value">${durationStr}</span>
    </div>
    ${mapsLink}
  `;
}

/**
 * 渲染捷運到站資訊（tdx_metro arrivals）
 */
function renderMetroArrivals(arrivals) {
  if (!arrivals || arrivals.length === 0) {
    return '<p class="data-row">目前無捷運到站資訊</p>';
  }

  let html = '<div class="metro-arrivals">';

  // 按路線分組
  const lineGroups = {};
  arrivals.forEach(arr => {
    const lineName = arr.line_name || '未知路線';
    if (!lineGroups[lineName]) {
      lineGroups[lineName] = [];
    }
    lineGroups[lineName].push(arr);
  });

  // 渲染每條路線
  Object.entries(lineGroups).forEach(([lineName, lineArrivals], index) => {
    html += `
      <div class="metro-line" style="border-bottom: 1px solid #eee; padding: 12px 0; ${index === Object.keys(lineGroups).length - 1 ? 'border-bottom: none;' : ''}">
        <div class="data-row" style="margin-bottom: 8px;">
          <span class="data-label" style="font-weight: bold; color: #0066cc;">🚇 ${lineName}</span>
        </div>
    `;
    
    lineArrivals.slice(0, 3).forEach(arr => {
      const dest = arr.destination || '未知';
      const timeSec = arr.arrival_time_sec;
      const status = arr.train_status || '未知';
      
      let timeStr = status;
      if (timeSec > 0) {
        const min = Math.floor(timeSec / 60);
        const sec = timeSec % 60;
        timeStr = min > 0 ? `${min} 分 ${sec} 秒` : `${sec} 秒`;
      }
      
      html += `
        <div class="data-row">
          <span class="data-label">→ ${dest}</span>
          <span class="data-value">${timeStr}</span>
        </div>
      `;
    });
    
    html += '</div>';
  });

  html += '</div>';
  return html;
}

/**
 * 渲染捷運站點資訊（tdx_metro stations）
 */
function renderMetroStations(stations) {
  if (!stations || stations.length === 0) {
    return '<p class="data-row">附近無捷運站</p>';
  }

  let html = '<div class="metro-stations">';

  stations.forEach((station, index) => {
    const stationName = station.station_name || '未知車站';
    const distance = station.distance_m ? `${Math.round(station.distance_m)} 公尺` : '';
    const walkTime = station.walking_time_min ? `步行約 ${station.walking_time_min} 分鐘` : '';
    const address = station.address || '';

    html += `
      <div class="metro-station-item" style="border-bottom: 1px solid #eee; padding: 12px 0; ${index === stations.length - 1 ? 'border-bottom: none;' : ''}">
        <div class="data-row" style="margin-bottom: 4px;">
          <span class="data-label" style="font-weight: bold; color: #0066cc;">🚇 ${stationName}</span>
        </div>
        ${distance ? `
        <div class="data-row">
          <span class="data-label">📏 距離</span>
          <span class="data-value">${distance}</span>
        </div>
        ` : ''}
        ${walkTime ? `
        <div class="data-row">
          <span class="data-label">🚶 步行時間</span>
          <span class="data-value">${walkTime}</span>
        </div>
        ` : ''}
        ${address ? `
        <div class="data-row">
          <span class="data-label">📍 地址</span>
          <span class="data-value" style="font-size: 0.85em;">${address}</span>
        </div>
        ` : ''}
      </div>
    `;
  });

  html += '</div>';
  return html;
}

/**
 * 渲染正向地理編碼（forward_geocode）
 */
function renderForwardGeocode(data) {
  const displayName = data.display_name || '未知地點';
  const lat = data.lat?.toFixed(6) || '';
  const lon = data.lon?.toFixed(6) || '';
  const city = data.city || '';
  const road = data.road || '';
  const suburb = data.suburb || '';

  // 生成 Google Maps 連結
  const mapsUrl = `https://www.google.com/maps?q=${lat},${lon}`;

  return `
    <div class="data-row">
      <span class="data-label">📍 地點</span>
      <span class="data-value" style="font-weight: bold;">${displayName}</span>
    </div>
    ${city ? `
    <div class="data-row">
      <span class="data-label">🏙️ 城市</span>
      <span class="data-value">${city}</span>
    </div>
    ` : ''}
    ${road ? `
    <div class="data-row">
      <span class="data-label">🛣️ 道路</span>
      <span class="data-value">${road}</span>
    </div>
    ` : ''}
    ${suburb ? `
    <div class="data-row">
      <span class="data-label">🏘️ 區域</span>
      <span class="data-value">${suburb}</span>
    </div>
    ` : ''}
    <div class="data-row">
      <span class="data-label">🌐 座標</span>
      <span class="data-value" style="font-size: 0.85em;">${lat}, ${lon}</span>
    </div>
    <div class="data-row" style="margin-top: 8px;">
      <a href="${mapsUrl}" target="_blank" style="color: #0066cc; text-decoration: none; font-size: 0.9em;">
        🗺️ 在 Google Maps 中查看 →
      </a>
    </div>
  `;
}

/**
 * Fallback：顯示 JSON
 */
function renderJSONFallback(data) {
  return `<pre style="font-size: 0.85em; white-space: pre-wrap;">${JSON.stringify(data, null, 2)}</pre>`;
}
