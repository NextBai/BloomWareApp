
const positions = ['pos-top-right', 'pos-top-left', 'pos-bottom-right', 'pos-bottom-left'];
let usedPositions = [];
const MAX_CARDS = 4;

const LABELS = {
  zh: {
    temperature: '溫度', condition: '狀況', humidity: '濕度', wind_speed: '風速',
    weather: '天氣', city: '城市', description: '描述',
    feels_like: '體感', pressure: '氣壓', sunrise: '日出', sunset: '日落',
    heart_rate: '心率', step_count: '步數', oxygen_level: '血氧', respiratory_rate: '呼吸',
    sleep_analysis: '睡眠', record_time: '記錄時間', average: '平均值',
    no_news: '無新聞', no_data: '無數據', unknown: '未知',
    exchange_rate: '匯率', conversion: '轉換', time: '時間',
    train_type: '車種', origin_station: '起站', dest_station: '迄站',
    departure: '出發', arrival: '抵達', duration: '行駛時間',
    distance: '距離', walking_time: '步行時間', station: '車站',
    available_bikes: '可借車輛', available_spaces: '可還空位',
    bike_type: '類型', service_status: '服務狀態', operating: '營運中', suspended: '暫停服務',
    location: '位置', coordinates: '座標', origin: '起點', destination: '目的地',
    estimated_time: '預估時間', view_in_maps: '在 Google Maps 中查看',
    line: '路線', address: '地址', road: '道路', area: '區域'
  },
  en: {
    temperature: 'Temperature', condition: 'Condition', humidity: 'Humidity', wind_speed: 'Wind Speed',
    weather: 'Weather', city: 'City', description: 'Description',
    feels_like: 'Feels Like', pressure: 'Pressure', sunrise: 'Sunrise', sunset: 'Sunset',
    heart_rate: 'Heart Rate', step_count: 'Steps', oxygen_level: 'Oxygen', respiratory_rate: 'Respiratory',
    sleep_analysis: 'Sleep', record_time: 'Record Time', average: 'Average',
    no_news: 'No News', no_data: 'No Data', unknown: 'Unknown',
    exchange_rate: 'Exchange Rate', conversion: 'Conversion', time: 'Time',
    train_type: 'Train Type', origin_station: 'Origin', dest_station: 'Destination',
    departure: 'Departure', arrival: 'Arrival', duration: 'Duration',
    distance: 'Distance', walking_time: 'Walking Time', station: 'Station',
    available_bikes: 'Available Bikes', available_spaces: 'Available Spaces',
    bike_type: 'Type', service_status: 'Service Status', operating: 'Operating', suspended: 'Suspended',
    location: 'Location', coordinates: 'Coordinates', origin: 'Origin', destination: 'Destination',
    estimated_time: 'Estimated Time', view_in_maps: 'View in Google Maps',
    line: 'Line', address: 'Address', road: 'Road', area: 'Area'
  },
  ko: {
    temperature: '온도', condition: '상태', humidity: '습도', wind_speed: '풍속',
    weather: '날씨', city: '도시', description: '설명',
    feels_like: '체감', pressure: '기압', sunrise: '일출', sunset: '일몰',
    heart_rate: '심박수', step_count: '걸음 수', oxygen_level: '혈중 산소', respiratory_rate: '호흡',
    sleep_analysis: '수면', record_time: '기록 시간', average: '평균',
    no_news: '뉴스 없음', no_data: '데이터 없음', unknown: '알 수 없음',
    exchange_rate: '환율', conversion: '환전', time: '시간',
    train_type: '열차 종류', origin_station: '출발역', dest_station: '도착역',
    departure: '출발', arrival: '도착', duration: '소요 시간',
    distance: '거리', walking_time: '도보 시간', station: '역',
    available_bikes: '대여 가능', available_spaces: '반납 가능',
    bike_type: '유형', service_status: '서비스 상태', operating: '운영 중', suspended: '일시 중단',
    location: '위치', coordinates: '좌표', origin: '출발지', destination: '목적지',
    estimated_time: '예상 시간', view_in_maps: 'Google Maps에서 보기',
    line: '노선', address: '주소', road: '도로', area: '지역'
  },
  ja: {
    temperature: '気温', condition: '状況', humidity: '湿度', wind_speed: '風速',
    weather: '天気', city: '都市', description: '説明',
    feels_like: '体感', pressure: '気圧', sunrise: '日の出', sunset: '日の入り',
    heart_rate: '心拍数', step_count: '歩数', oxygen_level: '血中酸素', respiratory_rate: '呼吸',
    sleep_analysis: '睡眠', record_time: '記録時刻', average: '平均',
    no_news: 'ニュースなし', no_data: 'データなし', unknown: '不明',
    exchange_rate: '為替レート', conversion: '換算', time: '時刻',
    train_type: '列車種別', origin_station: '出発駅', dest_station: '到着駅',
    departure: '出発', arrival: '到着', duration: '所要時間',
    distance: '距離', walking_time: '徒歩時間', station: '駅',
    available_bikes: '利用可能', available_spaces: '返却可能',
    bike_type: 'タイプ', service_status: 'サービス状態', operating: '運行中', suspended: '一時停止',
    location: '場所', coordinates: '座標', origin: '出発地', destination: '目的地',
    estimated_time: '予想時間', view_in_maps: 'Google Mapsで見る',
    line: '路線', address: '住所', road: '道路', area: 'エリア'
  },
  id: {
    temperature: 'Suhu', condition: 'Kondisi', humidity: 'Kelembaban', wind_speed: 'Kecepatan Angin',
    weather: 'Cuaca', city: 'Kota', description: 'Deskripsi',
    feels_like: 'Terasa', pressure: 'Tekanan', sunrise: 'Matahari Terbit', sunset: 'Matahari Terbenam',
    heart_rate: 'Detak Jantung', step_count: 'Langkah', oxygen_level: 'Oksigen', respiratory_rate: 'Pernapasan',
    sleep_analysis: 'Tidur', record_time: 'Waktu Rekam', average: 'Rata-rata',
    no_news: 'Tidak Ada Berita', no_data: 'Tidak Ada Data', unknown: 'Tidak Diketahui',
    exchange_rate: 'Nilai Tukar', conversion: 'Konversi', time: 'Waktu',
    train_type: 'Jenis Kereta', origin_station: 'Stasiun Asal', dest_station: 'Stasiun Tujuan',
    departure: 'Keberangkatan', arrival: 'Kedatangan', duration: 'Durasi',
    distance: 'Jarak', walking_time: 'Waktu Jalan', station: 'Stasiun',
    available_bikes: 'Sepeda Tersedia', available_spaces: 'Tempat Tersedia',
    bike_type: 'Tipe', service_status: 'Status Layanan', operating: 'Beroperasi', suspended: 'Ditangguhkan',
    location: 'Lokasi', coordinates: 'Koordinat', origin: 'Asal', destination: 'Tujuan',
    estimated_time: 'Waktu Estimasi', view_in_maps: 'Lihat di Google Maps',
    line: 'Jalur', address: 'Alamat', road: 'Jalan', area: 'Area'
  },
  vi: {
    temperature: 'Nhiệt độ', condition: 'Tình trạng', humidity: 'Độ ẩm', wind_speed: 'Tốc độ gió',
    weather: 'Thời tiết', city: 'Thành phố', description: 'Mô tả',
    feels_like: 'Cảm giác', pressure: 'Áp suất', sunrise: 'Mặt trời mọc', sunset: 'Mặt trời lặn',
    heart_rate: 'Nhịp tim', step_count: 'Số bước', oxygen_level: 'Oxy', respiratory_rate: 'Hô hấp',
    sleep_analysis: 'Giấc ngủ', record_time: 'Thời gian ghi', average: 'Trung bình',
    no_news: 'Không có tin', no_data: 'Không có dữ liệu', unknown: 'Không rõ',
    exchange_rate: 'Tỷ giá', conversion: 'Chuyển đổi', time: 'Thời gian',
    train_type: 'Loại tàu', origin_station: 'Ga đi', dest_station: 'Ga đến',
    departure: 'Khởi hành', arrival: 'Đến', duration: 'Thời gian di chuyển',
    distance: 'Khoảng cách', walking_time: 'Thời gian đi bộ', station: 'Ga',
    available_bikes: 'Xe có sẵn', available_spaces: 'Chỗ trống',
    bike_type: 'Loại', service_status: 'Trạng thái dịch vụ', operating: 'Hoạt động', suspended: 'Tạm ngừng',
    location: 'Vị trí', coordinates: 'Tọa độ', origin: 'Điểm đi', destination: 'Điểm đến',
    estimated_time: 'Thời gian ước tính', view_in_maps: 'Xem trên Google Maps',
    line: 'Tuyến', address: 'Địa chỉ', road: 'Đường', area: 'Khu vực'
  }
};

