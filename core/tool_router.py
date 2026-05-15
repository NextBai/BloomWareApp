"""
動態工具路由器
2025 最佳實踐：根據上下文智能過濾工具，減少 token 消耗

功能：
1. 位置過濾：用戶沒有位置時，排除需要位置的工具
2. 關鍵字過濾：根據用戶意圖關鍵字，優先顯示相關分類
3. 時間過濾：根據時間排除不適用的工具
4. 優先級排序：常用工具優先顯示
"""

import re
import logging
from typing import Dict, List, Any, Optional, Set
from datetime import datetime

from core.logging import get_logger

logger = get_logger("core.tool_router")


class ToolRouter:
    """
    動態工具路由器
    
    根據上下文智能過濾和排序工具，減少傳遞給 GPT 的工具數量
    """
    
    # 分類關鍵字映射
    CATEGORY_KEYWORDS = {
        "weather": ["天氣", "氣溫", "下雨", "晴天", "陰天", "weather", "溫度", "濕度", "天気", "雨", "気温"],
        "transportation": [
            "公車", "巴士", "bus", "火車", "台鐵", "高鐵", "捷運", "metro",
            "youbike", "ubike", "微笑單車", "共享單車", "停車場", "停車位",
            "バス", "電車", "地下鉄", "新幹線", "駐輪場", "駐車場"
        ],
        "location": ["我在哪", "這是哪", "位置", "地址", "怎麼去", "導航", "路線", "どこ", "現在地", "住所", "ナビ"],
        "information": ["新聞", "消息", "報導", "news", "ニュース", "報道"],
        "finance": ["匯率", "換算", "美元", "日圓", "歐元", "currency", "exchange", "為替", "レート", "円", "ドル"],
        "health": ["心率", "步數", "血氧", "睡眠", "健康", "運動", "健康", "歩数", "心拍", "運動"],
    }
    
    # 時間敏感工具（深夜可能不適用）
    NIGHT_EXCLUDED_TOOLS = {
        "tdx_bus_arrival",  # 深夜公車班次少
        "tdx_metro",        # 捷運深夜停駛
    }
    
    # 工具優先級（數字越小優先級越高）
    DEFAULT_PRIORITY = {
        "weather_query": 1,
        "reverse_geocode": 2,
        "forward_geocode": 3,
        "directions": 4,
        "tdx_bus_arrival": 5,
        "tdx_youbike": 6,
        "tdx_metro": 7,
        "tdx_train": 8,
        "tdx_thsr": 9,
        "news_query": 10,
        "exchange_query": 11,
        "healthkit_query": 12,
        "tdx_parking": 13,
    }
    
    def __init__(self):
        self._user_preferences: Dict[str, Dict[str, int]] = {}  # user_id -> {tool_name: usage_count}
    
    def filter_tools(
        self,
        tools: List[Dict[str, Any]],
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        根據上下文過濾和排序工具
        
        Args:
            tools: OpenAI tools 格式的工具列表
            message: 用戶消息
            context: 上下文資訊（位置、時間、用戶偏好等）
        
        Returns:
            過濾和排序後的工具列表
        """
        context = context or {}
        
        # 1. 檢測用戶意圖分類
        detected_categories = self._detect_categories(message)
        logger.debug(f"🎯 檢測到的分類: {detected_categories}")
        
        # 2. 過濾工具
        language = context.get("language")
        filtered_tools = []
        for tool in tools:
            tool_name = tool.get("function", {}).get("name", "")
            
            # 位置過濾
            if not self._check_location_requirement(tool_name, context):
                logger.debug(f"⏭️ 跳過 {tool_name}（需要位置但用戶未提供）")
                continue
            
            # 時間過濾
            if not self._check_time_requirement(tool_name, context):
                logger.debug(f"⏭️ 跳過 {tool_name}（深夜不適用）")
                continue
            
            filtered_tools.append(tool)
        
        # 3. 排序工具（相關分類優先）
        # 如果是日語，特別提升新聞與天氣的優先級（補償關鍵字可能不全的情況）
        if language == 'ja':
            detected_categories.add("weather")
            detected_categories.add("finance")
            detected_categories.add("information")

        sorted_tools = self._sort_tools(filtered_tools, detected_categories, context)
        
        # 4. 限制工具數量（減少 token 消耗）
        max_tools = self._get_max_tools(detected_categories)
        if len(sorted_tools) > max_tools:
            logger.info(f"📉 工具數量從 {len(sorted_tools)} 限制到 {max_tools}")
            sorted_tools = sorted_tools[:max_tools]
        
        logger.info(f"🔧 過濾後工具: {[t['function']['name'] for t in sorted_tools]} (用戶語系: {language})")
        return sorted_tools
    
    def _detect_categories(self, message: str) -> Set[str]:
        """檢測用戶消息中的意圖分類"""
        message_lower = message.lower()
        detected = set()
        
        for category, keywords in self.CATEGORY_KEYWORDS.items():
            for keyword in keywords:
                if keyword.lower() in message_lower:
                    detected.add(category)
                    break
        
        return detected
    
    def _check_location_requirement(
        self,
        tool_name: str,
        context: Dict[str, Any],
    ) -> bool:
        """檢查工具的位置需求"""
        # 需要位置的工具
        location_required_tools = {
            "reverse_geocode",
            "tdx_bus_arrival",
            "tdx_youbike",
            "tdx_metro",
            "tdx_parking",
            "tdx_train",
            "tdx_thsr",
        }
        
        if tool_name not in location_required_tools:
            return True
        
        # 檢查是否有位置資訊
        has_location = (
            context.get("lat") is not None and
            context.get("lon") is not None
        )
        
        # 如果沒有位置，但用戶明確要求（如「附近的公車」），仍然保留工具
        # 讓工具自己處理缺少位置的情況
        return True  # 暫時不嚴格過濾，讓工具自己處理
    
    def _check_time_requirement(
        self,
        tool_name: str,
        context: Dict[str, Any],
    ) -> bool:
        """檢查工具的時間需求"""
        if tool_name not in self.NIGHT_EXCLUDED_TOOLS:
            return True
        
        # 檢查是否為深夜（00:00 - 05:00）
        current_hour = context.get("hour")
        if current_hour is None:
            current_hour = datetime.now().hour
        
        is_night = 0 <= current_hour < 5
        
        # 深夜時排除某些工具
        return not is_night
    
    def _sort_tools(
        self,
        tools: List[Dict[str, Any]],
        detected_categories: Set[str],
        context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """排序工具（相關分類優先）"""
        
        def get_priority(tool: Dict[str, Any]) -> int:
            tool_name = tool.get("function", {}).get("name", "")
            
            # 基礎優先級
            base_priority = self.DEFAULT_PRIORITY.get(tool_name, 100)
            
            # 如果工具屬於檢測到的分類，降低優先級數字（提高優先級）
            tool_category = self._get_tool_category(tool_name)
            if tool_category in detected_categories:
                base_priority -= 50  # 相關工具優先
            
            # 用戶偏好加成
            user_id = context.get("user_id")
            if user_id and user_id in self._user_preferences:
                usage_count = self._user_preferences[user_id].get(tool_name, 0)
                base_priority -= min(usage_count, 10)  # 最多降低 10
            
            return base_priority
        
        return sorted(tools, key=get_priority)
    
    def _get_tool_category(self, tool_name: str) -> str:
        """取得工具的分類"""
        category_map = {
            "weather_query": "weather",
            "reverse_geocode": "location",
            "forward_geocode": "location",
            "directions": "location",
            "tdx_bus_arrival": "transportation",
            "tdx_youbike": "transportation",
            "tdx_metro": "transportation",
            "tdx_train": "transportation",
            "tdx_thsr": "transportation",
            "tdx_parking": "transportation",
            "news_query": "information",
            "exchange_query": "finance",
            "healthkit_query": "health",
        }
        return category_map.get(tool_name, "general")
    
    def _get_max_tools(self, detected_categories: Set[str]) -> int:
        """根據檢測到的分類決定最大工具數量"""
        if not detected_categories:
            # 沒有明確分類，返回所有工具
            return 20
        
        if len(detected_categories) == 1:
            # 單一分類，只需保留核心工具，顯著減少 LLM 負擔
            return 6
        
        # 多個分類，保持在較小範圍
        return 10
    
    def record_tool_usage(self, user_id: str, tool_name: str) -> None:
        """記錄工具使用（用於優先級調整）"""
        if user_id not in self._user_preferences:
            self._user_preferences[user_id] = {}
        
        current = self._user_preferences[user_id].get(tool_name, 0)
        self._user_preferences[user_id][tool_name] = current + 1
        
        logger.debug(f"📊 記錄工具使用: {user_id} -> {tool_name} ({current + 1})")


# 全域單例
tool_router = ToolRouter()
