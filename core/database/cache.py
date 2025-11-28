"""
數據庫緩存層 - 減少 Firestore 調用頻率
實現多級緩存策略，大幅降低數據庫讀取次數
"""

import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
from collections import OrderedDict
import hashlib
import json

logger = logging.getLogger("DatabaseCache")


class LRUCache:
    """LRU (Least Recently Used) 緩存實現"""
    
    def __init__(self, max_size: int = 1000, ttl_seconds: int = 300):
        """
        初始化 LRU 緩存
        
        Args:
            max_size: 最大緩存條目數
            ttl_seconds: 緩存過期時間（秒）
        """
        self.cache: OrderedDict = OrderedDict()
        self.max_size = max_size
        self.ttl = timedelta(seconds=ttl_seconds)
        self.hits = 0
        self.misses = 0
        self._lock = asyncio.Lock()
    
    async def get(self, key: str) -> Optional[Any]:
        """獲取緩存值"""
        async with self._lock:
            if key not in self.cache:
                self.misses += 1
                return None
            
            value, expire_time = self.cache[key]
            
            # 檢查是否過期
            if datetime.now() > expire_time:
                del self.cache[key]
                self.misses += 1
                return None
            
            # 移到最後（表示最近使用）
            self.cache.move_to_end(key)
            self.hits += 1
            return value
    
    async def set(self, key: str, value: Any):
        """設置緩存值"""
        async with self._lock:
            expire_time = datetime.now() + self.ttl
            
            if key in self.cache:
                # 更新現有值
                self.cache[key] = (value, expire_time)
                self.cache.move_to_end(key)
            else:
                # 新增值
                self.cache[key] = (value, expire_time)
                
                # 如果超過最大容量，移除最舊的
                if len(self.cache) > self.max_size:
                    oldest_key = next(iter(self.cache))
                    del self.cache[oldest_key]
                    logger.debug(f"LRU 緩存已滿，移除最舊條目: {oldest_key}")
    
    async def delete(self, key: str):
        """刪除緩存值"""
        async with self._lock:
            if key in self.cache:
                del self.cache[key]
    
    async def clear(self):
        """清空緩存"""
        async with self._lock:
            self.cache.clear()
            self.hits = 0
            self.misses = 0
    
    def get_stats(self) -> Dict[str, Any]:
        """獲取緩存統計"""
        total = self.hits + self.misses
        hit_rate = (self.hits / total * 100) if total > 0 else 0
        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": f"{hit_rate:.2f}%"
        }