let currentLanguage = 'zh';

let toolDrawer = null;
let toolDrawerToggle = null;
let toolDrawerContent = null;
let toolDrawerOverlay = null;
let toolDrawerClose = null;
let isDrawerOpen = false;

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

  toolDrawerToggle.addEventListener('click', toggleToolDrawer);

  if (toolDrawerClose) {
    toolDrawerClose.addEventListener('click', hideToolDrawer);
  }

  if (toolDrawerOverlay) {
    toolDrawerOverlay.addEventListener('click', hideToolDrawer);
  }

}

function showToolDrawerToggle() {
  if (toolDrawerToggle) {
    toolDrawerToggle.classList.add('visible');
  }
}

function hideToolDrawerToggle() {
  if (toolDrawerToggle) {
    toolDrawerToggle.classList.remove('visible');
    toolDrawerToggle.classList.remove('open');
  }
}

function toggleToolDrawer() {
  if (isDrawerOpen) {
    hideToolDrawer();
  } else {
    showToolDrawer();
  }
}

function showToolDrawer() {
  if (toolDrawer) {
    toolDrawer.classList.add('open');
    toolDrawerToggle?.classList.add('open');
    toolDrawerOverlay?.classList.add('visible');
    isDrawerOpen = true;
  }
}

function hideToolDrawer() {
  if (toolDrawer) {
    toolDrawer.classList.remove('open');
    toolDrawerToggle?.classList.remove('open');
    toolDrawerOverlay?.classList.remove('visible');
    isDrawerOpen = false;
  }
}

function hideToolCards() {
  hideToolDrawer();
  hideToolDrawerToggle();
  if (toolDrawerContent) {
    toolDrawerContent.innerHTML = '';
  }
  clearAllCards();
}

function getNextPosition() {
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
        toolsMetadata = {};
        data.tools.forEach(tool => {
          toolsMetadata[tool.name] = tool;
        });
      }
    }
  } catch (error) {
    console.error('❌ 同步工具 metadata 失敗:', error);
  }
}

function getIconForTool(toolName, category) {
  const iconMap = {
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
    'directions': '🗺️',
    'environment_context': '🌍'
  };

  if (iconMap[toolName]) {
    return iconMap[toolName];
  }

  if (category && iconMap[category]) {
    return iconMap[category];
  }

  return '🔧';
}

