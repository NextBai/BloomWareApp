"""
批次任務排程器（每日凌晨執行）
使用 Batch API 處理非即時任務，成本降低 50%

定時任務：
- 每日凌晨 3:00 執行記憶摘要
- 每週一凌晨 4:00 執行健康週報
"""

import asyncio
import logging
from datetime import datetime, time as dt_time, timedelta
from typing import Dict, List, Any
from services.batch_processor import batch_processor
from core.database import firestore_db

logger = logging.getLogger("batch_scheduler")


class BatchScheduler:
    """批次任務排程器"""

    def __init__(self):
        self.running = False
        self._tasks: List[asyncio.Task] = []

    async def start(self):
        """啟動排程器"""
        if self.running:
            logger.warning("⚠️ 排程器已在運行中")
            return

        self.running = True
        logger.info("🕐 批次任務排程器已啟動")

        # 啟動定時任務
        self._tasks.append(asyncio.create_task(self._daily_memory_summary()))
        self._tasks.append(asyncio.create_task(self._weekly_health_report()))

    async def stop(self):
        """停止排程器"""
        self.running = False

        for task in self._tasks:
            task.cancel()

        logger.info("🛑 批次任務排程器已停止")

    async def _daily_memory_summary(self):
        """
        每日記憶摘要任務（凌晨 3:00 執行）

        流程：
        1. 從數據庫獲取所有用戶的昨日記憶
        2. 創建批次任務
        3. 等待批次完成（最多 24 小時）
        4. 儲存摘要結果到數據庫
        """
        while self.running:
            try:
                # 計算下次執行時間（凌晨 3:00）
                now = datetime.now()
                target_time = dt_time(3, 0, 0)

                # 等待到凌晨 3:00
                await self._wait_until(target_time)

                if not self.running:
                    break

                logger.info("📚 開始執行每日記憶摘要任務...")

                # 1. 從數據庫獲取所有用戶的昨日記憶
                user_memories = await self._fetch_yesterday_memories()

                if not user_memories:
                    logger.info("📭 沒有需要摘要的記憶，跳過")
                    continue

                logger.info(f"📊 找到 {len(user_memories)} 位用戶的記憶需要摘要")

                # 2. 創建批次任務
                batch_id = await batch_processor.create_memory_summary_batch(user_memories)

                logger.info(f"🚀 批次任務已提交: {batch_id}")
                logger.info("⏳ 等待批次完成（最多 24 小時）...")

                # 3. 等待批次完成
                results = await batch_processor.wait_for_completion(batch_id)

                if results["success"]:
                    logger.info(f"✅ 批次任務完成，收到 {results['total_requests']} 個摘要")

                    # 4. 儲存摘要結果
                    await self._save_memory_summaries(results["results"])

                    logger.info("💾 記憶摘要已儲存到數據庫")
                else:
                    logger.error(f"❌ 批次任務失敗: {results.get('error')}")

            except Exception as e:
                logger.exception(f"❌ 每日記憶摘要任務發生錯誤: {e}")
                # 等待 1 小時後重試
                await asyncio.sleep(3600)

    async def _weekly_health_report(self):
        """
        每週健康報告任務（每週一凌晨 4:00 執行）

        流程：
        1. 從數據庫獲取所有用戶的本週健康數據
        2. 創建批次任務
        3. 等待批次完成
        4. 發送報告給用戶（通知）
        """
        while self.running:
            try:
                # 等待到週一凌晨 4:00
                now = datetime.now()
                target_time = dt_time(4, 0, 0)

                await self._wait_until(target_time)

                # 檢查是否為週一
                if now.weekday() != 0:  # 0 = 週一
                    await asyncio.sleep(3600)  # 不是週一，等 1 小時後再檢查
                    continue

                if not self.running:
                    break

                logger.info("❤️ 開始執行每週健康報告任務...")

                # 1. 獲取用戶健康數據
                user_health_data = await self._fetch_week_health_data()

                if not user_health_data:
                    logger.info("📭 沒有健康數據，跳過")
                    continue

                logger.info(f"📊 找到 {len(user_health_data)} 位用戶的健康數據")

                # 2. 創建批次任務
                batch_id = await batch_processor.create_health_report_batch(user_health_data)

                logger.info(f"🚀 批次任務已提交: {batch_id}")

                # 3. 等待批次完成
                results = await batch_processor.wait_for_completion(batch_id)

                if results["success"]:
                    logger.info(f"✅ 批次任務完成，收到 {results['total_requests']} 個報告")

                    # 4. TODO: 發送報告通知給用戶
                    # await self._send_health_reports(results["results"])

                    logger.info("📧 健康報告已準備就緒")
                else:
                    logger.error(f"❌ 批次任務失敗: {results.get('error')}")

            except Exception as e:
                logger.exception(f"❌ 每週健康報告任務發生錯誤: {e}")
                await asyncio.sleep(3600)

    async def _wait_until(self, target_time: dt_time):
        """等待到指定時間"""
        now = datetime.now()
        target = datetime.combine(now.date(), target_time)

        # 如果目標時間已過，設定為明天
        if target <= now:
            target += timedelta(days=1)

        wait_seconds = (target - now).total_seconds()
        logger.debug(f"⏰ 等待 {wait_seconds:.0f} 秒後執行（目標時間: {target}）")

        await asyncio.sleep(wait_seconds)

    async def _fetch_yesterday_memories(self) -> Dict[str, List[str]]:
        """
        從數據庫獲取所有用戶的昨日記憶

        Returns:
            {user_id: [memory_1, memory_2, ...]}
        """
        try:
            if not firestore_db:
                logger.warning("⚠️ Firestore 未連接，無法獲取記憶")
                return {}

            from google.cloud.firestore import FieldFilter
            import asyncio

            # 計算昨日時間範圍
            yesterday_start = (datetime.now() - timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            yesterday_end = yesterday_start + timedelta(days=1)

            # 獲取所有用戶
            users_collection = firestore_db.collection("users")
            
            def _fetch_users():
                return list(users_collection.stream())

            users = await asyncio.to_thread(_fetch_users)
            
            result: Dict[str, List[str]] = {}

            for user_doc in users:
                user_id = user_doc.id
                
                # 獲取該用戶的昨日記憶
                def _fetch_user_memories(uid: str):
                    memories_ref = firestore_db.collection("users").document(uid).collection("memories")
                    query = memories_ref.where(
                        filter=FieldFilter("created_at", ">=", yesterday_start)
                    ).where(
                        filter=FieldFilter("created_at", "<", yesterday_end)
                    )
                    return list(query.stream())

                memories = await asyncio.to_thread(_fetch_user_memories, user_id)
                
                if memories:
                    memory_contents = []
                    for mem_doc in memories:
                        mem_data = mem_doc.to_dict()
                        content = mem_data.get("content", "")
                        if content:
                            memory_contents.append(content)
                    
                    if memory_contents:
                        result[user_id] = memory_contents

            logger.info(f"📚 獲取到 {len(result)} 位用戶的昨日記憶")
            return result

        except Exception as e:
            logger.exception(f"❌ 獲取昨日記憶失敗: {e}")
            return {}

    async def _save_memory_summaries(self, results: List[Dict[str, Any]]):
        """
        儲存記憶摘要到數據庫

        Args:
            results: 批次結果列表
        """
        if not firestore_db:
            logger.warning("⚠️ Firestore 未連接，無法儲存摘要")
            return

        import asyncio
        
        logger.info(f"💾 準備儲存 {len(results)} 條記憶摘要")
        
        saved_count = 0
        for result in results:
            try:
                custom_id = result.get("custom_id")  # user_id
                response = result.get("response", {}).get("body", {})
                summary = response.get("choices", [{}])[0].get("message", {}).get("content", "")

                if not custom_id or not summary:
                    continue

                logger.debug(f"📝 用戶 {custom_id} 的摘要: {summary[:50]}...")

                # 儲存到用戶的記憶摘要集合
                def _save_summary(uid: str, summary_text: str):
                    summaries_ref = firestore_db.collection("users").document(uid).collection("memory_summaries")
                    summaries_ref.add({
                        "summary": summary_text,
                        "date": datetime.now().date().isoformat(),
                        "created_at": datetime.now(),
                        "type": "daily",
                    })

                await asyncio.to_thread(_save_summary, custom_id, summary)
                saved_count += 1

            except Exception as e:
                logger.error(f"❌ 儲存用戶 {custom_id} 的摘要失敗: {e}")

        logger.info(f"✅ 成功儲存 {saved_count}/{len(results)} 條記憶摘要")

    async def _fetch_week_health_data(self) -> Dict[str, Dict[str, Any]]:
        """
        從數據庫獲取所有用戶的本週健康數據

        Returns:
            {user_id: {heart_rate: [...], steps: [...], sleep: [...], ...}}
        """
        try:
            if not firestore_db:
                logger.warning("⚠️ Firestore 未連接，無法獲取健康數據")
                return {}

            from google.cloud.firestore import FieldFilter
            import asyncio

            # 計算本週時間範圍（週一到今天）
            today = datetime.now()
            week_start = today - timedelta(days=today.weekday())
            week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)

            # 獲取所有用戶
            users_collection = firestore_db.collection("users")
            
            def _fetch_users():
                return list(users_collection.stream())

            users = await asyncio.to_thread(_fetch_users)
            
            result: Dict[str, Dict[str, Any]] = {}

            for user_doc in users:
                user_id = user_doc.id
                
                # 獲取該用戶的本週健康數據
                def _fetch_user_health(uid: str):
                    health_ref = firestore_db.collection("health_data")
                    query = health_ref.where(
                        filter=FieldFilter("user_id", "==", uid)
                    ).where(
                        filter=FieldFilter("timestamp", ">=", week_start)
                    )
                    return list(query.stream())

                health_docs = await asyncio.to_thread(_fetch_user_health, user_id)
                
                if health_docs:
                    user_health: Dict[str, List[Any]] = {
                        "heart_rate": [],
                        "steps": [],
                        "sleep": [],
                        "active_calories": [],
                    }
                    
                    for doc in health_docs:
                        data = doc.to_dict()
                        data_type = data.get("type")
                        value = data.get("value")
                        timestamp = data.get("timestamp")
                        
                        if data_type in user_health and value is not None:
                            user_health[data_type].append({
                                "value": value,
                                "timestamp": timestamp,
                            })
                    
                    # 只保留有數據的用戶
                    if any(user_health.values()):
                        result[user_id] = user_health

            logger.info(f"❤️ 獲取到 {len(result)} 位用戶的本週健康數據")
            return result

        except Exception as e:
            logger.exception(f"❌ 獲取本週健康數據失敗: {e}")
            return {}


# 全域單例
batch_scheduler = BatchScheduler()
