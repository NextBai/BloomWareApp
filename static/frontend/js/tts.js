// ========== TTS 核心變數 ==========
let currentAudio = null;  // 當前播放的音頻對象
let isPlaying = false;    // 是否正在播放
let audioContext = null;  // 預先建立的 AudioContext（繞過自動播放限制）
let userGestureReceived = false;  // 是否已收到用戶手勢

console.log('✅ TTS 模組已載入');

// ========== 用戶手勢處理（解鎖自動播放）==========

/**
 * 在用戶手勢時初始化 AudioContext
 * 應該在錄音開始時調用此函數
 */
function unlockAudioPlayback() {
  if (userGestureReceived) {
    console.log('⚠️ 音頻播放已解鎖，跳過');
    return;
  }

  try {
    // 建立 AudioContext（需要用戶手勢才能啟動）
    audioContext = new (window.AudioContext || window.webkitAudioContext)();

    // 播放一個靜音音頻來"解鎖"自動播放權限
    const buffer = audioContext.createBuffer(1, 1, 22050);
    const source = audioContext.createBufferSource();
    source.buffer = buffer;
    source.connect(audioContext.destination);
    source.start(0);

    userGestureReceived = true;
    console.log('✅ 音頻播放已解鎖（用戶手勢已授權）');
  } catch (error) {
    console.warn('⚠️ 無法解鎖音頻播放:', error);
  }
}

// ========== 語音播放函數（異步方式）==========

/**
 * 播放文字語音（異步方式）
 * 獲取完整音頻後立即播放，前端可同時顯示打字效果
 *
 * @param {string} text - 要播放的文字
 * @returns {Promise<void>}
 */
async function speakText(text) {
  // 停止之前的語音
  stopSpeaking();

  try {
    console.log('🔊 呼叫 TTS API...');

    // 呼叫後端 TTS API
    const response = await fetch('/api/tts', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${localStorage.getItem('jwt_token')}`
      },
      body: JSON.stringify({
        text: text,
        voice: 'nova',
        speed: 1.0
      })
    });

    if (!response.ok) {
      const error = await response.json();
      console.error('❌ TTS API 錯誤:', error);
      return;
    }

    // 取得音頻數據（MP3）
    const audioBlob = await response.blob();
    const audioUrl = URL.createObjectURL(audioBlob);

    // 建立 Audio 元素並播放
    currentAudio = new Audio(audioUrl);
    isPlaying = true;

    currentAudio.onended = () => {
      console.log('✅ 語音播放完成');
      isPlaying = false;
      URL.revokeObjectURL(audioUrl);
    };

    currentAudio.onerror = (e) => {
      console.error('❌ 音頻播放錯誤:', e);
      isPlaying = false;
      URL.revokeObjectURL(audioUrl);
    };

    // 嘗試播放（如果之前有用戶手勢，應該可以成功）
    try {
      const playPromise = currentAudio.play();

      if (playPromise !== undefined) {
        await playPromise;
        console.log('▶️ 開始播放語音');
      }
    } catch (playError) {
      // 處理瀏覽器自動播放策略限制
      if (playError.name === 'NotAllowedError') {
        console.warn('⚠️ 自動播放被阻止（瀏覽器政策）');
        console.warn('💡 解決方案：等待用戶下次點擊任意處播放');

        // 保持 Audio 元素，等待用戶點擊
        isPlaying = false;

        // 添加全域點擊監聽器（一次性）
        const playOnUserClick = async (e) => {
          // 避免干擾其他點擊事件
          if (e.target.closest('.mic-button') || e.target.closest('button')) {
            return;
          }

          try {
            await currentAudio.play();
            console.log('✅ 用戶點擊後自動播放成功');
            isPlaying = true;
            document.removeEventListener('click', playOnUserClick);
          } catch (retryError) {
            console.error('❌ 仍然無法播放:', retryError);
            URL.revokeObjectURL(audioUrl);
          }
        };

        // 監聽下次點擊（保留 5 秒）
        document.addEventListener('click', playOnUserClick, { once: false });
        setTimeout(() => {
          document.removeEventListener('click', playOnUserClick);
          if (!isPlaying) {
            URL.revokeObjectURL(audioUrl);
            console.log('⏱️ 超時未播放，釋放音頻資源');
          }
        }, 5000);

      } else {
        // 其他播放錯誤
        console.error('❌ 音頻播放失敗:', playError);
        isPlaying = false;
        URL.revokeObjectURL(audioUrl);
        throw playError;
      }
    }

  } catch (error) {
    console.error('❌ TTS 請求失敗:', error);
    isPlaying = false;
  }
}

/**
 * 停止當前語音播放
 */
function stopSpeaking() {
  if (currentAudio && isPlaying) {
    currentAudio.pause();
    currentAudio.currentTime = 0;
    isPlaying = false;
    console.log('⏹️ 停止語音播放');
  }
}
