// ========== 工具卡片管理（改良版：支援位置滿了的情況）==========

const positions = ['pos-top-right', 'pos-top-left', 'pos-bottom-right', 'pos-bottom-left'];
let usedPositions = [];
const MAX_CARDS = 4;

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
  // 清除桌面版卡片
  const desktopCards = cardsContainer.querySelectorAll('.voice-tool-card');
  desktopCards.forEach(card => {
    card.classList.add('exiting');
    setTimeout(() => card.remove(), 300);
  });

  // 清除手機版側邊欄卡片
  const sidebarCards = document.getElementById('tool-sidebar-cards');
  if (sidebarCards) {
    const mobileCards = sidebarCards.querySelectorAll('.voice-tool-card');
    mobileCards.forEach(card => {
      card.classList.add('exiting');
      setTimeout(() => card.remove(), 300);
    });
  }

  usedPositions = [];
  updateSidebarToggle();
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
    '健康數據': '❤️',
    '天氣': '🌤️',
    '新聞': '📰',
    '匯率': '💱',
    '生活資訊': '💬',
    '地理定位': '📍',
    '軌道運輸': '🚇',
    '道路運輸': '🚌',
    '微型運具': '🚲',
    '停車與充電': '🅿️',
    '時間': '⏰',
    '提醒': '⏰',
    '日曆': '📅',
    '音樂': '🎵',
    '地圖': '🗺️',
    '翻譯': '🌐',
    '計算': '🔢',

    // 工具名稱映射
    'healthkit_query': '❤️',
    'weather_query': '🌤️',
    'news_query': '📰',
    'exchange_query': '💱',
    'forward_geocode': '📍',
    'reverse_geocode': '📍',
    'directions': '🗺️',
    'tdx_bus_arrival': '🚌',
    'tdx_metro': '�',
    'tdx_train': '🚆',
    'tdx_thsr': '🚄',
    'tdx_youbike': '🚲',
    'tdx_parking': '🅿️',
    'time_query': '⏰',
    'reminder': '⏰',
    'calendar': '📅'
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
 */
