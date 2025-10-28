"""
數據庫模組 - 整合 Firestore 操作、緩存、優化策略

結構：
- base.py: 基礎 Firestore 操作（用戶、對話、消息、記憶）
- cache.py: LRU 緩存實現（多級緩存、寫入緩衝）
- optimized.py: 優化版數據庫操作（帶緩存、請求合併、批量寫入）

使用建議：
- 高頻讀取操作：使用 optimized 版本（get_user_by_id, get_chat, get_user_chats）
- 寫入操作：使用 base 版本（create_chat, update_chat_title, delete_chat）
- 緩存管理：使用 cache.db_cache
"""

# 從 base 導入基礎設施
from .base import (
    connect_to_firestore,
    firestore_db,
    users_collection,
    chats_collection,
    messages_collection,
    memories_collection,
    ensure_indexes,
)

# 從 base 導入基礎操作（未優化）
from .base import (
    create_chat,
    save_message,
    update_chat_title,
    delete_chat,
    set_chat_emotion,
    get_chat_emotion,
    set_user_speaker_label,
    get_user_by_speaker_label,
    save_memory,
    search_memories,
    update_memory_importance,
    delete_memory,
    cleanup_old_memories,
    get_user_history,
    create_or_login_google_user,
)

# 從 optimized 導入優化版操作（帶緩存）
from .optimized import (
    get_user_by_id,
    get_user_chats,
    get_chat,
    save_chat_message,
    get_user_memories,
    batch_writer,
    query_optimizer,
)

# 從 cache 導入緩存管理
from .cache import db_cache, periodic_cache_maintenance

__all__ = [
    # 基礎設施
    "connect_to_firestore",
    "firestore_db",
    "users_collection",
    "chats_collection",
    "messages_collection",
    "memories_collection",
    "ensure_indexes",

    # 用戶操作
    "get_user_by_id",  # 優化版
    "create_or_login_google_user",
    "set_user_speaker_label",
    "get_user_by_speaker_label",

    # 對話操作
    "create_chat",
    "get_chat",  # 優化版
    "get_user_chats",  # 優化版
    "save_chat_message",  # 優化版
    "update_chat_title",
    "delete_chat",
    "set_chat_emotion",
    "get_chat_emotion",

    # 消息操作
    "save_message",
    "get_user_history",

    # 記憶操作
    "save_memory",
    "get_user_memories",  # 優化版
    "search_memories",
    "update_memory_importance",
    "delete_memory",
    "cleanup_old_memories",

    # 優化工具
    "batch_writer",
    "query_optimizer",
    "db_cache",
    "periodic_cache_maintenance",
]