function displayMultipleToolCards(toolsArray) {
  clearAllCards();
  if (!toolsArray || toolsArray.length === 0) return;

  if (toolDrawerContent) {
    toolDrawerContent.innerHTML = '';
  }

  toolsArray.forEach((tool, index) => {
    const toolName = tool.tool_name;
    const toolData = tool.tool_data;
    
    const toolMeta = toolsMetadata[toolName] || {};
    const category = toolMeta.category || '未知';
    const icon = getIconForTool(toolName, category);
    const contentHTML = renderCardContent(toolName, toolData);

    const card = document.createElement('div');
    card.className = 'voice-tool-card';
    card.dataset.type = toolName;
    card.style.marginBottom = '15px';
    card.style.position = 'relative';

    card.innerHTML = `
      <div class="card-header">
        <div class="card-icon">${icon}</div>
        <h3>${category}</h3>
        <span style="margin-left:auto; font-size:12px; color:#888;">${index + 1}/${toolsArray.length}</span>
      </div>
      <div class="card-content" style="max-height: 300px; overflow-y: auto; overflow-x: hidden; padding-right: 8px;">${contentHTML}</div>
    `;

    if (toolDrawerContent) {
      toolDrawerContent.appendChild(card);
    }
  });

  if (toolDrawerContent) {
    showToolDrawerToggle();
  }

  const lastTool = toolsArray[toolsArray.length - 1];
  const lastToolName = lastTool.tool_name;
  const lastToolData = lastTool.tool_data;
  
  const toolMeta = toolsMetadata[lastToolName] || {};
  const category = toolMeta.category || '未知';
  const icon = getIconForTool(lastToolName, category);
  const contentHTML = renderCardContent(lastToolName, lastToolData);

  const floatingCard = document.createElement('div');
  floatingCard.className = 'voice-tool-card';
  floatingCard.dataset.type = lastToolName;

  let extraHeaderHtml = '';
  if (toolsArray.length > 1) {
    extraHeaderHtml = `<button onclick="showToolDrawer()" style="margin-left:auto; background:rgba(0,100,255,0.1); color:#0066cc; border:none; padding:4px 8px; border-radius:12px; font-size:12px; font-weight:bold; cursor:pointer;">查看全部 (${toolsArray.length})</button>`;
  }

  floatingCard.innerHTML = `
    <div class="card-header">
      <div class="card-icon">${icon}</div>
      <h3>${category}</h3>
      ${extraHeaderHtml}
    </div>
    <div class="card-content" style="max-height: 300px; overflow-y: auto; overflow-x: hidden; padding-right: 8px;">${contentHTML}</div>
  `;

  const position = getNextPosition();
  if (position && cardsContainer) {
    floatingCard.classList.add(position);
    cardsContainer.appendChild(floatingCard);
  }
}

function displayToolCard(toolName, toolData) {
  clearAllCards();

  const toolMeta = toolsMetadata[toolName] || {};
  const category = toolMeta.category || '未知';
  const icon = getIconForTool(toolName, category);

  const contentHTML = renderCardContent(toolName, toolData);

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

  if (toolDrawerContent) {
    toolDrawerContent.innerHTML = '';
    toolDrawerContent.appendChild(card.cloneNode(true));
    showToolDrawerToggle();
  }

  const position = getNextPosition();
  if (position && cardsContainer) {
    card.classList.add(position);
    cardsContainer.appendChild(card);
  }
}

function renderCardContent(toolName, toolData) {
  
  if (!toolData) {
    console.warn('⚠️ toolData 為空');
    return '<p class="data-row">無數據</p>';
  }

  const healthData = toolData.health_data || toolData.raw_data?.health_data;
  if (healthData && Array.isArray(healthData)) {
    return renderHealthMetrics(healthData);
  }

  const articlesData = toolData.articles || toolData.raw_data?.articles;
  if (articlesData && Array.isArray(articlesData)) {
    return renderNewsList(articlesData);
  }

  const weatherData = toolData.raw_data || toolData;
  if (weatherData.main && weatherData.weather) {
    return renderWeatherData(weatherData);
  }

  if (toolData.arrivals && Array.isArray(toolData.arrivals)) {
    return renderBusArrivals(toolData.arrivals, toolData.route_name);
  }

  if (toolData.stops && Array.isArray(toolData.stops)) {
    return renderNearbyStops(toolData.stops);
  }

  const exchangeData = toolData.raw_data || toolData;
  if (exchangeData.rate !== undefined && exchangeData.from_currency !== undefined) {
    return renderExchangeRate(exchangeData);
  }

  if (toolData.trains && Array.isArray(toolData.trains)) {
    return renderTrainList(toolData.trains);
  }

  if (toolData.stations && Array.isArray(toolData.stations) && 
      (toolName === 'tdx_youbike' || toolData.stations[0]?.available_bikes !== undefined)) {
    return renderYouBikeStations(toolData.stations);
  }
  
  if (toolData.stations && Array.isArray(toolData.stations) && toolName === 'tdx_train') {
    return renderTrainStations(toolData.stations);
  }

  if (toolData.display_name && toolData.lat && toolData.lon && toolName === 'reverse_geocode') {
    return renderReverseGeocode(toolData);
  }

  if ((toolData.distance_m !== undefined || toolData.duration_s !== undefined) && 
      (toolName === 'directions' || toolData.polyline !== undefined)) {
    return renderDirections(toolData);
  }

  if (toolData.arrivals && Array.isArray(toolData.arrivals) && toolName === 'tdx_metro') {
    return renderMetroArrivals(toolData.arrivals);
  }

  if (toolData.stations && Array.isArray(toolData.stations) && toolName === 'tdx_metro') {
    return renderMetroStations(toolData.stations);
  }

  if (toolData.lat && toolData.lon && toolData.display_name && toolName === 'forward_geocode') {
    return renderForwardGeocode(toolData);
  }

  if (toolName === 'environment_context' || (toolData.lat && toolData.lon && toolData.label)) {
    return renderEnvironmentContext(toolData);
  }

  if (toolData.raw_data && typeof toolData.raw_data === 'object') {
    return renderKeyValuePairs(toolData.raw_data);
  }

  console.warn('⚠️ 未匹配任何模式，使用 JSON fallback');
  return renderJSONFallback(toolData);
}