function displayToolCard(toolName, toolData) {
  // 清除舊卡片
  clearAllCards();

  // 獲取工具 metadata
  const toolMeta = toolsMetadata[toolName] || {};
  const category = toolMeta.category || '未知';
  const icon = getIconForTool(toolName, category);

  const card = document.createElement('div');
  card.className = 'voice-tool-card';
  card.dataset.type = toolName;

  // 渲染卡片內容
  const contentHTML = renderCardContent(toolName, toolData);

  card.innerHTML = `
    <div class="card-header">
      <div class="card-icon">${icon}</div>
      <h3>${category}</h3>
    </div>
    <div class="card-content">${contentHTML}</div>
  `;

  if (isMobileMode()) {
    // 手機版：添加到側邊欄
    const sidebarCards = document.getElementById('tool-sidebar-cards');
    sidebarCards.appendChild(card);
    updateSidebarToggle();
  } else {
    // 桌面版：使用原有邏輯
    const position = getNextPosition();
    if (!position) return;

    card.classList.add(position);
    cardsContainer.appendChild(card);
  }

  console.log(`🃏 顯示工具卡片: ${toolName} (${category})`);
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

  // 模式 1：health_data 陣列
  if (toolData.health_data && Array.isArray(toolData.health_data)) {
    console.log('✅ 匹配到模式 1: health_data');
    return renderHealthMetrics(toolData.health_data);
  }

  // 模式 2：articles 陣列
  if (toolData.articles && Array.isArray(toolData.articles)) {
    console.log('✅ 匹配到模式 2: articles');
    return renderNewsList(toolData.articles);
  }

  // 模式 3：天氣數據（直接檢查，無論是否包在 raw_data 中）
  const weatherData = toolData.raw_data || toolData;
  if (weatherData.main && weatherData.weather) {
    console.log('✅ 匹配到模式 3: 天氣數據');
    return renderWeatherData(weatherData);
  }

  // 模式 4：匯率數據（優先檢查）
  if (toolData.rate !== undefined && toolData.from_currency !== undefined) {
    console.log('✅ 匹配到模式 4: 匯率數據');
    return renderExchangeRate(toolData);
  }

  // 模式 5：地理定位數據（forward_geocode / reverse_geocode）
  if (toolData.best_match && toolData.best_match.lat && toolData.best_match.lon) {
    console.log('✅ 匹配到模式 5: 地理定位數據');
    return renderLocationData(toolData);
  }

  // 模式 6：通用 raw_data 物件
  if (toolData.raw_data && typeof toolData.raw_data === 'object') {
    console.log('✅ 匹配到模式 6: 通用 raw_data');
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
  const metricNames = {
    heart_rate: '心率',
    step_count: '步數',
    oxygen_level: '血氧',
    respiratory_rate: '呼吸',
    sleep_analysis: '睡眠'
  };

  let html = '';
  healthData.slice(0, 3).forEach(item => {
    const label = metricNames[item.metric] || item.metric;
    html += `
      <div class="data-row">
        <span class="data-label">${label}</span>
        <span class="data-value">${item.value} ${item.unit || ''}</span>
      </div>
    `;
  });

  return html || '<p>無健康數據</p>';
}

/**
 * 渲染新聞列表（顯示 AI 生成的簡短摘要）
 * 顯示全部新聞，但保持 3 條的高度可滾動
 */
function renderNewsList(articles) {
  let html = '';
  articles.forEach(article => {
    // 優先使用 AI 生成的簡短摘要，否則 fallback 到標題
    const displayText = article.summary || article.title || '無摘要';

    html += `
      <div class="data-row" style="margin-bottom: 8px;">
        <span style="font-size: 14px; line-height: 1.5;">• ${displayText}</span>
      </div>
    `;
  });

  // 使用可滾動容器，固定高度為 3 條新聞的大小
  return html
    ? `<div style="max-height: 90px; overflow-y: auto; padding-right: 4px;">${html}</div>`
    : '<p>無新聞</p>';
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
 * 渲染地理定位數據（forward_geocode / reverse_geocode）
 */
function renderLocationData(data) {
  // reverse_geocode: 扁平結構（欄位在第一層）
  // forward_geocode: 巢狀結構（best_match + results）
  const bestMatch = data.best_match || data;  // ← 兼容兩種結構
  const results = data.results || [];
  const query = data.query || '';
  
  let html = '';

  // 顯示查詢字串（如果有）
  if (query) {
    html += `
      <div class="data-row">
        <span class="data-label">🔍 查詢</span>
        <span class="data-value">${query}</span>
      </div>
    `;
  }

  // 地點名稱（POI、建築物等）
  if (bestMatch.name && bestMatch.name !== bestMatch.road) {
    html += `
      <div class="data-row">
        <span class="data-label">� 地點</span>
        <span class="data-value">${bestMatch.name}</span>
      </div>
    `;
  }

  // 地址（路名 + 門牌號）
  if (bestMatch.road) {
    const address = bestMatch.house_number 
      ? `${bestMatch.road}${bestMatch.house_number}號`
      : bestMatch.road;
    html += `
      <div class="data-row">
        <span class="data-label">� 地址</span>
        <span class="data-value">${address}</span>
      </div>
    `;
  }

  // 區域 + 城市
  const locationParts = [];
  if (bestMatch.suburb) locationParts.push(bestMatch.suburb);
  if (bestMatch.city_district && bestMatch.city_district !== bestMatch.suburb) {
    locationParts.push(bestMatch.city_district);
  }
  if (bestMatch.city) locationParts.push(bestMatch.city);
  
  if (locationParts.length > 0) {
    html += `
      <div class="data-row">
        <span class="data-label">📍 位置</span>
        <span class="data-value">${locationParts.join(', ')}</span>
      </div>
    `;
  }

  // 郵遞區號
  if (bestMatch.postcode) {
    html += `
      <div class="data-row">
        <span class="data-label">📮 郵遞區號</span>
        <span class="data-value">${bestMatch.postcode}</span>
      </div>
    `;
  }

  // 如果有多個結果，顯示數量
  if (results.length > 1) {
    html += `
      <div class="data-row" style="margin-top: 8px; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 8px;">
        <span class="data-label">📊 其他結果</span>
        <span class="data-value">共 ${results.length} 個地點</span>
      </div>
    `;
  }

  // Google Maps 連結（可選）
  if (bestMatch.lat && bestMatch.lon) {
    const mapsUrl = `https://www.google.com/maps?q=${bestMatch.lat},${bestMatch.lon}`;
    html += `
      <div class="data-row" style="margin-top: 8px;">
        <a href="${mapsUrl}" target="_blank" rel="noopener noreferrer" 
           style="color: #4fc3f7; text-decoration: none; font-size: 0.9em;">
          🗺️ 在 Google Maps 中查看
        </a>
      </div>
    `;
  }

  return html || '<p>無地理數據</p>';
}

/**
 * Fallback：顯示 JSON
 */
function renderJSONFallback(data) {
  return `<pre style="font-size: 0.85em; white-space: pre-wrap;">${JSON.stringify(data, null, 2)}</pre>`;
}

// ========== RWD 響應式側邊欄控制 ==========

/**
 * 切換工具卡片側邊欄（手機版）
 */
function toggleToolSidebar() {
  const sidebar = document.getElementById('tool-sidebar');
  const toggle = document.getElementById('tool-sidebar-toggle');

  if (sidebar.classList.contains('active')) {
    sidebar.classList.remove('active');
    toggle.classList.remove('active');
  } else {
    sidebar.classList.add('active');
    toggle.classList.add('active');
    // 檢查側邊欄內是否有卡片，動態更新切換按鈕
    updateSidebarToggle();
  }
}

/**
 * 更新側邊欄切換按鈕狀態
 */
function updateSidebarToggle() {
  // 新的設計中按鈕始終可見，不需要特殊狀態
  return;
}

/**
 * 檢測是否為手機/平板模式
 */
function isMobileMode() {
  return window.innerWidth <= 1024;
}

// 重寫 addToolCard 函數，支援雙容器（桌面 vs 手機）
const originalAddToolCard = addToolCard;
function addToolCard(type) {
  if (isMobileMode()) {
    // 手機版：卡片加到側邊欄
    const sidebarCards = document.getElementById('tool-sidebar-cards');

    const card = document.createElement('div');
    card.className = 'voice-tool-card';
    card.dataset.type = type;

    // 複製原有的卡片內容生成邏輯
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

    sidebarCards.appendChild(card);
    updateSidebarToggle();
  } else {
    // 桌面版：使用原有邏輯
    originalAddToolCard(type);
  }
}
