"""
優化後的數據庫調用層
整合緩存、批量操作、請求合併等優化策略
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
import asyncio

from .base import (
    firestore_db, users_collection, chats_collection,
    messages_collection,
    get_user_by_id as _get_user_by_id_original,
    get_chat as _get_chat_original,
    get_user_chats as _get_user_chats_original,
    save_message as _save_message_original,
    save_chat_message as _save_chat_message_original,
    get_user_memories as _get_user_memories_original,
)
from .cache import db_cache

logger = logging.getLogger("DatabaseOptimized")


# ==================== 用戶操作優化 ====================

async def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    """
    優化版：獲取用戶資料（帶緩存）
    
    優化策略：
    1. 先查緩存
    2. 緩存未命中時，使用請求合併避免重複查詢
    3. 查詢結果寫入緩存
    """
    # 1. 檢查緩存
    cached_user = await db_cache.get_user_cached(user_id)
    if cached_user is not None:
        logger.debug(f"用戶緩存命中: {user_id}")
        return cached_user
    
    # 2. 使用請求合併
    cache_key = f"fetch_user:{user_id}"
    
    async def fetch_user():
        logger.debug(f"從數據庫獲取用戶: {user_id}")
        user = await _get_user_by_id_original(user_id)
        if user:
            # 寫入緩存
            await db_cache.set_user_cache(user_id, user)
        return user
    
    return await db_cache.coalesce_request(cache_key, fetch_user)


# ==================== 對話操作優化 ====================

async def get_chat(chat_id: str) -> Dict[str, Any]:
    """
    優化版：獲取對話（帶緩存）
    
    優化策略：
    1. 先查緩存
    2. 緩存未命中時查詢數據庫
    3. 結果寫入緩存
    """
    # 1. 檢查緩存
    cached_chat = await db_cache.get_chat_cached(chat_id)
    if cached_chat is not None:
        logger.debug(f"對話緩存命中: {chat_id}")
        return {"success": True, "chat": cached_chat}
    
    # 2. 使用請求合併
    cache_key = f"fetch_chat:{chat_id}"
    
    async def fetch_chat():
        logger.debug(f"從數據庫獲取對話: {chat_id}")
        result = await _get_chat_original(chat_id)
        if result.get("success") and result.get("chat"):
            # 寫入緩存
            await db_cache.set_chat_cache(chat_id, result["chat"])
        return result
    
    return await db_cache.coalesce_request(cache_key, fetch_chat)


async def get_user_chats(user_id: str) -> Dict[str, Any]:
    """
    優化版：獲取用戶對話列表（帶緩存）
    
    優化策略：
    1. 先查緩存
    2. 緩存未命中時查詢數據庫
    3. 結果寫入緩存（短時間）
    """
    # 1. 檢查緩存
    cached_chats = await db_cache.get_user_chats_cached(user_id)
    if cached_chats is not None:
        logger.debug(f"用戶對話列表緩存命中: {user_id}")
        return {"success": True, "chats": cached_chats}
    
    # 2. 使用請求合併
    cache_key = f"fetch_user_chats:{user_id}"
    
    async def fetch_chats():
        logger.debug(f"從數據庫獲取用戶對話列表: {user_id}")
        result = await _get_user_chats_original(user_id)
        if result.get("success") and result.get("chats"):
            # 寫入緩存
            await db_cache.set_user_chats_cache(user_id, result["chats"])
        return result
    
    return await db_cache.coalesce_request(cache_key, fetch_chats)


async def save_chat_message(chat_id: str, sender: str, content: str, buffered: bool = False) -> Dict[str, Any]:
    """
    優化版：保存對話消息（支援批量緩衝）

    優化策略：
    1. buffered=True: 先放入緩衝區，10秒或50條後批量寫入（適用於高頻場景）
    2. buffered=False: 直接寫入（確保數據一致性，適用於關鍵操作）
    3. 使對話緩存失效
    """
    try:
        if buffered:
            # 使用緩衝寫入（非阻塞）
            should_flush = await db_cache.buffer_write("messages", {
                "chat_id": chat_id,
                "sender": sender,
                "content": content,
                "timestamp": datetime.now()
            })

            # 如果緩衝區已滿，觸發批量寫入（後台執行）
            if should_flush:
                import asyncio
                asyncio.create_task(_flush_message_buffer())

            # 使對話緩存失效
            await db_cache.invalidate_chat_cache(chat_id)

            return {"success": True, "buffered": True}
        else:
            # 直接寫入（阻塞）
            result = await _save_chat_message_original(chat_id, sender, content)
            if result.get("success"):
                # 使對話緩存失效
                await db_cache.invalidate_chat_cache(chat_id)
                logger.debug(f"消息已保存並使緩存失效: {chat_id}")
            return result
    except Exception as e:
        logger.error(f"保存消息失敗: {e}")
        return {"success": False, "error": str(e)}


async def _flush_message_buffer():
    """清空消息緩衝區並批量寫入"""
    try:
        result = await db_cache.flush_write_buffer("messages")
        if result.get("messages", 0) > 0:
            logger.info(f"✅ 批量寫入 {result['messages']} 條消息")
    except Exception as e:
        logger.error(f"❌ 批量寫入失敗: {e}")


# ==================== 記憶操作優化 ====================

async def get_user_memories(
    user_id: str, 
    memory_type: Optional[str] = None, 
    limit: int = 10, 
    min_importance: float = 0.0
) -> Dict[str, Any]:
    """
    優化版：獲取用戶記憶（帶緩存）
    
    優化策略：
    1. 先查緩存（只緩存常見查詢）
    2. 緩存未命中時查詢數據庫
    3. 結果寫入緩存
    """
    # 只對標準查詢使用緩存（避免緩存碎片化）
    use_cache = (limit == 10 and min_importance == 0.0)
    
    if use_cache:
        # 1. 檢查緩存
        cached_memories = await db_cache.get_memories_cached(user_id, memory_type)
        if cached_memories is not None:
            logger.debug(f"記憶緩存命中: {user_id}, type={memory_type}")
            return {"success": True, "memories": cached_memories}
    
    # 2. 查詢數據庫
    cache_key = f"fetch_memories:{user_id}:{memory_type}:{limit}:{min_importance}"
    
    async def fetch_memories():
        logger.debug(f"從數據庫獲取記憶: {user_id}")
        result = await _get_user_memories_original(user_id, memory_type, limit, min_importance)
        if use_cache and result.get("success") and result.get("memories"):
            # 寫入緩存
            await db_cache.set_memories_cache(user_id, result["memories"], memory_type)
        return result
    
    return await db_cache.coalesce_request(cache_key, fetch_memories)


# ==================== 批量操作優化 ====================

class BatchWriter:
    """批量寫入管理器"""
    
    def __init__(self):
        self.batch_queue: Dict[str, List[Dict[str, Any]]] = {
            "messages": [],
            "memories": [],
        }
        self.batch_size = 50
        self.lock = asyncio.Lock()
    
    async def add_message(self, user_id: str, content: str, is_bot: bool = False):
        """添加消息到批量寫入隊列"""
        async with self.lock:
            self.batch_queue["messages"].append({
                "user_id": user_id,
                "content": content,
                "is_bot": is_bot,
                "timestamp": datetime.now(),
            })
            
            # 達到批量大小時觸發寫入
            if len(self.batch_queue["messages"]) >= self.batch_size:
                await self._flush_messages()
    
    async def _flush_messages(self):
        """批量寫入消息"""
        if not self.batch_queue["messages"]:
            return
        
        messages = self.batch_queue["messages"]
        self.batch_queue["messages"] = []
        
        logger.info(f"批量寫入 {len(messages)} 條消息到 Firestore")
        
        try:
            # Firestore 批量寫入
            batch = firestore_db.batch()
            for msg in messages:
                doc_ref = messages_collection.document()
                batch.set(doc_ref, msg)
            
            # 執行批量寫入
            await asyncio.to_thread(batch.commit)
            logger.info(f"✅ 批量寫入成功: {len(messages)} 條消息")
        
        except Exception as e:
            logger.error(f"批量寫入失敗: {e}")
            # 失敗時重新加入隊列
            self.batch_queue["messages"].extend(messages)
    
    async def flush_all(self):
        """清空所有隊列"""
        async with self.lock:
            await self._flush_messages()


# 全局批量寫入器
batch_writer = BatchWriter()


# ==================== 查詢優化工具 ====================

class QueryOptimizer:
    """查詢優化工具"""
    
    def __init__(self):
        # 記錄查詢統計
        self.query_stats: Dict[str, Dict[str, int]] = {}
        self.lock = asyncio.Lock()
    
    async def record_query(self, query_type: str, from_cache: bool):
        """記錄查詢統計"""
        async with self.lock:
            if query_type not in self.query_stats:
                self.query_stats[query_type] = {"total": 0, "cached": 0, "db": 0}
            
            self.query_stats[query_type]["total"] += 1
            if from_cache:
                self.query_stats[query_type]["cached"] += 1
            else:
                self.query_stats[query_type]["db"] += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """獲取查詢統計"""
        stats = {}
        for query_type, counts in self.query_stats.items():
            total = counts["total"]
            cached = counts["cached"]
            cache_hit_rate = (cached / total * 100) if total > 0 else 0
            
            stats[query_type] = {
                "total": total,
                "from_cache": cached,
                "from_db": counts["db"],
                "cache_hit_rate": f"{cache_hit_rate:.2f}%"
            }
        
        return stats
    
    async def reset_stats(self):
        """重置統計"""
        async with self.lock:
            self.query_stats.clear()


# 全局查詢優化器
query_optimizer = QueryOptimizer()


# ==================== 導出接口 ====================

__all__ = [
    "get_user_by_id",
    "get_chat",
    "get_user_chats",
    "save_chat_message",
    "get_user_memories",
    "batch_writer",
    "query_optimizer",
]