function renderWeatherData(data) {
  const main = data.main || {};
  const weather = data.weather?.[0] || {};
  const wind = data.wind || {};
  const sys = data.sys || {};
  const labels = LABELS[currentLanguage] || LABELS.zh;
  
  const formatTime = (timestamp) => {
    if (!timestamp) return '--:--';
    const date = new Date(timestamp * 1000);
    return date.toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' });
  };
  
  return `
    <div class="data-row">
      <span class="data-label">🌡️ ${labels.temperature}</span>
      <span class="data-value">${main.temp?.toFixed(1) || '--'}°C</span>
    </div>
    <div class="data-row">
      <span class="data-label">🤔 ${labels.feels_like}</span>
      <span class="data-value">${main.feels_like?.toFixed(1) || '--'}°C</span>
    </div>
    <div class="data-row">
      <span class="data-label">☁️ ${labels.condition}</span>
      <span class="data-value">${weather.description || '--'}</span>
    </div>
    <div class="data-row">
      <span class="data-label">💧 ${labels.humidity}</span>
      <span class="data-value">${main.humidity || '--'}%</span>
    </div>
    <div class="data-row">
      <span class="data-label">🌪️ ${labels.wind_speed}</span>
      <span class="data-value">${wind.speed?.toFixed(1) || '--'} m/s</span>
    </div>
    <div class="data-row">
      <span class="data-label">📊 ${labels.pressure}</span>
      <span class="data-value">${main.pressure || '--'} hPa</span>
    </div>
    <div class="data-row">
      <span class="data-label">🌅 ${labels.sunrise}</span>
      <span class="data-value">${formatTime(sys.sunrise)}</span>
    </div>
    <div class="data-row">
      <span class="data-label">🌇 ${labels.sunset}</span>
      <span class="data-value">${formatTime(sys.sunset)}</span>
    </div>
  `;
}

function renderHealthMetrics(healthData) {
  const labels = LABELS[currentLanguage] || LABELS.zh;
  
  if (!healthData || healthData.length === 0) {
    return `<p class="data-row">${labels.no_data}</p>`;
  }

  const metricIcons = {
    heart_rate: '❤️',
    step_count: '�',
    oxygen_level: '🫁',
    respiratory_rate: '💨',
    sleep_analysis: '😴'
  };

  const grouped = {};
  healthData.forEach(item => {
    const metric = item.metric || item.type;
    if (!grouped[metric]) {
      grouped[metric] = [];
    }
    grouped[metric].push(item);
  });

  let html = '<div class="health-metrics">';

  Object.entries(grouped).forEach(([metric, items], index) => {
    const icon = metricIcons[metric] || '📊';
    const label = labels[metric] || metric;
    const latestItem = items[0]; // 最新的數據
    const value = latestItem.value;
    const unit = latestItem.unit || '';
    
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
          <span class="data-label" style="font-size: 0.85em;">${labels.record_time}</span>
          <span class="data-value" style="font-size: 0.85em;">${timeStr}</span>
        </div>
        ` : ''}
        ${items.length > 1 ? `
        <div class="data-row" style="opacity: 0.6;">
          <span class="data-label" style="font-size: 0.8em;">${labels.average}</span>
          <span class="data-value" style="font-size: 0.8em;">${(items.reduce((sum, i) => sum + i.value, 0) / items.length).toFixed(1)} ${unit}</span>
        </div>
        ` : ''}
      </div>
    `;
  });

  html += '</div>';
  return html;
}

function renderNewsList(articles) {
  const labels = LABELS[currentLanguage] || LABELS.zh;
  let html = '';
  articles.slice(0, 3).forEach(article => {
    html += `
      <div class="data-row" style="flex-direction: column; align-items: flex-start; margin-bottom: 10px;">
        <span class="data-label" style="font-weight: bold;">${article.title || labels.unknown}</span>
        <span class="data-value" style="font-size: 0.85em; opacity: 0.8;">${article.source?.name || article.source || ''}</span>
      </div>
    `;
  });

  return html || `<p>${labels.no_news}</p>`;
}

