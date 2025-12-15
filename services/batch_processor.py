"""
OpenAI Batch API 處理器（2025 最佳實踐）
用於非即時任務，成本降低 50%

適用場景：
- 長期記憶摘要（每日凌晨批次處理）
- 健康數據分析報告
- 情緒分析週報
- 大量文字翻譯/摘要

參考：https://cookbook.openai.com/examples/batch_processing
"""

import os
import json
import time
import asyncio
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("batch_processor")

# OpenAI 客戶端
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Batch 檔案儲存目錄
BATCH_DIR = Path("/tmp/openai_batch")
BATCH_DIR.mkdir(exist_ok=True, parents=True)


class BatchProcessor:
    """
    OpenAI Batch API 處理器

    使用方式：
        processor = BatchProcessor()
        batch_id = await processor.create_memory_summary_batch(user_ids)
        result = await processor.wait_for_completion(batch_id)
    """

    def __init__(self):
        self.client = client

    def create_batch_request(
        self,
        custom_id: str,
        model: str,
        messages: List[Dict[str, str]],
        **kwargs
    ) -> Dict[str, Any]:
        """
        創建單個批次請求（JSONL 格式）

        Args:
            custom_id: 自訂 ID（用於識別結果）
            model: 模型名稱
            messages: 對話訊息
            **kwargs: 其他參數（如 max_tokens, temperature）

        Returns:
            JSONL 格式的請求物件
        """
        return {
            "custom_id": custom_id,
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {
                "model": model,
                "messages": messages,
                **kwargs
            }
        }

    async def create_batch_file(
        self,
        requests: List[Dict[str, Any]],
        filename: Optional[str] = None
    ) -> str:
        """
        創建批次檔案（JSONL 格式）

        Args:
            requests: 批次請求列表
            filename: 檔案名稱（可選）

        Returns:
            批次檔案路徑
        """
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"batch_{timestamp}.jsonl"

        file_path = BATCH_DIR / filename

        # 寫入 JSONL 格式
        with open(file_path, "w", encoding="utf-8") as f:
            for req in requests:
                f.write(json.dumps(req, ensure_ascii=False) + "\n")

        logger.info(f"✅ 批次檔案已創建: {file_path}（{len(requests)} 個請求）")
        return str(file_path)

    async def submit_batch(
        self,
        file_path: str,
        description: Optional[str] = None
    ) -> str:
        """
        提交批次任務到 OpenAI

        Args:
            file_path: 批次檔案路徑
            description: 批次描述（可選）

        Returns:
            batch_id
        """
        # 上傳檔案
        with open(file_path, "rb") as f:
            batch_file = self.client.files.create(
                file=f,
                purpose="batch"
            )

        logger.info(f"📤 檔案已上傳: {batch_file.id}")

        # 提交批次任務
        batch_job = self.client.batches.create(
            input_file_id=batch_file.id,
            endpoint="/v1/chat/completions",
            completion_window="24h",
            metadata={"description": description} if description else None
        )

        logger.info(f"🚀 批次任務已提交: {batch_job.id}")
        logger.info(f"📊 狀態: {batch_job.status}")

        return batch_job.id

    async def wait_for_completion(
        self,
        batch_id: str,
        poll_interval: int = 60,
        max_wait_time: int = 86400  # 24小時
    ) -> Dict[str, Any]:
        """
        等待批次任務完成（非阻塞）

        Args:
            batch_id: 批次 ID
            poll_interval: 輪詢間隔（秒），預設 60 秒
            max_wait_time: 最大等待時間（秒），預設 24 小時

        Returns:
            批次結果
        """
        start_time = time.time()

        while True:
            # 檢查是否超時
            if time.time() - start_time > max_wait_time:
                logger.error(f"❌ 批次任務 {batch_id} 超時（{max_wait_time}秒）")
                raise TimeoutError(f"Batch {batch_id} timeout after {max_wait_time}s")

            # 查詢批次狀態
            batch_job = self.client.batches.retrieve(batch_id)

            logger.info(f"📊 批次 {batch_id} 狀態: {batch_job.status}")

            if batch_job.status == "completed":
                logger.info(f"✅ 批次任務完成: {batch_id}")
                return await self._retrieve_results(batch_job)

            elif batch_job.status == "failed":
                logger.error(f"❌ 批次任務失敗: {batch_id}")
                return {
                    "success": False,
                    "error": "Batch job failed",
                    "batch_id": batch_id
                }

            elif batch_job.status == "cancelled":
                logger.warning(f"⚠️ 批次任務已取消: {batch_id}")
                return {
                    "success": False,
                    "error": "Batch job cancelled",
                    "batch_id": batch_id
                }

            # 等待下一次輪詢
            await asyncio.sleep(poll_interval)

    async def _retrieve_results(self, batch_job: Any) -> Dict[str, Any]:
        """
        提取批次結果

        Args:
            batch_job: 批次任務物件

        Returns:
            解析後的結果
        """
        # 下載結果檔案
        result_file_id = batch_job.output_file_id
        result_content = self.client.files.content(result_file_id)

        # 解析 JSONL 結果
        results = []
        for line in result_content.text.strip().split("\n"):
            if line:
                results.append(json.loads(line))

        logger.info(f"📥 批次結果已下載: {len(results)} 個回應")

        return {
            "success": True,
            "batch_id": batch_job.id,
            "total_requests": len(results),
            "results": results,
            "metadata": {
                "created_at": batch_job.created_at,
                "completed_at": batch_job.completed_at,
                "request_counts": batch_job.request_counts
            }
        }

    # ========== 具體應用場景 ==========

    async def create_memory_summary_batch(
        self,
        user_memories: Dict[str, List[str]],
        model: str = "gpt-5-nano"
    ) -> str:
        """
        創建記憶摘要批次任務

        Args:
            user_memories: {user_id: [memory_1, memory_2, ...]}
            model: 模型名稱

        Returns:
            batch_id
        """
        requests = []

        for user_id, memories in user_memories.items():
            # 組裝提示詞
            messages = [
                {
                    "role": "system",
                    "content": "你是記憶摘要助手，請將用戶的多條記憶整合為簡潔的摘要。"
                },
                {
                    "role": "user",
                    "content": f"請摘要以下記憶：\n" + "\n".join(f"- {m}" for m in memories)
                }
            ]

            # 創建請求
            req = self.create_batch_request(
                custom_id=user_id,
                model=model,
                messages=messages,
                max_tokens=500,
                reasoning_effort="medium"  # 批次任務可用較高推理強度
            )

            requests.append(req)

        # 創建批次檔案
        file_path = await self.create_batch_file(requests, filename="memory_summary.jsonl")

        # 提交批次
        batch_id = await self.submit_batch(file_path, description="每日記憶摘要")

        return batch_id

    async def create_health_report_batch(
        self,
        user_health_data: Dict[str, Dict[str, Any]],
        model: str = "gpt-5-nano"
    ) -> str:
        """
        創建健康報告批次任務

        Args:
            user_health_data: {user_id: {heart_rate: ..., steps: ...}}
            model: 模型名稱

        Returns:
            batch_id
        """
        requests = []

        for user_id, health_data in user_health_data.items():
            messages = [
                {
                    "role": "system",
                    "content": "你是健康分析助手，請根據用戶的健康數據生成週報。"
                },
                {
                    "role": "user",
                    "content": f"請分析以下健康數據並生成報告：\n{json.dumps(health_data, ensure_ascii=False, indent=2)}"
                }
            ]

            req = self.create_batch_request(
                custom_id=user_id,
                model=model,
                messages=messages,
                max_tokens=1000,
                reasoning_effort="medium"
            )

            requests.append(req)

        file_path = await self.create_batch_file(requests, filename="health_report.jsonl")
        batch_id = await self.submit_batch(file_path, description="健康週報")

        return batch_id


# 全域單例
batch_processor = BatchProcessor()


# ========== 便捷函數 ==========

async def submit_memory_summary_batch(user_memories: Dict[str, List[str]]) -> str:
    """
    便捷函數：提交記憶摘要批次任務

    範例：
        user_memories = {
            "user_123": ["今天去了公園", "吃了義大利麵", "心情不錯"],
            "user_456": ["工作很忙", "晚上健身"],
        }
        batch_id = await submit_memory_summary_batch(user_memories)
    """
    return await batch_processor.create_memory_summary_batch(user_memories)


async def get_batch_results(batch_id: str) -> Dict[str, Any]:
    """
    便捷函數：獲取批次結果（等待完成）

    範例：
        results = await get_batch_results(batch_id)
        if results["success"]:
            for item in results["results"]:
                logger.debug(item)
    """
    return await batch_processor.wait_for_completion(batch_id)
