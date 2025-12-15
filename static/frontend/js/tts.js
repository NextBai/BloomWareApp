let currentAudio = null;  // 當前播放的音頻對象
let isPlaying = false;    // 是否正在播放
let audioContext = null;  // 預先建立的 AudioContext（繞過自動播放限制）
let userGestureReceived = false;  // 是否已收到用戶手勢



function unlockAudioPlayback() {
  if (userGestureReceived) {
    return;
  }

  try {
    audioContext = new (window.AudioContext || window.webkitAudioContext)();

    const buffer = audioContext.createBuffer(1, 1, 22050);
    const source = audioContext.createBufferSource();
    source.buffer = buffer;
    source.connect(audioContext.destination);
    source.start(0);

    userGestureReceived = true;
  } catch (error) {
    console.warn('⚠️ 無法解鎖音頻播放:', error);
  }
}


async function speakText(text) {
  stopSpeaking();

  try {

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

    const audioBlob = await response.blob();
    const audioUrl = URL.createObjectURL(audioBlob);

    currentAudio = new Audio(audioUrl);
    isPlaying = true;

    currentAudio.onended = () => {
      isPlaying = false;
      URL.revokeObjectURL(audioUrl);
    };

    currentAudio.onerror = (e) => {
      console.error('❌ 音頻播放錯誤:', e);
      isPlaying = false;
      URL.revokeObjectURL(audioUrl);
    };

    try {
      const playPromise = currentAudio.play();

      if (playPromise !== undefined) {
        await playPromise;
      }
    } catch (playError) {
      if (playError.name === 'NotAllowedError') {
        console.warn('⚠️ 自動播放被阻止（瀏覽器政策）');
        console.warn('💡 解決方案：等待用戶下次點擊任意處播放');

        isPlaying = false;

        const playOnUserClick = async (e) => {
          if (e.target.closest('.mic-button') || e.target.closest('button')) {
            return;
          }

          try {
            await currentAudio.play();
            isPlaying = true;
            document.removeEventListener('click', playOnUserClick);
          } catch (retryError) {
            console.error('❌ 仍然無法播放:', retryError);
            URL.revokeObjectURL(audioUrl);
          }
        };

        document.addEventListener('click', playOnUserClick, { once: false });
        setTimeout(() => {
          document.removeEventListener('click', playOnUserClick);
          if (!isPlaying) {
            URL.revokeObjectURL(audioUrl);
          }
        }, 5000);

      } else {
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

function stopSpeaking() {
  if (currentAudio && isPlaying) {
    currentAudio.pause();
    currentAudio.currentTime = 0;
    isPlaying = false;
  }
}