function renderKeyValuePairs(data) {
  const labels = LABELS[currentLanguage] || LABELS.zh;
  const keyMap = {
    city: labels.city,
    temp: labels.temperature,
    temperature: labels.temperature,
    condition: labels.condition,
    weather: labels.weather,
    humidity: labels.humidity,
    wind_speed: labels.wind_speed,
    description: labels.description
  };

  let html = '';
  for (const [key, value] of Object.entries(data)) {
    if (typeof value === 'object') continue; // 跳過巢狀物件

    const label = keyMap[key] || key;
    let displayValue = value;

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

function renderExchangeRate(data) {
  const labels = LABELS[currentLanguage] || LABELS.zh;
  const currencySymbols = {
    "USD": "$", "TWD": "NT$", "JPY": "¥", "EUR": "€", 
    "GBP": "£", "CNY": "¥", "KRW": "₩", "HKD": "HK$"
  };
  
  const fromCurrency = data.from_currency || "USD";
  const toCurrency = data.to_currency || "TWD";
  const fromSymbol = currencySymbols[fromCurrency] || fromCurrency;
  const toSymbol = currencySymbols[toCurrency] || toCurrency;
  
  let html = '';

  if (data.rate !== undefined) {
    html += `
      <div class="data-row">
        <span class="data-label">💰 ${labels.exchange_rate}</span>
        <span class="data-value">1 ${fromCurrency} = ${data.rate.toFixed(4)} ${toCurrency}</span>
      </div>
    `;
  }

  if (data.amount && data.converted_amount !== undefined) {
    html += `
      <div class="data-row">
        <span class="data-label">🔄 ${labels.conversion}</span>
        <span class="data-value">${fromSymbol}${data.amount.toFixed(2)} = ${toSymbol}${data.converted_amount.toFixed(2)}</span>
      </div>
    `;
  }
  
  if (data.raw_data?.metadata?.timestamp) {
    const time = new Date(data.raw_data.metadata.timestamp).toLocaleString('zh-TW');
    html += `
      <div class="data-row">
        <span class="data-label">⏰ ${labels.time}</span>
        <span class="data-value">${time}</span>
      </div>
    `;
  }

  return html || `<p>${labels.no_data}</p>`;
}

function renderTrainList(trains) {
  const labels = LABELS[currentLanguage] || LABELS.zh;
  
  if (!trains || trains.length === 0) {
    return `<p class="data-row">${labels.no_data}</p>`;
  }

  let html = '<div class="train-list">';

  trains.forEach((train, index) => {
    const trainType = train.train_type || labels.unknown;
    const trainNo = train.train_no || '---';
    const departTime = train.departure_time ? train.departure_time.substring(0, 5) : '--:--';
    const arriveTime = train.arrival_time ? train.arrival_time.substring(0, 5) : '--:--';
    const durationText = train.duration_min ? `${train.duration_min}${currentLanguage === 'zh' ? '分鐘' : currentLanguage === 'en' ? ' min' : currentLanguage === 'ko' ? '분' : currentLanguage === 'ja' ? '分' : currentLanguage === 'id' ? ' menit' : ' phút'}` : labels.unknown;
    const originStation = train.origin_station || labels.unknown;
    const destStation = train.destination_station || labels.unknown;

    html += `
      <div class="train-item" style="border-bottom: 1px solid #eee; padding: 12px 0; ${index === trains.length - 1 ? 'border-bottom: none;' : ''}">
        <div class="data-row" style="margin-bottom: 8px;">
          <span class="data-label" style="font-weight: bold; color: #0066cc;">🚂 ${trainType} ${trainNo}</span>
        </div>
        <div class="data-row">
          <span class="data-label">📍 ${labels.origin_station} → ${labels.dest_station}</span>
          <span class="data-value">${originStation} → ${destStation}</span>
        </div>
        <div class="data-row">
          <span class="data-label">⏰ ${labels.departure}</span>
          <span class="data-value">${departTime}</span>
        </div>
        <div class="data-row">
          <span class="data-label">⏱️ ${labels.arrival}</span>
          <span class="data-value">${arriveTime}</span>
        </div>
        <div class="data-row">
          <span class="data-label">🕐 ${labels.duration}</span>
          <span class="data-value">${durationText}</span>
        </div>
      </div>
    `;
  });

  html += '</div>';
  return html;
}

function renderTrainStations(stations) {
  const labels = LABELS[currentLanguage] || LABELS.zh;
  
  if (!stations || stations.length === 0) {
    return `<p class="data-row">${labels.no_data}</p>`;
  }

  let html = '<div class="station-list">';

  stations.forEach((station, index) => {
    const stationName = station.station_name || station.name || labels.unknown;
    const distanceUnit = currentLanguage === 'zh' ? '公尺' : currentLanguage === 'en' ? 'm' : currentLanguage === 'ko' ? '미터' : currentLanguage === 'ja' ? 'メートル' : currentLanguage === 'id' ? 'm' : 'm';
    const distance = station.distance_m ? `${Math.round(station.distance_m)}${distanceUnit}` : '';
    const walkTimeText = station.walking_time_min ? `${currentLanguage === 'zh' ? '步行約' : ''}${station.walking_time_min}${currentLanguage === 'zh' ? '分鐘' : currentLanguage === 'en' ? ' min walk' : currentLanguage === 'ko' ? '분 도보' : currentLanguage === 'ja' ? '分 徒歩' : currentLanguage === 'id' ? ' menit jalan' : ' phút đi bộ'}` : '';

    html += `
      <div class="station-item" style="border-bottom: 1px solid #eee; padding: 12px 0; ${index === stations.length - 1 ? 'border-bottom: none;' : ''}">
        <div class="data-row" style="margin-bottom: 4px;">
          <span class="data-label" style="font-weight: bold; color: #0066cc;">🚉 ${stationName}</span>
        </div>
        ${distance ? `
        <div class="data-row">
          <span class="data-label">📏 ${labels.distance}</span>
          <span class="data-value">${distance}</span>
        </div>
        ` : ''}
        ${walkTimeText ? `
        <div class="data-row">
          <span class="data-label">🚶 ${labels.walking_time}</span>
          <span class="data-value">${walkTimeText}</span>
        </div>
        ` : ''}
      </div>
    `;
  });

  html += '</div>';
  return html;
}

function renderYouBikeStations(stations) {
  const labels = LABELS[currentLanguage] || LABELS.zh;
  
  if (!stations || stations.length === 0) {
    return `<p class="data-row">${labels.no_data}</p>`;
  }

  let html = '<div class="youbike-list">';

  stations.forEach((station, index) => {
    const stationName = station.station_name || labels.unknown;
    const availableBikes = station.available_bikes ?? 0;
    const availableSpaces = station.available_spaces ?? 0;
    const distance = station.distance_m || 0;
    const walkingTime = station.walking_time_min || 0;
    const bikeType = station.bike_type || 'YouBike';
    const serviceStatus = station.service_status === 1 ? labels.operating : labels.suspended;
    const walkText = currentLanguage === 'zh' ? `步行約 ${walkingTime} 分鐘` : currentLanguage === 'en' ? `${walkingTime} min walk` : currentLanguage === 'ko' ? `도보 ${walkingTime}분` : currentLanguage === 'ja' ? `徒歩${walkingTime}分` : currentLanguage === 'id' ? `${walkingTime} menit jalan` : `${walkingTime} phút đi bộ`;
    const bikeUnit = currentLanguage === 'zh' ? '輛' : currentLanguage === 'en' ? '' : currentLanguage === 'ko' ? '대' : currentLanguage === 'ja' ? '台' : currentLanguage === 'id' ? '' : '';
    const spaceUnit = currentLanguage === 'zh' ? '個' : currentLanguage === 'en' ? '' : currentLanguage === 'ko' ? '개' : currentLanguage === 'ja' ? '個' : currentLanguage === 'id' ? '' : '';

    let bikeStatusColor = '#e74c3c';
    let bikeStatusIcon = '🚫';
    if (availableBikes > 3) {
      bikeStatusColor = '#27ae60';
      bikeStatusIcon = '✅';
    } else if (availableBikes > 0) {
      bikeStatusColor = '#f39c12';
      bikeStatusIcon = '⚠️';
    }

    html += `
      <div class="youbike-item" style="border-bottom: 1px solid #eee; padding: 12px 0; ${index === stations.length - 1 ? 'border-bottom: none;' : ''}">
        <div class="data-row" style="margin-bottom: 8px;">
          <span class="data-label" style="font-weight: bold; color: #e67e22;">🚲 ${stationName}</span>
        </div>
        <div class="data-row">
          <span class="data-label">📍 ${labels.distance}</span>
          <span class="data-value">${distance}m (${walkText})</span>
        </div>
        <div class="data-row">
          <span class="data-label">🚴 ${labels.available_bikes}</span>
          <span class="data-value" style="color: ${bikeStatusColor}; font-weight: bold;">${bikeStatusIcon} ${availableBikes} ${bikeUnit}</span>
        </div>
        <div class="data-row">
          <span class="data-label">🅿️ ${labels.available_spaces}</span>
          <span class="data-value">${availableSpaces} ${spaceUnit}</span>
        </div>
        <div class="data-row">
          <span class="data-label">ℹ️ ${labels.bike_type}</span>
          <span class="data-value">${bikeType} (${serviceStatus})</span>
        </div>
      </div>
    `;
  });

  html += '</div>';
  return html;
}

function renderBusArrivals(arrivals, routeName) {
  const labels = LABELS[currentLanguage] || LABELS.zh;
  
  if (!arrivals || arrivals.length === 0) {
    return `<p>${labels.no_data}</p>`;
  }

  let html = '';
  
  const stopGroups = {};
  arrivals.forEach(arr => {
    const stopName = arr.stop_name || labels.unknown;
    if (!stopGroups[stopName]) {
      stopGroups[stopName] = [];
    }
    stopGroups[stopName].push(arr);
  });

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
      const directionText = arr.direction === 0 ? (currentLanguage === 'zh' ? '往 ↑' : currentLanguage === 'en' ? 'To ↑' : currentLanguage === 'ko' ? '방향 ↑' : currentLanguage === 'ja' ? '行き ↑' : currentLanguage === 'id' ? 'Ke ↑' : 'Đến ↑') : (currentLanguage === 'zh' ? '返 ↓' : currentLanguage === 'en' ? 'Return ↓' : currentLanguage === 'ko' ? '회차 ↓' : currentLanguage === 'ja' ? '戻り ↓' : currentLanguage === 'id' ? 'Kembali ↓' : 'Về ↓');
      const status = arr.status || labels.unknown;
      html += `
        <div style="display: flex; justify-content: space-between; width: 100%; padding: 2px 0;">
          <span style="font-size: 0.9em; opacity: 0.8;">${directionText}</span>
          <span class="data-value" style="font-size: 0.9em;">${status}</span>
        </div>
      `;
    });
    
    html += `</div>`;
  });

  return html;
}

