#!/usr/bin/env python3
"""
測試導航功能修復
驗證地點查詢與導航是否正常工作
"""

import pytest

pytestmark = pytest.mark.skip(reason='Integration script - skipped in automated suite')

import asyncio
import logging
from features.mcp.agent_bridge import MCPAgentBridge

# 設置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_navigation():
    """測試導航功能"""
    bridge = MCPAgentBridge()
    await bridge.async_initialize()
    
    print("\n" + "="*60)
    print("測試場景 1: 單純地點查詢")
    print("="*60)
    
    test_messages_1 = [
        "銘傳大學在哪裡",
        "桃園火車站的位置",
        "台北101地址"
    ]
    
    for msg in test_messages_1:
        print(f"\n用戶: {msg}")
        has_intent, intent_data = await bridge.detect_intent(msg)
        print(f"意圖檢測: has_intent={has_intent}")
        if intent_data:
            print(f"意圖資料: {intent_data}")
    
    print("\n" + "="*60)
    print("測試場景 2: 導航需求（應自動串接 directions）")
    print("="*60)
    
    test_messages_2 = [
        "怎麼去桃園火車站",
        "如何去銘傳大學",
        "到台北101怎麼走"
    ]
    
    # 模擬用戶位置（桃園）
    test_user_id = "test_user_123"
    
    for msg in test_messages_2:
        print(f"\n用戶: {msg}")
        has_intent, intent_data = await bridge.detect_intent(msg)
        print(f"意圖檢測: has_intent={has_intent}")
        if intent_data:
            print(f"意圖資料: {intent_data}")
            
            # 處理意圖
            if intent_data.get("type") == "mcp_tool":
                print(f"\n執行工具: {intent_data.get('tool_name')}")
                print(f"參數: {intent_data.get('arguments')}")
    
    print("\n" + "="*60)
    print("測試場景 3: 點到點查詢")
    print("="*60)
    
    test_messages_3 = [
        "從銘傳大學到桃園火車站要多久",
        "台北車站到淡水捷運站怎麼走"
    ]
    
    for msg in test_messages_3:
        print(f"\n用戶: {msg}")
        has_intent, intent_data = await bridge.detect_intent(msg)
        print(f"意圖檢測: has_intent={has_intent}")
        if intent_data:
            print(f"意圖資料: {intent_data}")

if __name__ == "__main__":
    asyncio.run(test_navigation())
