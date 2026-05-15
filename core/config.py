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

    # Google Cloud Speech / TTS 專用服務帳戶（可與 Firebase 不同 GCP 專案）
    _google_speech_creds_json: Optional[str] = os.getenv("GOOGLE_SPEECH_CREDENTIALS_JSON")
    _google_speech_creds_base64: Optional[str] = os.getenv("GOOGLE_SPEECH_SERVICE_ACCOUNT_JSON_BASE64")
    _google_speech_sa_path: Optional[str] = os.getenv("GOOGLE_SPEECH_SERVICE_ACCOUNT_PATH")

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

    @classmethod
    def try_get_google_speech_credentials(cls) -> Optional[Dict[str, Any]]:
        """
        載入 STT/TTS 專用 Google 服務帳戶 JSON（與 Firebase 分離）。

        若三種來源皆未設定，回傳 None；若已設定但格式錯誤則拋出 ValueError。
        """
        if cls._google_speech_creds_json:
            try:
                return json.loads(cls._google_speech_creds_json)
            except json.JSONDecodeError as e:
                raise ValueError(f"GOOGLE_SPEECH_CREDENTIALS_JSON 格式錯誤: {e}") from e
        if cls._google_speech_creds_base64:
            try:
                decoded_bytes = base64.b64decode(cls._google_speech_creds_base64)
                return json.loads(decoded_bytes.decode("utf-8"))
            except Exception as e:
                raise ValueError(f"GOOGLE_SPEECH_SERVICE_ACCOUNT_JSON_BASE64 解碼失敗: {e}") from e
        if cls._google_speech_sa_path:
            try:
                with open(cls._google_speech_sa_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except FileNotFoundError:
                raise ValueError(f"GOOGLE_SPEECH_SERVICE_ACCOUNT_PATH 檔案不存在: {cls._google_speech_sa_path}") from None
            except json.JSONDecodeError as e:
                raise ValueError(f"GOOGLE_SPEECH_SERVICE_ACCOUNT_PATH JSON 格式錯誤: {e}") from e
        return None

    @classmethod
    def resolve_speech_service_account_info(cls) -> tuple[Optional[Dict[str, Any]], str]:
        """
        解析語音 API 使用的服務帳戶：優先 GOOGLE_SPEECH_*，否則退回 Firebase 憑證（相容舊部署）。

        Returns:
            (credentials_dict | None, "speech" | "firebase" | "none")
        """
        speech = cls.try_get_google_speech_credentials()
        if speech is not None:
            return speech, "speech"
        try:
            return cls.get_firebase_credentials(), "firebase"
        except ValueError:
            return None, "none"

    @classmethod
    def get_google_speech_project_id(cls, credential_project_id: Optional[str] = None) -> str:
        """
        Speech-to-Text recognizer 所屬 GCP 專案 ID。

        優先順序：GOOGLE_SPEECH_PROJECT_ID → GOOGLE_CLOUD_PROJECT_ID（若為純數字「專案編號」
        且憑證 JSON 內有字串型 project_id，則改用憑證內 ID，避免誤用編號）→
        憑證 JSON 內 project_id → FIREBASE_PROJECT_ID
        """
        if cls.GOOGLE_SPEECH_PROJECT_ID.strip():
            return cls.GOOGLE_SPEECH_PROJECT_ID.strip()
        cloud = cls.GOOGLE_CLOUD_PROJECT_ID.strip()
        cred = (credential_project_id or "").strip()
        if cloud.isdigit() and cred and not cred.isdigit():
            return cred
        if cloud:
            return cloud
        if cred:
            return cred
        return cls.FIREBASE_PROJECT_ID.strip()

    # ===== OpenAI 配置 =====
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-5.4")
    OPENAI_TIMEOUT: int = int(os.getenv("OPENAI_TIMEOUT", "30"))
    OPENAI_RESPONSES_TIMEOUT: int = int(os.getenv("OPENAI_RESPONSES_TIMEOUT", "90"))
    OPENAI_USE_RESPONSES: bool = os.getenv("OPENAI_USE_RESPONSES", "true").lower() == "true"
    OPENAI_MODEL_CONTEXT_WINDOW: int = int(os.getenv("OPENAI_MODEL_CONTEXT_WINDOW", "1000000"))
    OPENAI_MODEL_AUTO_COMPACT_TOKEN_LIMIT: int = int(os.getenv("OPENAI_MODEL_AUTO_COMPACT_TOKEN_LIMIT", "900000"))
    OPENAI_ENABLE_WEB_SEARCH: bool = os.getenv("OPENAI_ENABLE_WEB_SEARCH", "true").lower() == "true"
    OPENAI_ENABLE_REMOTE_MCP: bool = os.getenv("OPENAI_ENABLE_REMOTE_MCP", "false").lower() == "true"
    OPENAI_REMOTE_MCP_SERVERS_JSON: str = os.getenv("OPENAI_REMOTE_MCP_SERVERS_JSON", "[]")
    OPENAI_ENABLE_SKILLS: bool = os.getenv("OPENAI_ENABLE_SKILLS", "false").lower() == "true"

    # ===== Google OAuth（使用者「登入 Bloom Ware」用，非語音 API）=====
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI: str = os.getenv(
        "GOOGLE_REDIRECT_URI",
        "http://localhost:8080/auth/google/callback"  # 開發環境預設值
    )
    # ----- Google Cloud「語音」專案（STT/TTS，例：supervisor-project；常與 Firebase 不同）-----
    # GOOGLE_CLOUD_PROJECT_ID：語音相關 REST/專案語境之預設專案 ID（請填「專案 ID」字串，勿只填控制台「專案編號」）
    GOOGLE_CLOUD_PROJECT_ID: str = os.getenv("GOOGLE_CLOUD_PROJECT_ID", os.getenv("FIREBASE_PROJECT_ID", ""))
    # GOOGLE_SPEECH_PROJECT_ID：明確指定 STT recognizer 所屬專案；與 Firebase 分離時必須搭配 GOOGLE_SPEECH_* 服務帳戶
    GOOGLE_SPEECH_PROJECT_ID: str = os.getenv("GOOGLE_SPEECH_PROJECT_ID", "")
    # STT gRPC 臨時除錯用；正式環境請用服務帳戶
    GOOGLE_STT_ACCESS_TOKEN: str = os.getenv("GOOGLE_STT_ACCESS_TOKEN", "")
    # TTS 與部分 REST 用 API Key（屬於語音 GCP；與 STT 串流 gRPC OAuth 分開）
    GOOGLE_SPEECH_API_KEY: str = os.getenv("GOOGLE_SPEECH_API_KEY", os.getenv("GOOGLE_API_KEY", ""))
    GOOGLE_TTS_API_KEY: str = os.getenv("GOOGLE_TTS_API_KEY", os.getenv("GOOGLE_API_KEY", ""))
    GOOGLE_STT_LOCATION: str = os.getenv("GOOGLE_STT_LOCATION", "global")
    GOOGLE_STT_RECOGNIZER_ID: str = os.getenv("GOOGLE_STT_RECOGNIZER_ID", "_")
    GOOGLE_STT_AUTO_LANGUAGE_CODES: str = os.getenv("GOOGLE_STT_AUTO_LANGUAGE_CODES", "cmn-Hant-TW,en-US,ja-JP")
    GOOGLE_TTS_LANGUAGE_CODE: str = os.getenv("GOOGLE_TTS_LANGUAGE_CODE", "cmn-TW")
    GOOGLE_TTS_DEFAULT_VOICE: str = os.getenv("GOOGLE_TTS_DEFAULT_VOICE", "cmn-TW-Wavenet-A")

    # ===== 第三方 API Keys =====
    WEATHER_API_KEY: str = os.getenv("WEATHER_API_KEY", "")
    TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")
    EXCHANGE_API_KEY: str = os.getenv("EXCHANGE_API_KEY", "")

    # ===== JWT 認證配置 =====
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

    # ===== 伺服器配置 =====
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8080"))  # Render 會自動設為 10000

    # ===== GPT 意圖檢測配置 =====
    USE_GPT_INTENT: bool = os.getenv("USE_GPT_INTENT", "true").lower() == "true"
    GPT_INTENT_MODEL: str = os.getenv("GPT_INTENT_MODEL", "gpt-5.4")

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
            import logging
            logger = logging.getLogger("core.config")
            logger.error(f"⚠️ 缺少必要環境變數: {', '.join(missing_fields)}")
            logger.error("請檢查以下選項:")
            logger.error("1. 環境變數是否正確設定")
            logger.error("2. .env 檔案是否存在且格式正確")
            logger.error("3. 生產環境中是否在部署平台設定了環境變數")
            return False

        # 驗證 Firebase 憑證
        try:
            cls.get_firebase_credentials()
        except ValueError as e:
            import logging
            logger = logging.getLogger("core.config")
            logger.error(f"⚠️ Firebase 憑證驗證失敗: {e}")
            logger.error("請檢查 FIREBASE_CREDENTIALS_JSON 或 FIREBASE_SERVICE_ACCOUNT_PATH")
            return False

        # 驗證 OpenAI API Key 格式（OpenAI-compatible relay keys may not use sk-*）
        if not cls.OPENAI_BASE_URL and not cls.OPENAI_API_KEY.startswith("sk-"):
            import logging
            logger = logging.getLogger("core.config")
            logger.warning("⚠️ OpenAI API Key 格式可能不正確（應以 'sk-' 開頭）")

        # 驗證 JWT Secret 長度（強制檢查）
        if len(cls.JWT_SECRET_KEY) < cls.JWT_SECRET_MIN_LENGTH:
            import logging
            logger = logging.getLogger("core.config")
            logger.error(f"❌ JWT Secret Key 長度必須至少 {cls.JWT_SECRET_MIN_LENGTH} 個字符")
            if cls.IS_PRODUCTION:
                return False
            logger.warning("⚠️ 開發環境允許繼續，但生產環境將拒絕啟動")

        # 生產環境 CORS 檢查
        if cls.IS_PRODUCTION and cls._cors_origins_raw == "*":
            import logging
            logger = logging.getLogger("core.config")
            logger.warning("⚠️ 生產環境建議設定具體的 CORS_ORIGINS，而非 '*'")

        return True

    @classmethod
    def print_summary(cls) -> None:
        """列印當前配置摘要（隱藏敏感資訊）"""
        import logging
        logger = logging.getLogger("core.config")
        logger.info("\n" + "=" * 60)
        logger.info("📋 Bloom Ware 配置摘要")
        logger.info("=" * 60)
        logger.info(f"環境模式: {cls.ENVIRONMENT}")
        logger.info(f"是否為生產環境: {cls.IS_PRODUCTION}")
        logger.info(f"Firebase 專案 ID: {cls.FIREBASE_PROJECT_ID}")

        # 判斷 Firebase 憑證來源
        if cls._firebase_creds_json:
            firebase_source = "環境變數 (JSON)"
        elif cls._firebase_creds_base64:
            firebase_source = "環境變數 (Base64)"
        elif cls._firebase_service_account_path:
            firebase_source = "檔案"
        else:
            firebase_source = "未設定 ❌"
        logger.info(f"Firebase 憑證來源: {firebase_source}")
        logger.info(f"OpenAI 模型: {cls.OPENAI_MODEL}")
        logger.info(f"OpenAI Base URL: {cls.OPENAI_BASE_URL or 'default'}")
        logger.info(f"OpenAI Responses API: {'enabled' if cls.OPENAI_USE_RESPONSES else 'disabled'}")
        logger.info(f"OpenAI Timeout: {cls.OPENAI_TIMEOUT}s")
        logger.info(f"OpenAI Responses Timeout: {cls.OPENAI_RESPONSES_TIMEOUT}s")
        logger.info(f"Google OAuth 回調 URI: {cls.GOOGLE_REDIRECT_URI}")
        logger.info(f"JWT Token 有效期: {cls.ACCESS_TOKEN_EXPIRE_MINUTES} 分鐘")
        logger.info(f"伺服器監聽: {cls.HOST}:{cls.PORT}")
        logger.info(f"使用 GPT 意圖檢測: {cls.USE_GPT_INTENT}")
        logger.info(f"Weather API Key: {'已設定 ✅' if cls.WEATHER_API_KEY else '未設定 ❌'}")
        logger.info(f"NewsData API Key: {'已設定 ✅' if cls.NEWSDATA_API_KEY else '未設定 ❌'}")
        logger.info(f"Exchange API Key: {'已設定 ✅' if cls.EXCHANGE_API_KEY else '未設定 ❌'}")
        logger.info(f"環境節流距離: {cls.ENV_CONTEXT_DISTANCE_THRESHOLD} m")
        logger.info(f"環境節流方位差: {cls.ENV_CONTEXT_HEADING_THRESHOLD}°")
        logger.info(f"環境快取 TTL: {cls.ENV_CONTEXT_TTL_SECONDS} 秒")
        logger.info("=" * 60 + "\n")


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