function renderReverseGeocode(data) {
  const labels = LABELS[currentLanguage] || LABELS.zh;
  const displayName = data.display_name || labels.unknown;
  const city = data.city || '';
  const road = data.road || '';
  const houseNumber = data.house_number || '';
  const suburb = data.suburb || '';
  const admin = data.admin || '';
  const countryCode = data.country_code || '';
  const lat = data.lat?.toFixed(6) || '';
  const lon = data.lon?.toFixed(6) || '';

  let detailedAddress = [];
  if (city) detailedAddress.push(city);
  if (admin && admin !== city) detailedAddress.push(admin);
  if (suburb) detailedAddress.push(suburb);
  if (road) detailedAddress.push(road);
  if (houseNumber) detailedAddress.push(houseNumber);

  const addressText = detailedAddress.length > 0 ? detailedAddress.join(', ') : displayName;

  const mapsUrl = `https://www.google.com/maps?q=${lat},${lon}`;

  return `
    <div class="data-row">
      <span class="data-label">📍 ${labels.location}</span>
      <span class="data-value" style="font-weight: bold;">${displayName}</span>
    </div>
    ${city ? `
    <div class="data-row">
      <span class="data-label">🏙️ ${labels.city}</span>
      <span class="data-value">${city}</span>
    </div>
    ` : ''}
    ${road ? `
    <div class="data-row">
      <span class="data-label">🛣️ ${labels.road}</span>
      <span class="data-value">${road}${houseNumber ? ' ' + houseNumber : ''}</span>
    </div>
    ` : ''}
    ${suburb ? `
    <div class="data-row">
      <span class="data-label">🏘️ ${labels.area}</span>
      <span class="data-value">${suburb}</span>
    </div>
    ` : ''}
    <div class="data-row">
      <span class="data-label">🌐 ${labels.coordinates}</span>
      <span class="data-value" style="font-size: 0.85em;">${lat}, ${lon}</span>
    </div>
    <div class="data-row" style="margin-top: 8px;">
      <a href="${mapsUrl}" target="_blank" style="color: #0066cc; text-decoration: none; font-size: 0.9em;">
        🗺️ ${labels.view_in_maps} →
      </a>
    </div>
  `;
}

function renderNearbyStops(stops) {
  const labels = LABELS[currentLanguage] || LABELS.zh;
  
  if (!stops || stops.length === 0) {
    return `<p>${labels.no_data}</p>`;
  }

  let html = '';
  stops.slice(0, 5).forEach((stop, index) => {
    const stopName = stop.stop_name || labels.unknown;
    const distance = stop.distance_m ? `${Math.round(stop.distance_m)}m` : '';
    const walkTimeText = stop.walking_time_min ? `${currentLanguage === 'zh' ? '步行 ' : ''}${stop.walking_time_min}${currentLanguage === 'zh' ? ' 分' : currentLanguage === 'en' ? ' min walk' : currentLanguage === 'ko' ? '분 도보' : currentLanguage === 'ja' ? '分 徒歩' : currentLanguage === 'id' ? ' menit jalan' : ' phút đi bộ'}` : '';
    
    html += `
      <div class="data-row" style="margin-bottom: 8px;">
        <div style="flex: 1;">
          <div style="font-weight: 600; margin-bottom: 2px;">🚏 ${stopName}</div>
          <div style="font-size: 0.85em; opacity: 0.7;">${walkTimeText} ${distance ? `(${distance})` : ''}</div>
        </div>
      </div>
    `;
  });

  return html;
}

