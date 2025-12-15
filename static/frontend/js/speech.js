
class SpeechRecognition {
    constructor() {
        this.recognition = null;
        this.isListening = false;
        this.isSupported = false;
        this.onResult = null;
        this.onError = null;
        this.onStart = null;
        this.onEnd = null;
        
        this.context = {
            userLocation: null,
            recentQueries: [],
            currentSession: null
        };
        
        this.initRecognition();
    }

    initRecognition() {
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

        this.recognition.continuous = false;
        this.recognition.interimResults = true;
        this.recognition.lang = 'zh-TW';
        this.recognition.maxAlternatives = 3;  // 增加候選結果數量

        this.recognition.onstart = () => {
            this.isListening = true;
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
    
    setUserLocation(location) {
        this.context.userLocation = location;
    }
    
    addRecentQuery(query) {
        if (query && typeof query === 'string') {
            this.context.recentQueries.unshift(query);
            if (this.context.recentQueries.length > 10) {
                this.context.recentQueries = this.context.recentQueries.slice(0, 10);
            }
        }
    }
    
    getContext() {
        return {
            ...this.context,
            timestamp: Date.now()
        };
    }
    
    clearContext() {
        this.context = {
            userLocation: null,
            recentQueries: [],
            currentSession: null
        };
    }
}

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

        this.stop();

        const utterance = new SpeechSynthesisUtterance(text);
        
        utterance.lang = options.lang || 'zh-TW';
        utterance.rate = options.rate || 1.0;
        utterance.pitch = options.pitch || 1.0;
        utterance.volume = options.volume || 1.0;

        utterance.onstart = () => {
            this.isSpeaking = true;
        };

        utterance.onend = () => {
            this.isSpeaking = false;
            this.currentUtterance = null;
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

window.speechRecognition = new SpeechRecognition();
window.textToSpeech = new TextToSpeech();