class DatabaseCache:
    """數據庫緩存管理器"""
    
    def __init__(self):
        # 不同數據類型使用不同的緩存策略
        self.user_cache = LRUCache(max_size=500, ttl_seconds=600)  # 用戶資料：10分鐘
        self.chat_cache = LRUCache(max_size=300, ttl_seconds=300)   # 對話資料：5分鐘
        self.message_cache = LRUCache(max_size=1000, ttl_seconds=180)  # 消息歷史：3分鐘
        self.memory_cache = LRUCache(max_size=200, ttl_seconds=900)  # 記憶：15分鐘
        
        # 寫入緩衝區（批量寫入優化）
        self.write_buffer: Dict[str, List[Dict[str, Any]]] = {
            "messages": [],
            "memories": [],
            "chats": []
        }
        self.write_buffer_lock = asyncio.Lock()
        self.write_buffer_max_size = 50  # 達到50條時觸發批量寫入
        self.write_buffer_timeout = 10  # 10秒後強制寫入
        
        # 請求合併（同一查詢只執行一次）
        self.pending_requests: Dict[str, asyncio.Future] = {}
        self.pending_lock = asyncio.Lock()

        # 其他快取：環境、反地理、路徑
        self.env_ctx_cache = LRUCache(max_size=1000, ttl_seconds=600)     # 使用者環境快取：10 分鐘
        self.geo_cache = LRUCache(max_size=5000, ttl_seconds=604800)      # 反地理快取：7 天
        self.route_cache = LRUCache(max_size=5000, ttl_seconds=86400)     # 路線快取：1 天

        logger.info("數據庫緩存管理器初始化完成")
    
    def _generate_cache_key(self, operation: str, **kwargs) -> str:
        """生成緩存鍵"""
        # 將參數排序後生成哈希，確保相同參數生成相同鍵
        params_str = json.dumps(kwargs, sort_keys=True, default=str)
        key_hash = hashlib.md5(f"{operation}:{params_str}".encode()).hexdigest()
        return f"{operation}:{key_hash}"
    
    async def get_user_cached(self, user_id: str) -> Optional[Dict[str, Any]]:
        """獲取緩存的用戶資料"""
        cache_key = self._generate_cache_key("user", user_id=user_id)
        return await self.user_cache.get(cache_key)
    
    async def set_user_cache(self, user_id: str, user_data: Dict[str, Any]):
        """設置用戶緩存"""
        cache_key = self._generate_cache_key("user", user_id=user_id)
        await self.user_cache.set(cache_key, user_data)
    
    async def get_chat_cached(self, chat_id: str) -> Optional[Dict[str, Any]]:
        """獲取緩存的對話資料"""
        cache_key = self._generate_cache_key("chat", chat_id=chat_id)
        return await self.chat_cache.get(cache_key)
    
    async def set_chat_cache(self, chat_id: str, chat_data: Dict[str, Any]):
        """設置對話緩存"""
        cache_key = self._generate_cache_key("chat", chat_id=chat_id)
        await self.chat_cache.set(cache_key, chat_data)
    
    async def invalidate_chat_cache(self, chat_id: str):
        """使對話緩存失效（當對話更新時調用）"""
        cache_key = self._generate_cache_key("chat", chat_id=chat_id)
        await self.chat_cache.delete(cache_key)
    
    async def get_user_chats_cached(self, user_id: str) -> Optional[List[Dict[str, Any]]]:
        """獲取緩存的用戶對話列表"""
        cache_key = self._generate_cache_key("user_chats", user_id=user_id)
        return await self.chat_cache.get(cache_key)
    
    async def set_user_chats_cache(self, user_id: str, chats: List[Dict[str, Any]]):
        """設置用戶對話列表緩存"""
        cache_key = self._generate_cache_key("user_chats", user_id=user_id)
        await self.chat_cache.set(cache_key, chats)
    
    async def invalidate_user_chats_cache(self, user_id: str):
        """使用戶對話列表緩存失效"""
        cache_key = self._generate_cache_key("user_chats", user_id=user_id)
        await self.chat_cache.delete(cache_key)
    
    async def get_memories_cached(self, user_id: str, memory_type: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
        """獲取緩存的記憶"""
        cache_key = self._generate_cache_key("memories", user_id=user_id, memory_type=memory_type)
        return await self.memory_cache.get(cache_key)
    
    async def set_memories_cache(self, user_id: str, memories: List[Dict[str, Any]], memory_type: Optional[str] = None):
        """設置記憶緩存"""
        cache_key = self._generate_cache_key("memories", user_id=user_id, memory_type=memory_type)
        await self.memory_cache.set(cache_key, memories)
    
    async def coalesce_request(self, cache_key: str, fetch_func):
        """
        請求合併：如果同一個請求正在執行，等待其結果而不是重複執行
        
        Args:
            cache_key: 請求的唯一標識
            fetch_func: 實際的數據獲取函數（async）
        
        Returns:
            查詢結果
        """
        async with self.pending_lock:
            # 檢查是否有相同請求正在執行
            if cache_key in self.pending_requests:
                logger.debug(f"請求合併：等待現有請求 {cache_key}")
                # 等待現有請求完成
                future = self.pending_requests[cache_key]
            else:
                # 創建新的請求
                future = asyncio.create_task(fetch_func())
                self.pending_requests[cache_key] = future
        
        try:
            # 等待結果
            result = await future
            return result
        finally:
            # 清理已完成的請求
            async with self.pending_lock:
                if cache_key in self.pending_requests:
                    del self.pending_requests[cache_key]
    
    async def buffer_write(self, collection: str, data: Dict[str, Any]) -> bool:
        """
        緩衝寫入：先存入緩衝區，達到一定數量或時間後批量寫入
        
        Args:
            collection: 集合名稱 (messages/memories/chats)
            data: 要寫入的數據
        
        Returns:
            True 如果已觸發批量寫入
        """
        async with self.write_buffer_lock:
            if collection not in self.write_buffer:
                self.write_buffer[collection] = []
            
            # 添加時間戳
            data["_buffered_at"] = datetime.now()
            self.write_buffer[collection].append(data)
            
            # 檢查是否需要立即寫入
            if len(self.write_buffer[collection]) >= self.write_buffer_max_size:
                logger.info(f"寫入緩衝區已滿 ({collection})，觸發批量寫入")
                return True
            
            return False
    
    async def flush_write_buffer(self, collection: Optional[str] = None) -> Dict[str, int]:
        """
        清空寫入緩衝區，執行批量寫入
        
        Args:
            collection: 指定集合名稱，None 表示清空所有
        
        Returns:
            每個集合的寫入數量
        """
        async with self.write_buffer_lock:
            collections_to_flush = [collection] if collection else list(self.write_buffer.keys())
            result = {}
            
            for coll in collections_to_flush:
                if coll not in self.write_buffer or not self.write_buffer[coll]:
                    result[coll] = 0
                    continue
                
                items = self.write_buffer[coll]
                self.write_buffer[coll] = []
                result[coll] = len(items)
                
                logger.info(f"批量寫入 {coll}: {len(items)} 條記錄")
                
                # 這裡需要實際的批量寫入邏輯
                # 將在 database.py 中實現
            
            return result
    
    async def get_buffer_size(self) -> Dict[str, int]:
        """獲取各緩衝區的大小"""
        async with self.write_buffer_lock:
            return {k: len(v) for k, v in self.write_buffer.items()}
    
    def get_all_stats(self) -> Dict[str, Any]:
        """獲取所有緩存統計"""
        return {
            "user_cache": self.user_cache.get_stats(),
            "chat_cache": self.chat_cache.get_stats(),
            "message_cache": self.message_cache.get_stats(),
            "memory_cache": self.memory_cache.get_stats(),
            "env_ctx_cache": self.env_ctx_cache.get_stats(),
            "geo_cache": self.geo_cache.get_stats(),
            "route_cache": self.route_cache.get_stats(),
            "write_buffer": {k: len(v) for k, v in self.write_buffer.items()}
        }
    
    async def clear_all(self):
        """清空所有緩存"""
        await self.user_cache.clear()
        await self.chat_cache.clear()
        await self.message_cache.clear()
        await self.memory_cache.clear()
        logger.info("所有緩存已清空")

    # ===== 環境/地理/路線 快取 API =====
    async def get_env_ctx_cached(self, user_id: str) -> Optional[Dict[str, Any]]:
        key = self._generate_cache_key("env_ctx", user_id=user_id)
        return await self.env_ctx_cache.get(key)

    async def set_env_ctx_cache(self, user_id: str, ctx: Dict[str, Any]):
        key = self._generate_cache_key("env_ctx", user_id=user_id)
        await self.env_ctx_cache.set(key, ctx)

    async def get_geo_cached(self, geohash7: str) -> Optional[Dict[str, Any]]:
        key = self._generate_cache_key("geo", geohash=geohash7)
        return await self.geo_cache.get(key)

    async def set_geo_cache(self, geohash7: str, payload: Dict[str, Any]):
        key = self._generate_cache_key("geo", geohash=geohash7)
        await self.geo_cache.set(key, payload)

    async def get_route_cached(self, cache_key: str) -> Optional[Dict[str, Any]]:
        key = self._generate_cache_key("route", key=cache_key)
        return await self.route_cache.get(key)

    async def set_route_cache(self, cache_key: str, payload: Dict[str, Any]):
        key = self._generate_cache_key("route", key=cache_key)
        await self.route_cache.set(key, payload)

    async def get_tdx_cached(self, cache_key: str) -> Optional[Any]:
        """獲取 TDX API 快取資料"""
        return await self.route_cache.get(cache_key)

    async def set_tdx_cache(self, cache_key: str, data: Any, ttl: int = 60):
        """設置 TDX API 快取資料（使用 route_cache，因為 TDX 也是路線相關）"""
        await self.route_cache.set(cache_key, data)


# 全局緩存實例
db_cache = DatabaseCache()


async def periodic_cache_maintenance():
    """定期緩存維護任務"""
    while True:
        try:
            await asyncio.sleep(300)  # 每5分鐘執行一次
            
            # 輸出緩存統計
            stats = db_cache.get_all_stats()
            logger.info(f"緩存統計: {stats}")
            
            # 檢查寫入緩衝區
            buffer_size = await db_cache.get_buffer_size()
            if any(size > 0 for size in buffer_size.values()):
                logger.info(f"清空寫入緩衝區: {buffer_size}")
                await db_cache.flush_write_buffer()
        
        except Exception as e:
            logger.error(f"緩存維護任務出錯: {e}")