function renderDirections(data) {
  const labels = LABELS[currentLanguage] || LABELS.zh;
  const originLabel = data.origin_label || labels.origin;
  const destLabel = data.dest_label || labels.destination;
  const distanceM = data.distance_m;
  const durationS = data.duration_s;
  
  let distanceStr = '--';
  if (distanceM !== undefined) {
    if (distanceM >= 1000) {
      const kmUnit = currentLanguage === 'zh' ? '公里' : currentLanguage === 'en' ? ' km' : currentLanguage === 'ko' ? '킬로미터' : currentLanguage === 'ja' ? 'キロ' : currentLanguage === 'id' ? ' km' : ' km';
      distanceStr = `${(distanceM / 1000).toFixed(1)}${kmUnit}`;
    } else {
      const mUnit = currentLanguage === 'zh' ? '公尺' : currentLanguage === 'en' ? ' m' : currentLanguage === 'ko' ? '미터' : currentLanguage === 'ja' ? 'メートル' : currentLanguage === 'id' ? ' m' : ' m';
      distanceStr = `${Math.round(distanceM)}${mUnit}`;
    }
  }
  
  let durationStr = '--';
  if (durationS !== undefined) {
    const minutes = Math.round(durationS / 60);
    if (minutes >= 60) {
      const hours = Math.floor(minutes / 60);
      const mins = minutes % 60;
      const hourUnit = currentLanguage === 'zh' ? '小時' : currentLanguage === 'en' ? ' hr' : currentLanguage === 'ko' ? '시간' : currentLanguage === 'ja' ? '時間' : currentLanguage === 'id' ? ' jam' : ' giờ';
      const minUnit = currentLanguage === 'zh' ? '分鐘' : currentLanguage === 'en' ? ' min' : currentLanguage === 'ko' ? '분' : currentLanguage === 'ja' ? '分' : currentLanguage === 'id' ? ' menit' : ' phút';
      durationStr = mins > 0 ? `${hours}${hourUnit} ${mins}${minUnit}` : `${hours}${hourUnit}`;
    } else {
      const minUnit = currentLanguage === 'zh' ? '分鐘' : currentLanguage === 'en' ? ' min' : currentLanguage === 'ko' ? '분' : currentLanguage === 'ja' ? '分' : currentLanguage === 'id' ? ' menit' : ' phút';
      durationStr = `${minutes}${minUnit}`;
    }
  }
  
  let mapsLink = '';
  if (data.origin_lat && data.origin_lon && data.dest_lat && data.dest_lon) {
    const mapsUrl = `https://www.google.com/maps/dir/${data.origin_lat},${data.origin_lon}/${data.dest_lat},${data.dest_lon}`;
    mapsLink = `
      <div class="data-row" style="margin-top: 8px;">
        <a href="${mapsUrl}" target="_blank" style="color: #0066cc; text-decoration: none; font-size: 0.9em;">
          🗺️ ${labels.view_in_maps} →
        </a>
      </div>
    `;
  }
  
  return `
    <div class="data-row">
      <span class="data-label">📍 ${labels.origin}</span>
      <span class="data-value">${originLabel}</span>
    </div>
    <div class="data-row">
      <span class="data-label">🎯 ${labels.destination}</span>
      <span class="data-value">${destLabel}</span>
    </div>
    <div class="data-row">
      <span class="data-label">📏 ${labels.distance}</span>
      <span class="data-value">${distanceStr}</span>
    </div>
    <div class="data-row">
      <span class="data-label">⏱️ ${labels.estimated_time}</span>
      <span class="data-value">${durationStr}</span>
    </div>
    ${mapsLink}
  `;
}

