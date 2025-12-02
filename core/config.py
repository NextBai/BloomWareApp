"""
Bloom Ware 統一配置管理中心
所有環境變數與敏感資訊的單一真理來源（Single Source of Truth）
"""

import os
import json
import base64
from typing import Optional, Dict, Any
from dotenv import load_dotenv

# 載入 .env 檔案（僅開發環境需要，Render 會自動注入環境變數）
load_dotenv()


class Settings:
    """統一配置管理中心"""

    # ===== 環境檢測 =====
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    IS_PRODUCTION: bool = ENVIRONMENT == "production"

    # ===== Firebase 配置 =====
    FIREBASE_PROJECT_ID: str = os.getenv("FIREBASE_PROJECT_ID", "")

    # Firebase 憑證：支援三種方式
    _firebase_creds_json: Optional[str] = os.getenv("FIREBASE_CREDENTIALS_JSON")
    _firebase_creds_base64: Optional[str] = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON_BASE64")
    _firebase_service_account_path: Optional[str] = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")

    @classmethod
    def get_firebase_credentials(cls) -> Dict[str, Any]:
        """
        取得 Firebase 憑證

        優先順序：
        1. 環境變數 FIREBASE_CREDENTIALS_JSON（生產環境，JSON 字串）
        2. 環境變數 FIREBASE_SERVICE_ACCOUNT_JSON_BASE64（base64 編碼的 JSON）
        3. 檔案路徑 FIREBASE_SERVICE_ACCOUNT_PATH（開發環境）

        Returns:
            dict: Firebase Service Account 憑證字典

        Raises:
            ValueError: 當所有方式都未設定時
        """
        # 方式 1: 直接 JSON 字串
        if cls._firebase_creds_json:
            try:
                return json.loads(cls._firebase_creds_json)
            except json.JSONDecodeError as e:
                raise ValueError(f"FIREBASE_CREDENTIALS_JSON 格式錯誤: {e}")

        # 方式 2: Base64 編碼的 JSON
        elif cls._firebase_creds_base64:
            try:
                decoded_bytes = base64.b64decode(cls._firebase_creds_base64)
                decoded_str = decoded_bytes.decode('utf-8')
                return json.loads(decoded_str)
            except Exception as e:
                raise ValueError(f"FIREBASE_SERVICE_ACCOUNT_JSON_BASE64 解碼失敗: {e}")

        # 方式 3: 從檔案讀取
        elif cls._firebase_service_account_path:
            try:
                with open(cls._firebase_service_account_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except FileNotFoundError:
                raise ValueError(f"Firebase 憑證檔案不存在: {cls._firebase_service_account_path}")
            except json.JSONDecodeError as e:
                raise ValueError(f"Firebase 憑證檔案格式錯誤: {e}")

        # 三種方式都沒設定
        else:
            raise ValueError(
                "Firebase 憑證未設定！\n"
                "請設定以下其中一項：\n"
                "1. FIREBASE_CREDENTIALS_JSON（JSON 字串）\n"
                "2. FIREBASE_SERVICE_ACCOUNT_JSON_BASE64（base64 編碼）\n"
                "3. FIREBASE_SERVICE_ACCOUNT_PATH（檔案路徑）"
            )

    # ===== OpenAI 配置 =====
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-5-nano")
    OPENAI_TIMEOUT: int = int(os.getenv("OPENAI_TIMEOUT", "30"))

    # ===== Google OAuth 配置 =====
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI: str = os.getenv(
        "GOOGLE_REDIRECT_URI",
        "http://localhost:8080/auth/google/callback"  # 開發環境預設值
    )

    # ===== 第三方 API Keys =====
    WEATHER_API_KEY: str = os.getenv("WEATHER_API_KEY", "")
    NEWSDATA_API_KEY: str = os.getenv("NEWSDATA_API_KEY", "")
    EXCHANGE_API_KEY: str = os.getenv("EXCHANGE_API_KEY", "")

    # ===== JWT 認證配置 =====
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

    # ===== 伺服器配置 =====
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8080"))  # Render 會自動設為 10000

    # ===== GPT 意圖檢測配置 =====
    USE_GPT_INTENT: bool = os.getenv("USE_GPT_INTENT", "true").lower() == "true"
    GPT_INTENT_MODEL: str = os.getenv("GPT_INTENT_MODEL", "gpt-5-nano")

    # ===== 背景任務開關 =====
    ENABLE_BACKGROUND_JOBS: bool = os.getenv("ENABLE_BACKGROUND_JOBS", "true").lower() == "true"

    # ===== 環境感知參數 =====
    ENV_CONTEXT_DISTANCE_THRESHOLD: float = float(os.getenv("ENV_CONTEXT_DISTANCE_THRESHOLD", "100"))
    ENV_CONTEXT_HEADING_THRESHOLD: float = float(os.getenv("ENV_CONTEXT_HEADING_THRESHOLD", "25"))
    ENV_CONTEXT_TTL_SECONDS: float = float(os.getenv("ENV_CONTEXT_TTL_SECONDS", "300"))

    # ===== CORS 安全設定 =====
    # 生產環境應設定具體的允許來源，多個來源用逗號分隔
    # 例如：CORS_ORIGINS=https://example.com,https://app.example.com
    _cors_origins_raw: str = os.getenv("CORS_ORIGINS", "*")

    @classmethod
    def get_cors_origins(cls) -> list:
        """取得 CORS 允許的來源列表"""
        if cls._cors_origins_raw == "*":
            return ["*"]
        return [origin.strip() for origin in cls._cors_origins_raw.split(",") if origin.strip()]

    # ===== 安全性設定 =====
    # 登入失敗封鎖閾值
    FAILED_LOGIN_THRESHOLD: int = int(os.getenv("FAILED_LOGIN_THRESHOLD", "5"))
    # 封鎖時間（秒）
    LOGIN_BLOCK_DURATION: int = int(os.getenv("LOGIN_BLOCK_DURATION", "900"))  # 15 分鐘
    # JWT Secret 最小長度
    JWT_SECRET_MIN_LENGTH: int = 32

    # ===== 效能調優常數 =====
    # WebSocket 會話超時（秒）
    WEBSOCKET_SESSION_TIMEOUT: int = int(os.getenv("WEBSOCKET_SESSION_TIMEOUT", "1800"))  # 30 分鐘
    # 定期清理間隔（秒）
    CLEANUP_INTERVAL: int = int(os.getenv("CLEANUP_INTERVAL", "1800"))  # 30 分鐘
    # 記憶重要性閾值
    MEMORY_IMPORTANCE_THRESHOLD: float = float(os.getenv("MEMORY_IMPORTANCE_THRESHOLD", "0.6"))
    # 意圖快取 TTL（秒）
    INTENT_CACHE_TTL: int = int(os.getenv("INTENT_CACHE_TTL", "300"))  # 5 分鐘
    # 對話歷史載入限制
    CHAT_HISTORY_LIMIT: int = int(os.getenv("CHAT_HISTORY_LIMIT", "12"))
    # 關懷模式對話歷史限制
    CARE_MODE_HISTORY_LIMIT: int = int(os.getenv("CARE_MODE_HISTORY_LIMIT", "3"))

    @classmethod
    def validate(cls) -> bool:
        """
        驗證必要配置是否已設定

        Returns:
            bool: 所有必要配置是否完整
        """
        required_fields = [
            ("FIREBASE_PROJECT_ID", cls.FIREBASE_PROJECT_ID),
            ("OPENAI_API_KEY", cls.OPENAI_API_KEY),
            ("GOOGLE_CLIENT_ID", cls.GOOGLE_CLIENT_ID),
            ("GOOGLE_CLIENT_SECRET", cls.GOOGLE_CLIENT_SECRET),
            ("JWT_SECRET_KEY", cls.JWT_SECRET_KEY),
        ]

        missing_fields = [name for name, value in required_fields if not value]

        if missing_fields:
            print(f"⚠️ 缺少必要環境變數: {', '.join(missing_fields)}")
            print("請檢查以下選項:")
            print("1. 環境變數是否正確設定")
            print("2. .env 檔案是否存在且格式正確")
            print("3. 生產環境中是否在部署平台設定了環境變數")
            return False

        # 驗證 Firebase 憑證
        try:
            cls.get_firebase_credentials()
        except ValueError as e:
            print(f"⚠️ Firebase 憑證驗證失敗: {e}")
            print("請檢查 FIREBASE_CREDENTIALS_JSON 或 FIREBASE_SERVICE_ACCOUNT_PATH")
            return False

        # 驗證 OpenAI API Key 格式（基本檢查）
        if not cls.OPENAI_API_KEY.startswith("sk-"):
            print("⚠️ OpenAI API Key 格式可能不正確（應以 'sk-' 開頭）")

        # 驗證 JWT Secret 長度（強制檢查）
        if len(cls.JWT_SECRET_KEY) < cls.JWT_SECRET_MIN_LENGTH:
            print(f"❌ JWT Secret Key 長度必須至少 {cls.JWT_SECRET_MIN_LENGTH} 個字符")
            if cls.IS_PRODUCTION:
                return False
            print("⚠️ 開發環境允許繼續，但生產環境將拒絕啟動")

        # 生產環境 CORS 檢查
        if cls.IS_PRODUCTION and cls._cors_origins_raw == "*":
            print("⚠️ 生產環境建議設定具體的 CORS_ORIGINS，而非 '*'")

        return True

    @classmethod
    def print_summary(cls) -> None:
        """列印當前配置摘要（隱藏敏感資訊）"""
        print("\n" + "=" * 60)
        print("📋 Bloom Ware 配置摘要")
        print("=" * 60)
        print(f"環境模式: {cls.ENVIRONMENT}")
        print(f"是否為生產環境: {cls.IS_PRODUCTION}")
        print(f"Firebase 專案 ID: {cls.FIREBASE_PROJECT_ID}")

        # 判斷 Firebase 憑證來源
        if cls._firebase_creds_json:
            firebase_source = "環境變數 (JSON)"
        elif cls._firebase_creds_base64:
            firebase_source = "環境變數 (Base64)"
        elif cls._firebase_service_account_path:
            firebase_source = "檔案"
        else:
            firebase_source = "未設定 ❌"
        print(f"Firebase 憑證來源: {firebase_source}")
        print(f"OpenAI 模型: {cls.OPENAI_MODEL}")
        print(f"OpenAI Timeout: {cls.OPENAI_TIMEOUT}s")
        print(f"Google OAuth 回調 URI: {cls.GOOGLE_REDIRECT_URI}")
        print(f"JWT Token 有效期: {cls.ACCESS_TOKEN_EXPIRE_MINUTES} 分鐘")
        print(f"伺服器監聽: {cls.HOST}:{cls.PORT}")
        print(f"使用 GPT 意圖檢測: {cls.USE_GPT_INTENT}")
        print(f"Weather API Key: {'已設定 ✅' if cls.WEATHER_API_KEY else '未設定 ❌'}")
        print(f"NewsData API Key: {'已設定 ✅' if cls.NEWSDATA_API_KEY else '未設定 ❌'}")
        print(f"Exchange API Key: {'已設定 ✅' if cls.EXCHANGE_API_KEY else '未設定 ❌'}")
        print(f"環境節流距離: {cls.ENV_CONTEXT_DISTANCE_THRESHOLD} m")
        print(f"環境節流方位差: {cls.ENV_CONTEXT_HEADING_THRESHOLD}°")
        print(f"環境快取 TTL: {cls.ENV_CONTEXT_TTL_SECONDS} 秒")
        print("=" * 60 + "\n")


# 建立全域設定實例（單例模式）
settings = Settings()


# 啟動時驗證配置（僅在非測試環境）
if __name__ != "__main__":
    import logging
    logger = logging.getLogger("core.config")

    if not settings.validate():
        logger.warning("⚠️ 配置驗證失敗，部分功能可能無法正常運作")

    # 開發環境下列印配置摘要
    if not settings.IS_PRODUCTION and os.getenv("BLOOMWARE_SHOW_CONFIG", "false").lower() == "true":
        settings.print_summary()
