"use client"

import { useEffect } from "react"
import { Button } from "@/components/ui/button"
import { TulipIllustration } from "@/components/tulip-illustration"
import { Mic } from "lucide-react"

export function LoginForm() {
  // 處理 OAuth callback
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    const state = params.get('state');
    const error = params.get('error');

    if (error) {
      console.error('❌ OAuth 錯誤:', error);
      alert(`Google 登入失敗: ${error}`);
      // 清除 URL 參數
      window.history.replaceState({}, '', window.location.pathname);
      return;
    }

    if (code && state) {
      console.log('🔍 檢測到 OAuth callback，處理授權碼...');
      handleOAuthCallback(code, state);
    }
  }, []);

  const handleOAuthCallback = async (code: string, state: string) => {
    try {
      // 從 sessionStorage 獲取 PKCE 參數
      const storedState = sessionStorage.getItem('oauth_state');
      const codeVerifier = sessionStorage.getItem('oauth_code_verifier');

      console.log('🔐 驗證 state 參數...');
      if (state !== storedState) {
        throw new Error('State 參數不匹配，可能存在 CSRF 攻擊');
      }

      console.log('📤 發送授權碼到後端...');
      const response = await fetch('/auth/google/callback', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          code,
          state,
          code_verifier: codeVerifier,
        }),
      });

      const data = await response.json();

      if (data.success) {
        console.log('✅ 登入成功！');

        // 存儲 JWT token
        localStorage.setItem('jwt_token', data.access_token);

        // 清除 sessionStorage
        sessionStorage.removeItem('oauth_state');
        sessionStorage.removeItem('oauth_code_verifier');

        // 清除 URL 參數並導向主應用
        window.history.replaceState({}, '', window.location.pathname);

        // 導向主應用頁面
        window.location.href = '/static/';
      } else {
        throw new Error(data.error || '登入失敗');
      }
    } catch (error) {
      console.error('❌ OAuth callback 處理失敗:', error);
      alert(`登入處理失敗: ${error}`);

      // 清除 URL 參數
      window.history.replaceState({}, '', window.location.pathname);
    }
  };

  const handleGoogleLogin = async () => {
    try {
      console.log('🚀 開始 Google OAuth 登入流程...');

      // 從後端獲取授權 URL 和 PKCE 參數
      const response = await fetch('/auth/google/url');
      const data = await response.json();

      if (!data.success) {
        throw new Error(data.error || '獲取授權 URL 失敗');
      }

      console.log('✅ 獲取授權 URL 成功');

      // 存儲 PKCE 參數到 sessionStorage
      sessionStorage.setItem('oauth_state', data.state);
      sessionStorage.setItem('oauth_code_verifier', data.code_verifier);

      console.log('🔐 PKCE 參數已存儲');

      // 重定向到 Google 授權頁面
      console.log('🌐 重定向到 Google 授權頁面...');
      window.location.href = data.auth_url;

    } catch (error) {
      console.error('❌ OAuth 初始化失敗:', error);
      alert('Google 登入初始化失敗，請稍後再試');
    }
  }

  const handleVoiceLogin = () => {
    console.log('🎤 開始語音登入...');

    // 存儲匿名語音登入 token
    localStorage.setItem('jwt_token', 'anonymous_voice_login');

    // 導向主應用頁面（語音登入模式）
    window.location.href = '/static/';
  }

  return (
    <div className="flex flex-col items-center space-y-6 sm:space-y-8">
      <div className="text-center space-y-1 sm:space-y-2">
        <h1 className="font-serif text-4xl sm:text-5xl md:text-6xl text-[#2C2C2C] tracking-wide text-balance">
          Bloom Ware
        </h1>
        <p className="text-[#4A4A4A] text-xs sm:text-sm tracking-widest uppercase">MADE BY 槓上開發</p>
      </div>

      <div className="my-4 sm:my-6 md:my-8">
        <TulipIllustration size="large" />
      </div>

      <div className="w-full space-y-3 sm:space-y-4">
        {/* Google Login */}
        <Button
          onClick={handleGoogleLogin}
          className="w-full h-11 sm:h-12 bg-white hover:bg-gray-50 text-[#2C2C2C] shadow-md hover:shadow-lg transition-all duration-200 rounded-lg border border-gray-200 text-sm sm:text-base"
          variant="outline"
        >
          <svg className="w-4 h-4 sm:w-5 sm:h-5 mr-2 sm:mr-3" viewBox="0 0 24 24">
            <path
              fill="#4285F4"
              d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
            />
            <path
              fill="#34A853"
              d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
            />
            <path
              fill="#FBBC05"
              d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
            />
            <path
              fill="#EA4335"
              d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
            />
          </svg>
          <span className="font-medium">Continue with Google</span>
        </Button>

        {/* Voice Login */}
        <Button
          onClick={handleVoiceLogin}
          className="w-full h-11 sm:h-12 bg-white hover:bg-gray-50 text-[#2C2C2C] shadow-md hover:shadow-lg transition-all duration-200 rounded-lg border border-gray-200 text-sm sm:text-base"
          variant="outline"
        >
          <Mic className="w-4 h-4 sm:w-5 sm:h-5 mr-2 sm:mr-3" />
          <span className="font-medium">Voice Login</span>
        </Button>
      </div>

      <p className="text-[#4A4A4A] text-[10px] sm:text-xs text-center mt-6 sm:mt-8 max-w-xs text-balance px-4">
        By continuing, you agree to our Terms of Service and Privacy Policy
      </p>
    </div>
  )
}
