"""
測試動態工具路由器
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tool_router import ToolRouter


class TestToolRouter:
    """測試 ToolRouter 類別"""
    
    def _create_mock_tools(self):
        """建立模擬工具列表"""
        return [
            {"type": "function", "function": {"name": "weather_query", "description": "天氣查詢"}},
            {"type": "function", "function": {"name": "tdx_bus_arrival", "description": "公車到站"}},
            {"type": "function", "function": {"name": "tdx_youbike", "description": "YouBike 查詢"}},
            {"type": "function", "function": {"name": "reverse_geocode", "description": "位置查詢"}},
            {"type": "function", "function": {"name": "news_query", "description": "新聞查詢"}},
            {"type": "function", "function": {"name": "exchange_query", "description": "匯率查詢"}},
        ]
    
    def test_detect_categories_weather(self):
        """測試天氣分類檢測"""
        router = ToolRouter()
        
        categories = router._detect_categories("台北天氣怎麼樣")
        assert "weather" in categories
        
        categories = router._detect_categories("今天會下雨嗎")
        assert "weather" in categories
    
    def test_detect_categories_transportation(self):
        """測試交通分類檢測"""
        router = ToolRouter()
        
        categories = router._detect_categories("附近的公車站")
        assert "transportation" in categories
        
        categories = router._detect_categories("YouBike 在哪")
        assert "transportation" in categories
    
    def test_detect_categories_location(self):
        """測試位置分類檢測"""
        router = ToolRouter()
        
        categories = router._detect_categories("我在哪裡")
        assert "location" in categories
        
        categories = router._detect_categories("怎麼去台北車站")
        assert "location" in categories
    
    def test_filter_tools_basic(self):
        """測試基本工具過濾"""
        router = ToolRouter()
        tools = self._create_mock_tools()
        
        filtered = router.filter_tools(tools, "台北天氣", {})
        
        # 應該返回工具（天氣相關優先）
        assert len(filtered) > 0
        tool_names = [t["function"]["name"] for t in filtered]
        assert "weather_query" in tool_names
    
    def test_filter_tools_night_exclusion(self):
        """測試深夜工具排除"""
        router = ToolRouter()
        tools = self._create_mock_tools()
        
        # 深夜（凌晨 2 點）
        filtered = router.filter_tools(tools, "公車", {"hour": 2})
        tool_names = [t["function"]["name"] for t in filtered]
        
        # 深夜應該排除公車和捷運
        assert "tdx_bus_arrival" not in tool_names
    
    def test_filter_tools_daytime(self):
        """測試白天工具不排除"""
        router = ToolRouter()
        tools = self._create_mock_tools()
        
        # 白天（下午 2 點）
        filtered = router.filter_tools(tools, "公車", {"hour": 14})
        tool_names = [t["function"]["name"] for t in filtered]
        
        # 白天應該包含公車
        assert "tdx_bus_arrival" in tool_names
    
    def test_sort_tools_priority(self):
        """測試工具排序"""
        router = ToolRouter()
        tools = self._create_mock_tools()
        
        # 天氣查詢應該排在前面
        filtered = router.filter_tools(tools, "天氣", {"hour": 12})
        
        # 第一個應該是天氣相關工具
        assert filtered[0]["function"]["name"] == "weather_query"
    
    def test_record_tool_usage(self):
        """測試工具使用記錄"""
        router = ToolRouter()
        
        router.record_tool_usage("user1", "weather_query")
        router.record_tool_usage("user1", "weather_query")
        router.record_tool_usage("user1", "news_query")
        
        assert router._user_preferences["user1"]["weather_query"] == 2
        assert router._user_preferences["user1"]["news_query"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
