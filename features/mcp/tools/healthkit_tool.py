"""
HealthKit 工具 - 從數據庫查詢健康數據
提供雲端同步的健康數據查詢功能
"""

import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from .base_tool import MCPTool, ValidationError, ExecutionError
from google.cloud import firestore
from google.cloud.firestore_v1 import FieldFilter

logger = logging.getLogger("mcp.tools.healthkit")
logger.setLevel(logging.DEBUG)  # 強制設置為 DEBUG 級別


class HealthKitTool(MCPTool):
    """HealthKit 健康數據查詢工具 - 從數據庫讀取"""
    
    NAME = "healthkit_query"
    DESCRIPTION = "查詢用戶的健康數據，包括心率、步數、血氧、呼吸頻率等（數據由iOS設備自動同步到Firestore）"
    CATEGORY = "健康數據"
    TAGS = ["health", "fitness", "database", "firestore"]
    KEYWORDS = ["健康", "心率", "步數", "血氧", "睡眠", "health", "運動", "卡路里", "呼吸"]
    USAGE_TIPS = [
        "可查詢心率、步數、血氧、呼吸頻率、睡眠等",
        "支援指定查詢天數（1-365天）",
        "數據由 iOS 設備自動同步"
    ]
    
    def __init__(self):
        super().__init__()
        self.name = self.NAME
        self.description = self.DESCRIPTION
        self.category = self.CATEGORY
        self.tags = self.TAGS
    
    @classmethod
    def get_input_schema(cls) -> Dict[str, Any]:
        """獲取輸入參數模式"""
        return {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "string",
                    "description": "用戶 ID（可選，不提供時使用當前用戶）"
                },
                "metric_type": {
                    "type": "string",
                    "description": "要查詢的健康指標類型",
                    "enum": ["all", "heart_rate", "step_count", "oxygen_level", "respiratory_rate", "sleep_analysis"],
                    "default": "all"
                },
                "days": {
                    "type": "integer",
                    "description": "查詢過去多少天的數據",
                    "default": 7,
                    "minimum": 1,
                    "maximum": 365
                },
                "latest_only": {
                    "type": "boolean",
                    "description": "是否只返回最新的一筆數據",
                    "default": False
                },
                "aggregation": {
                    "type": "string",
                    "description": "數據聚合方式",
                    "enum": ["none", "daily", "weekly"],
                    "default": "none"
                }
            },
            "required": []
        }
    
    @classmethod
    def get_output_schema(cls) -> Dict[str, Any]:
        """獲取輸出結果模式"""
        return {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "data": {"type": "array"},
                "count": {"type": "integer"},
                "message": {"type": "string"},
                "metadata": {"type": "object"}
            }
        }
    
    @classmethod
    async def execute(cls, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """從數據庫查詢健康數據"""
        logger.info("🔍 收到 HealthKit 查詢請求: %s", json.dumps(arguments, ensure_ascii=False))

        try:
            # 從模組取得 firestore_db 實例（應用啟動時已確保連接）
            import core.database.base as db_module

            db = db_module.firestore_db

            # 安全檢查（理論上不應該發生）
            if not db:
                logger.error("❌ Firestore 未連接（這不應該發生，請檢查應用啟動日誌）")
                return cls.create_error_response(
                    error="Firestore數據庫未連接，請重啟應用或聯繫管理員",
                    code="DB_NOT_CONNECTED"
                )

            logger.debug("✅ 使用 Firestore 數據庫連接")

            # 解析參數（_user_id 由 coordinator 注入）
            user_id = arguments.get('_user_id')
            metric_type = arguments.get('metric_type', 'all')
            days = arguments.get('days', 7)
            latest_only = arguments.get('latest_only', False)
            aggregation = arguments.get('aggregation', 'none')

            # 如果沒有提供 user_id，返回錯誤
            if not user_id:
                return cls.create_error_response(
                    error="需要提供用戶 ID",
                    code="USER_ID_REQUIRED"
                )

            # Firestore 查詢 - 統一使用 health_data 集合
            # iOS APP 寫入路徑: health_data/{doc_id} (包含 user_id 字段)
            health_collection = db.collection('health_data')
            query = health_collection.where(
                filter=FieldFilter("user_id", "==", user_id)
            )
            logger.debug("📌 查詢 user_id 條件: %s", user_id)

            # 添加時間範圍過濾
            start_date = datetime.utcnow() - timedelta(days=days)
            query = query.where(
                filter=FieldFilter("timestamp", ">=", start_date)
            )
            logger.debug("📆 查詢時間範圍: %s 之後", start_date.isoformat())

            # 添加 metric_type 過濾 - 修正字段名稱
            if metric_type != 'all':
                query = query.where(
                    filter=FieldFilter("type", "==", metric_type)  # iOS寫入時使用"type"字段
                )
                logger.debug("🎯 指標過濾: %s", metric_type)
            else:
                logger.debug("🎯 指標過濾: 全部")
            
            # 排序和限制
            query = query.order_by("timestamp", direction=firestore.Query.DESCENDING)
            if latest_only:
                query = query.limit(1)
                logger.debug("⏱ 只取最新一筆資料")
            logger.debug("📥 即將執行 Firestore 查詢 (latest_only=%s)", latest_only)
            # 執行查詢
            docs = query.get()
            logger.info("📊 查詢完成，共取得 %d 筆原始文件", len(docs))
            
            # 收集數據
            data = []
            for doc in docs:
                doc_data = doc.to_dict()
                data_point = {
                    "metric": doc_data["type"],  # 修正字段名稱
                    "value": doc_data["value"],
                    "unit": doc_data["unit"],
                    "timestamp": doc_data["timestamp"].isoformat() if hasattr(doc_data["timestamp"], 'isoformat') else str(doc_data["timestamp"]),
                    "source": doc_data.get("source", "iOS HealthKit"),
                    "device_id": doc_data.get("device_id")
                }
                data.append(data_point)
            
            # 數據聚合（如果需要）
            if aggregation != 'none' and data:
                data = cls._aggregate_data(data, aggregation)
                logger.debug("🧮 聚合模式: %s，聚合後筆數: %d", aggregation, len(data))
            else:
                logger.debug("🧮 未進行額外聚合")
            
            # 生成摘要
            summary = cls._generate_summary(data, metric_type)
            logger.info("✅ 成功產生摘要。筆數: %d, metric_type: %s", len(data), metric_type)
            
            # 獲取設備資訊（可選）- 從健康數據中推斷
            device_info = None
            try:
                if data:
                    # 從最新的健康數據中獲取設備信息
                    latest_record = data[0]  # 數據已按時間降序排列
                    device_id = latest_record.get("device_id")
                    if device_id:
                        device_info = {
                            "device_id": device_id,
                            "last_sync": latest_record.get("timestamp")
                        }
            except Exception:
                pass  # 設備資訊是可選的
            
            # 限制返回給前端的數據量（避免傳輸過多數據）
            # 前端工具卡片只顯示最新的 20 筆，但 count 顯示總數
            display_limit = 20
            display_data = data[:display_limit] if len(data) > display_limit else data
            
            return cls.create_success_response(
                content=summary,
                data={
                    "raw_data": {
                        "health_data": display_data,
                        "count": len(data),
                        "total_records": len(data),
                        "displayed_records": len(display_data),
                        "query": {
                            "metric_type": metric_type,
                            "days": days,
                            "latest_only": latest_only,
                            "aggregation": aggregation
                        },
                        "device_info": device_info
                    }
                }
            )
            
        except Exception as e:
            logger.exception("❌ 查詢健康數據時發生錯誤")
            raise ExecutionError(f"查詢健康數據失敗: {str(e)}", e)
    
    @classmethod
    def _aggregate_data(cls, data: List[Dict], aggregation: str) -> List[Dict]:
        """聚合健康數據"""
        if aggregation == 'daily':
            # 按日期分組並計算平均值
            from collections import defaultdict
            daily_data = defaultdict(list)
            
            for point in data:
                date = datetime.fromisoformat(point["timestamp"]).date()
                daily_data[date].append(point)
            
            aggregated = []
            for date, points in daily_data.items():
                # 按指標類型分組
                metrics = defaultdict(list)
                for p in points:
                    metrics[p["metric"]].append(p["value"])
                
                for metric, values in metrics.items():
                    if values:  # 確保有數據
                        avg_value = sum(values) / len(values)
                        aggregated.append({
                            "metric": metric,
                            "value": round(avg_value, 2),
                            "unit": points[0]["unit"],
                            "timestamp": date.isoformat(),
                            "aggregation": "daily_average",
                            "data_points": len(values)
                        })
            
            return sorted(aggregated, key=lambda x: x["timestamp"], reverse=True)
        
        elif aggregation == 'weekly':
            # 週平均（簡化實現）
            from collections import defaultdict
            import calendar
            
            weekly_data = defaultdict(list)
            
            for point in data:
                date = datetime.fromisoformat(point["timestamp"]).date()
                # 獲取週數
                year, week, _ = date.isocalendar()
                week_key = f"{year}-W{week:02d}"
                weekly_data[week_key].append(point)
            
            aggregated = []
            for week_key, points in weekly_data.items():
                metrics = defaultdict(list)
                for p in points:
                    metrics[p["metric"]].append(p["value"])
                
                for metric, values in metrics.items():
                    if values:
                        avg_value = sum(values) / len(values)
                        aggregated.append({
                            "metric": metric,
                            "value": round(avg_value, 2),
                            "unit": points[0]["unit"],
                            "timestamp": week_key,
                            "aggregation": "weekly_average",
                            "data_points": len(values)
                        })
            
            return sorted(aggregated, key=lambda x: x["timestamp"], reverse=True)
        
        return data
    
    @classmethod
    def _generate_summary(cls, data: List[Dict], metric_type: str) -> str:
        """生成數據摘要"""
        if not data:
            if metric_type == 'all':
                return "沒有找到任何健康數據。請確認 iOS 設備已登入相同 Google 帳號並自動同步數據到 Firestore"
            else:
                metric_names = {
                    "heart_rate": "心率",
                    "step_count": "步數", 
                    "oxygen_level": "血氧",
                    "respiratory_rate": "呼吸頻率",
                    "sleep_analysis": "睡眠"
                }
                name = metric_names.get(metric_type, metric_type)
                return f"沒有找到 {name} 數據。請確認 iOS 設備已登入相同 Google 帳號並自動同步數據"
        
        metric_names = {
            "heart_rate": "心率",
            "step_count": "步數",
            "oxygen_level": "血氧", 
            "respiratory_rate": "呼吸頻率",
            "sleep_analysis": "睡眠"
        }
        
        if metric_type == 'all':
            # 統計各類數據
            metrics = {}
            for point in data:
                metric = point["metric"]
                if metric not in metrics:
                    metrics[metric] = []
                metrics[metric].append(point["value"])
            
            summary = "查詢到以下健康數據：\n"
            for metric, values in metrics.items():
                name = metric_names.get(metric, metric)
                if values:
                    avg_value = sum(values) / len(values)
                    latest_value = values[0] if values else 0
                    # 不顯示記錄數，避免使用者困惑
                    summary += f"• {name}: 最新 {latest_value:.1f}，平均 {avg_value:.1f}\n"
        else:
            name = metric_names.get(metric_type, metric_type)
            if len(data) == 1:
                point = data[0]
                timestamp = datetime.fromisoformat(point['timestamp']).strftime("%m/%d %H:%M")
                summary = f"最新{name}數據：{point['value']} {point['unit']} (記錄於 {timestamp})"
            else:
                values = [p["value"] for p in data]
                avg_value = sum(values) / len(values)
                latest_value = values[0] if values else 0
                # 不顯示記錄數，避免使用者困惑（AI 會根據需要提取重點）
                summary = f"{name}數據：最新 {latest_value:.1f} {data[0]['unit']}，平均 {avg_value:.1f}"
        
        return summary
