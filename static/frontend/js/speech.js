/**
 * 語音識別模組
 * 處理語音輸入和語音合成
 */

class SpeechRecognition {
    constructor() {
        this.recognition = null;
        this.isListening = false;
        this.isSupported = false;
        this.onResult = null;
        this.onError = null;
        this.onStart = null;
        this.onEnd = null;
        
        // 語音辨識上下文
        this.context = {
            userLocation: null,
            recentQueries: [],
            currentSession: null
        };
        
        this.initRecognition();
    }

    initRecognition() {
        // 檢查瀏覽器支援
        if ('webkitSpeechRecognition' in window) {
            this.recognition = new webkitSpeechRecognition();
            this.isSupported = true;
        } else if ('SpeechRecognition' in window) {
            this.recognition = new SpeechRecognition();
            this.isSupported = true;
        } else {
            console.warn('瀏覽器不支援語音識別');
            return;
        }

        // 設定語音識別參數
        this.recognition.continuous = false;
        this.recognition.interimResults = true;
        this.recognition.lang = 'zh-TW';
        this.recognition.maxAlternatives = 3;  // 增加候選結果數量

        // 綁定事件
        this.recognition.onstart = () => {
            this.isListening = true;
            console.log('🎤 語音識別開始');
            if (this.onStart) this.onStart();
        };

        this.recognition.onresult = (event) => {
            let finalTranscript = '';
            let interimTranscript = '';

            for (let i = event.resultIndex; i < event.results.length; i++) {
                const transcript = event.results[i][0].transcript;
                if (event.results[i].isFinal) {
                    finalTranscript += transcript;
                } else {
                    interimTranscript += transcript;
                }
            }

            console.log('🎤 語音識別原始結果:', finalTranscript || interimTranscript);
            
            // 使用語音增強功能
            let enhancedFinal = finalTranscript;
            let enhancedInterim = interimTranscript;
            
            if (window.speechEnhancer) {
                const context = this.getContext();
                
                if (finalTranscript) {
                    enhancedFinal = window.speechEnhancer.enhance(finalTranscript, context);
                }
                
                if (interimTranscript) {
                    enhancedInterim = window.speechEnhancer.enhance(interimTranscript, context);
                }
            }
            
            if (this.onResult) {
                this.onResult(enhancedFinal, enhancedInterim);
            }
        };

        this.recognition.onerror = (event) => {
            console.error('🎤 語音識別錯誤:', event.error);
            this.isListening = false;
            if (this.onError) this.onError(event.error);
        };

        this.recognition.onend = () => {
            this.isListening = false;
            console.log('🎤 語音識別結束');
            if (this.onEnd) this.onEnd();
        };
    }

    start() {
        if (!this.isSupported) {
            console.error('瀏覽器不支援語音識別');
            return false;
        }

        if (this.isListening) {
            console.warn('語音識別已在進行中');
            return false;
        }

        try {
            this.recognition.start();
            return true;
        } catch (error) {
            console.error('啟動語音識別失敗:', error);
            return false;
        }
    }

    stop() {
        if (this.recognition && this.isListening) {
            this.recognition.stop();
        }
    }

    abort() {
        if (this.recognition && this.isListening) {
            this.recognition.abort();
        }
    }
    
    /**
     * 設定用戶位置上下文
     */
    setUserLocation(location) {
        this.context.userLocation = location;
        console.log('📍 設定用戶位置上下文:', location);
    }
    
    /**
     * 添加查詢歷史
     */
    addRecentQuery(query) {
        if (query && typeof query === 'string') {
            this.context.recentQueries.unshift(query);
            // 只保留最近 10 次查詢
            if (this.context.recentQueries.length > 10) {
                this.context.recentQueries = this.context.recentQueries.slice(0, 10);
            }
            console.log('📝 添加查詢歷史:', query);
        }
    }
    
    /**
     * 獲取當前上下文
     */
    getContext() {
        return {
            ...this.context,
            timestamp: Date.now()
        };
    }
    
    /**
     * 清除上下文
     */
    clearContext() {
        this.context = {
            userLocation: null,
            recentQueries: [],
            currentSession: null
        };
        console.log('🗑️ 已清除語音辨識上下文');
    }
}

// 語音合成類
class TextToSpeech {
    constructor() {
        this.synth = window.speechSynthesis;
        this.isSupported = 'speechSynthesis' in window;
        this.isSpeaking = false;
        this.currentUtterance = null;
    }

    speak(text, options = {}) {
        if (!this.isSupported) {
            console.error('瀏覽器不支援語音合成');
            return false;
        }

        // 停止當前播放
        this.stop();

        const utterance = new SpeechSynthesisUtterance(text);
        
        // 設定參數
        utterance.lang = options.lang || 'zh-TW';
        utterance.rate = options.rate || 1.0;
        utterance.pitch = options.pitch || 1.0;
        utterance.volume = options.volume || 1.0;

        // 綁定事件
        utterance.onstart = () => {
            this.isSpeaking = true;
            console.log('🔊 語音合成開始');
        };

        utterance.onend = () => {
            this.isSpeaking = false;
            this.currentUtterance = null;
            console.log('🔊 語音合成結束');
        };

        utterance.onerror = (event) => {
            console.error('🔊 語音合成錯誤:', event.error);
            this.isSpeaking = false;
            this.currentUtterance = null;
        };

        this.currentUtterance = utterance;
        this.synth.speak(utterance);
        return true;
    }

    stop() {
        if (this.synth.speaking) {
            this.synth.cancel();
        }
        this.isSpeaking = false;
        this.currentUtterance = null;
    }

    pause() {
        if (this.synth.speaking && !this.synth.paused) {
            this.synth.pause();
        }
    }

    resume() {
        if (this.synth.paused) {
            this.synth.resume();
        }
    }
}

// 全域實例
window.speechRecognition = new SpeechRecognition();
window.textToSpeech = new TextToSpeech();
