import os
import logging
from typing import Optional

# ANSI 轉義序列
class LogColor:
    DEBUG = "\x1b[38;20m"    # 灰色
    INFO = "\x1b[32;20m"     # 綠色
    WARNING = "\x1b[33;20m"  # 黃色
    ERROR = "\x1b[31;20m"    # 紅色
    CRITICAL = "\x1b[31;1m"   # 粗體紅
    RESET = "\x1b[0m"
    GRAY = "\x1b[90m"        # 淺灰色
    CYAN = "\x1b[36;20m"     # 青色
    BLUE = "\x1b[34;20m"     # 藍色
    MAGENTA = "\x1b[35;20m"  # 品紅

class ColoredFormatter(logging.Formatter):
    """自定義彩色日誌格式化器"""
    
    LEVEL_COLORS = {
        logging.DEBUG: LogColor.GRAY,
        logging.INFO: LogColor.INFO,
        logging.WARNING: LogColor.WARNING,
        logging.ERROR: LogColor.ERROR,
        logging.CRITICAL: LogColor.CRITICAL
    }

    def format(self, record):
        level_color = self.LEVEL_COLORS.get(record.levelno, LogColor.RESET)
        
        # 格式化時間（淡灰色）
        asctime = self.formatTime(record, self.datefmt)
        asctime_colored = f"{LogColor.GRAY}{asctime}{LogColor.RESET}"
        
        # 格式化名稱（青色）
        name_colored = f"{LogColor.CYAN}{record.name}{LogColor.RESET}"
        
        # 格式化等級（根據等級變色）
        levelname_colored = f"{level_color}{record.levelname:8}{LogColor.RESET}"
        
        # 格式化訊息
        message = record.getMessage()
        
        # 自動截斷過長的訊息（如工具調用的完整原始數據）
        if len(message) > 500:
            message = message[:500] + f"{LogColor.GRAY}... [已截斷，共 {len(message)} 字元]{LogColor.RESET}"

        if "✅" in message:
            message = f"{LogColor.INFO}{message}{LogColor.RESET}"
        elif "❌" in message or "⚠️" in message:
            message = f"{LogColor.ERROR}{message}{LogColor.RESET}"
        elif "🎙️" in message or "🔊" in message:
            message = f"{LogColor.BLUE}{message}{LogColor.RESET}"
        elif "🌐" in message or "MCP" in message:
            message = f"{LogColor.MAGENTA}{message}{LogColor.RESET}"
        else:
            message = f"{level_color}{message}{LogColor.RESET}"
            
        return f"{asctime_colored} | {name_colored} | {levelname_colored} | {message}"

# 全域日誌等級
_LOG_LEVEL_NAME = os.getenv("BLOOMWARE_LOG_LEVEL", "INFO").upper()
_LOG_LEVEL = getattr(logging, _LOG_LEVEL_NAME, logging.INFO)

def get_log_level() -> int:
    return _LOG_LEVEL

def setup_logging(
    name: Optional[str] = None,
    level: Optional[int] = None,
) -> logging.Logger:
    if level is None:
        level = _LOG_LEVEL

    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(ColoredFormatter())
        logger.addHandler(console_handler)

    logger.propagate = False
    return logger

def get_logger(name: str) -> logging.Logger:
    return setup_logging(name)

def get_level_name() -> str:
    return _LOG_LEVEL_NAME

# 預設配置 root logger
_root_configured = False

def configure_root_logger():
    global _root_configured
    if not _root_configured:
        root = logging.getLogger()
        root.setLevel(get_log_level())
        
        # 清除現有的 handlers
        for handler in root.handlers[:]:
            root.removeHandler(handler)
            
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(ColoredFormatter())
        root.addHandler(console_handler)
        
        _root_configured = True

# 自動配置
configure_root_logger()

# 關閉 Speechbrain 等吵雜的日誌
logging.getLogger("speechbrain").setLevel(logging.WARNING)
logging.getLogger("werkzeug").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
