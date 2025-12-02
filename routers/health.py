"""
健康數據相關 API 路由
包含 HealthKit 數據同步等
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from core.auth import require_auth

logger = logging.getLogger("routers.health")

router = APIRouter(prefix="/api/health", tags=["健康數據"])


class HealthDataPoint(BaseModel):
    """健康數據點"""
    type: str  # heart_rate, steps, sleep, etc.
    value: float
    unit: str
    timestamp: datetime
    source: Optional[str] = None


class HealthDataSyncRequest(BaseModel):
    """健康數據同步請求"""
    data: List[HealthDataPoint]


class HealthQueryRequest(BaseModel):
    """健康數據查詢請求"""
    types: List[str]
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


@router.post("/sync")
async def sync_health_data(
    request: HealthDataSyncRequest,
    user: dict = Depends(require_auth)
):
    """
    同步健康數據（從 HealthKit/Google Fit）
    """
    user_id = user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="無效的用戶")

    try:
        from core.database import firestore_db
        
        if not firestore_db:
            raise HTTPException(status_code=503, detail="數據庫不可用")

        # 批量寫入健康數據
        batch = firestore_db.batch()
        health_collection = firestore_db.collection("health_data")

        for data_point in request.data:
            doc_ref = health_collection.document()
            batch.set(doc_ref, {
                "user_id": user_id,
                "type": data_point.type,
                "value": data_point.value,
                "unit": data_point.unit,
                "timestamp": data_point.timestamp,
                "source": data_point.source,
                "synced_at": datetime.now(),
            })

        # 執行批量寫入
        import asyncio
        await asyncio.to_thread(batch.commit)

        logger.info(f"用戶 {user_id} 同步了 {len(request.data)} 條健康數據")

        return {
            "success": True,
            "synced_count": len(request.data),
        }

    except Exception as e:
        logger.exception(f"健康數據同步失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query")
async def query_health_data(
    request: HealthQueryRequest,
    user: dict = Depends(require_auth)
):
    """
    查詢健康數據
    """
    user_id = user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="無效的用戶")

    try:
        from core.database import firestore_db
        from google.cloud.firestore import FieldFilter
        
        if not firestore_db:
            raise HTTPException(status_code=503, detail="數據庫不可用")

        health_collection = firestore_db.collection("health_data")
        
        # 構建查詢
        query = health_collection.where(
            filter=FieldFilter("user_id", "==", user_id)
        )

        # 時間範圍過濾
        if request.start_date:
            query = query.where(
                filter=FieldFilter("timestamp", ">=", request.start_date)
            )
        if request.end_date:
            query = query.where(
                filter=FieldFilter("timestamp", "<=", request.end_date)
            )

        # 執行查詢
        import asyncio
        docs = await asyncio.to_thread(lambda: list(query.stream()))

        # 過濾類型並格式化結果
        results: Dict[str, List[Dict[str, Any]]] = {t: [] for t in request.types}
        
        for doc in docs:
            data = doc.to_dict()
            data_type = data.get("type")
            if data_type in request.types:
                results[data_type].append({
                    "value": data.get("value"),
                    "unit": data.get("unit"),
                    "timestamp": data.get("timestamp"),
                    "source": data.get("source"),
                })

        return {
            "success": True,
            "data": results,
        }

    except Exception as e:
        logger.exception(f"健康數據查詢失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary")
async def get_health_summary(user: dict = Depends(require_auth)):
    """
    獲取健康數據摘要（今日）
    """
    user_id = user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="無效的用戶")

    try:
        from core.database import firestore_db
        from google.cloud.firestore import FieldFilter
        
        if not firestore_db:
            raise HTTPException(status_code=503, detail="數據庫不可用")

        # 今日開始時間
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        health_collection = firestore_db.collection("health_data")
        
        query = health_collection.where(
            filter=FieldFilter("user_id", "==", user_id)
        ).where(
            filter=FieldFilter("timestamp", ">=", today_start)
        )

        import asyncio
        docs = await asyncio.to_thread(lambda: list(query.stream()))

        # 計算摘要
        summary = {
            "steps": 0,
            "heart_rate_avg": 0,
            "heart_rate_readings": [],
            "sleep_hours": 0,
            "active_calories": 0,
        }

        for doc in docs:
            data = doc.to_dict()
            data_type = data.get("type")
            value = data.get("value", 0)

            if data_type == "steps":
                summary["steps"] += value
            elif data_type == "heart_rate":
                summary["heart_rate_readings"].append(value)
            elif data_type == "sleep":
                summary["sleep_hours"] += value
            elif data_type == "active_calories":
                summary["active_calories"] += value

        # 計算心率平均值
        if summary["heart_rate_readings"]:
            summary["heart_rate_avg"] = sum(summary["heart_rate_readings"]) / len(summary["heart_rate_readings"])
        del summary["heart_rate_readings"]

        return {
            "success": True,
            "date": today_start.date().isoformat(),
            "summary": summary,
        }

    except Exception as e:
        logger.exception(f"健康摘要獲取失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))