function renderMetroArrivals(arrivals) {
  const labels = LABELS[currentLanguage] || LABELS.zh;
  
  if (!arrivals || arrivals.length === 0) {
    return `<p class="data-row">${labels.no_data}</p>`;
  }

  let html = '<div class="metro-arrivals">';

  const lineGroups = {};
  arrivals.forEach(arr => {
    const lineName = arr.line_name || labels.unknown;
    if (!lineGroups[lineName]) {
      lineGroups[lineName] = [];
    }
    lineGroups[lineName].push(arr);
  });

  Object.entries(lineGroups).forEach(([lineName, lineArrivals], index) => {
    html += `
      <div class="metro-line" style="border-bottom: 1px solid #eee; padding: 12px 0; ${index === Object.keys(lineGroups).length - 1 ? 'border-bottom: none;' : ''}">
        <div class="data-row" style="margin-bottom: 8px;">
          <span class="data-label" style="font-weight: bold; color: #0066cc;">🚇 ${lineName}</span>
        </div>
    `;
    
    lineArrivals.slice(0, 3).forEach(arr => {
      const dest = arr.destination || labels.unknown;
      const timeSec = arr.arrival_time_sec;
      const status = arr.train_status || labels.unknown;
      
      let timeStr = status;
      if (timeSec > 0) {
        const min = Math.floor(timeSec / 60);
        const sec = timeSec % 60;
        const minUnit = currentLanguage === 'zh' ? '分' : currentLanguage === 'en' ? ' min' : currentLanguage === 'ko' ? '분' : currentLanguage === 'ja' ? '分' : currentLanguage === 'id' ? ' menit' : ' phút';
        const secUnit = currentLanguage === 'zh' ? '秒' : currentLanguage === 'en' ? ' sec' : currentLanguage === 'ko' ? '초' : currentLanguage === 'ja' ? '秒' : currentLanguage === 'id' ? ' detik' : ' giây';
        timeStr = min > 0 ? `${min}${minUnit} ${sec}${secUnit}` : `${sec}${secUnit}`;
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

function renderMetroStations(stations) {
  const labels = LABELS[currentLanguage] || LABELS.zh;
  
  if (!stations || stations.length === 0) {
    return `<p class="data-row">${labels.no_data}</p>`;
  }

  let html = '<div class="metro-stations">';

  stations.forEach((station, index) => {
    const stationName = station.station_name || labels.unknown;
    const distanceUnit = currentLanguage === 'zh' ? '公尺' : currentLanguage === 'en' ? 'm' : currentLanguage === 'ko' ? '미터' : currentLanguage === 'ja' ? 'メートル' : currentLanguage === 'id' ? 'm' : 'm';
    const distance = station.distance_m ? `${Math.round(station.distance_m)} ${distanceUnit}` : '';
    const walkTimeText = station.walking_time_min ? `${currentLanguage === 'zh' ? '步行約 ' : ''}${station.walking_time_min}${currentLanguage === 'zh' ? ' 分鐘' : currentLanguage === 'en' ? ' min walk' : currentLanguage === 'ko' ? '분 도보' : currentLanguage === 'ja' ? '分 徒歩' : currentLanguage === 'id' ? ' menit jalan' : ' phút đi bộ'}` : '';
    const address = station.address || '';

    html += `
      <div class="metro-station-item" style="border-bottom: 1px solid #eee; padding: 12px 0; ${index === stations.length - 1 ? 'border-bottom: none;' : ''}">
        <div class="data-row" style="margin-bottom: 4px;">
          <span class="data-label" style="font-weight: bold; color: #0066cc;">🚇 ${stationName}</span>
        </div>
        ${distance ? `
        <div class="data-row">
          <span class="data-label">📏 ${labels.distance}</span>
          <span class="data-value">${distance}</span>
        </div>
        ` : ''}
        ${walkTimeText ? `
        <div class="data-row">
          <span class="data-label">🚶 ${labels.walking_time}</span>
          <span class="data-value">${walkTimeText}</span>
        </div>
        ` : ''}
        ${address ? `
        <div class="data-row">
          <span class="data-label">📍 ${labels.address}</span>
          <span class="data-value" style="font-size: 0.85em;">${address}</span>
        </div>
        ` : ''}
      </div>
    `;
  });

  html += '</div>';
  return html;
}

function renderForwardGeocode(data) {
  const labels = LABELS[currentLanguage] || LABELS.zh;
  const displayName = data.display_name || labels.unknown;
  const lat = data.lat?.toFixed(6) || '';
  const lon = data.lon?.toFixed(6) || '';
  const city = data.city || '';
  const road = data.road || '';
  const suburb = data.suburb || '';

  const mapsUrl = `https://www.google.com/maps?q=${lat},${lon}`;

  return `
    <div class="data-row">
      <span class="data-label">📍 ${labels.location}</span>
      <span class="data-value" style="font-weight: bold;">${displayName}</span>
    </div>
    ${city ? `
    <div class="data-row">
      <span class="data-label">🏙️ ${labels.city}</span>
      <span class="data-value">${city}</span>
    </div>
    ` : ''}
    ${road ? `
    <div class="data-row">
      <span class="data-label">🛣️ ${labels.road}</span>
      <span class="data-value">${road}</span>
    </div>
    ` : ''}
    ${suburb ? `
    <div class="data-row">
      <span class="data-label">🏘️ ${labels.area}</span>
      <span class="data-value">${suburb}</span>
    </div>
    ` : ''}
    <div class="data-row">
      <span class="data-label">🌐 ${labels.coordinates}</span>
      <span class="data-value" style="font-size: 0.85em;">${lat}, ${lon}</span>
    </div>
    <div class="data-row" style="margin-top: 8px;">
      <a href="${mapsUrl}" target="_blank" style="color: #0066cc; text-decoration: none; font-size: 0.9em;">
        🗺️ ${labels.view_in_maps} →
      </a>
    </div>
  `;
}

function renderEnvironmentContext(data) {
  const labels = LABELS[currentLanguage] || LABELS.zh;
  const label = data.label || labels.unknown;
  const detailedAddress = data.detailed_address || '';
  const lat = data.lat?.toFixed(6) || '';
  const lon = data.lon?.toFixed(6) || '';
  const accuracy = data.accuracy_m ? `${data.accuracy_m}m` : '';
  const device = data.device || {};
  const platform = device.platform || '';
  const tz = data.tz || '';

  const mapsUrl = `https://www.google.com/maps?q=${lat},${lon}`;

  return `
    <div class="data-row">
      <span class="data-label">📍 ${labels.location}</span>
      <span class="data-value" style="font-weight: bold;">${label}</span>
    </div>
    ${detailedAddress && detailedAddress !== label ? `
    <div class="data-row">
      <span class="data-label">🏠 ${labels.address}</span>
      <span class="data-value" style="font-size: 0.85em;">${detailedAddress}</span>
    </div>
    ` : ''}
    <div class="data-row">
      <span class="data-label">🌐 ${labels.coordinates}</span>
      <span class="data-value" style="font-size: 0.85em;">${lat}, ${lon} ${accuracy ? `(±${accuracy})` : ''}</span>
    </div>
    ${tz ? `
    <div class="data-row">
      <span class="data-label">⏰ 時區</span>
      <span class="data-value">${tz}</span>
    </div>
    ` : ''}
    ${platform ? `
    <div class="data-row">
      <span class="data-label">💻 設備</span>
      <span class="data-value">${platform}</span>
    </div>
    ` : ''}
    <div class="data-row" style="margin-top: 8px;">
      <a href="${mapsUrl}" target="_blank" style="color: #0066cc; text-decoration: none; font-size: 0.9em;">
        🗺️ ${labels.view_in_maps} →
      </a>
    </div>
  `;
}

function renderJSONFallback(data) {
  return `<pre style="font-size: 0.85em; white-space: pre-wrap;">${JSON.stringify(data, null, 2)}</pre>`;
}
