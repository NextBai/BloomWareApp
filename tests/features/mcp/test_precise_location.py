#!/usr/bin/env python3
"""
測試精確地址功能
驗證 reverse_geocode 與 forward_geocode 是否能正確提取門牌、路口資訊
"""

import pytest

pytestmark = pytest.mark.skip(reason='Integration script - skipped in automated suite')

import asyncio
import logging
from features.mcp.tools.geocode_tool import ReverseGeocodeTool
from features.mcp.tools.geocoding_tool import ForwardGeocodeTool

# 設置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_reverse_geocode():
    """測試反向地理編碼（座標→地址）"""
    print("\n" + "="*60)
    print("測試場景 1: Reverse Geocode（座標 → 精確地址）")
    print("="*60)
    
    test_cases = [
        {"lat": 25.0330, "lon": 121.5654, "name": "台北101"},
        {"lat": 25.0478, "lon": 121.5170, "name": "台北車站"},
        {"lat": 24.9932, "lon": 121.3261, "name": "桃園火車站"},
        {"lat": 25.0625, "lon": 121.1876, "name": "銘傳大學桃園校區"},
        {"lat": 25.0853, "lon": 121.5603, "name": "台北市政府"},
    ]
    
    for case in test_cases:
        print(f"\n📍 測試地點: {case['name']}")
        print(f"   座標: ({case['lat']}, {case['lon']})")
        
        try:
            result = await ReverseGeocodeTool.execute({
                "lat": case['lat'],
                "lon": case['lon']
            })
            
            if result.get("success"):
                data = result.get("data", {})
                print(f"   ✅ 成功取得地址:")
                print(f"      標籤: {data.get('label')}")
                print(f"      詳細地址: {data.get('detailed_address')}")
                if data.get('road'):
                    print(f"      路段: {data.get('road')}")
                if data.get('house_number'):
                    print(f"      門牌: {data.get('house_number')}")
                if data.get('postcode'):
                    print(f"      郵遞區號: {data.get('postcode')}")
                if data.get('suburb'):
                    print(f"      區域: {data.get('suburb')}")
                if data.get('city'):
                    print(f"      城市: {data.get('city')}")
            else:
                print(f"   ❌ 失敗: {result.get('error')}")
        except Exception as e:
            print(f"   ❌ 異常: {e}")

async def test_forward_geocode():
    """測試正向地理編碼（地名→座標）"""
    print("\n" + "="*60)
    print("測試場景 2: Forward Geocode（地名 → 座標 + 精確地址）")
    print("="*60)
    
    test_queries = [
        "台北101",
        "桃園火車站",
        "銘傳大學桃園校區",
        "台北車站",
        "淡水捷運站",
        "台北市政府",
        "中正紀念堂",
    ]
    
    for query in test_queries:
        print(f"\n🔍 查詢: {query}")
        
        try:
            result = await ForwardGeocodeTool.execute({"query": query, "limit": 1})
            
            if result.get("success"):
                data = result.get("data", {})
                best = data.get("best_match", {})
                print(f"   ✅ 找到地點:")
                print(f"      標籤: {best.get('label')}")
                print(f"      座標: ({best.get('lat')}, {best.get('lon')})")
                print(f"      詳細地址: {best.get('detailed_address')}")
                if best.get('road'):
                    print(f"      路段: {best.get('road')}")
                if best.get('house_number'):
                    print(f"      門牌: {best.get('house_number')}")
                if best.get('postcode'):
                    print(f"      郵遞區號: {best.get('postcode')}")
            else:
                print(f"   ❌ 失敗: {result.get('error')}")
        except Exception as e:
            print(f"   ❌ 異常: {e}")

async def test_precision_comparison():
    """測試精度對比（舊 vs 新）"""
    print("\n" + "="*60)
    print("測試場景 3: 精度對比（展示改進效果）")
    print("="*60)
    
    # 測試一個有明確門牌的地點
    test_lat = 25.0330
    test_lon = 121.5654
    
    print(f"\n測試座標: ({test_lat}, {test_lon}) - 台北101附近")
    
    result = await ReverseGeocodeTool.execute({"lat": test_lat, "lon": test_lon})
    
    if result.get("success"):
        data = result.get("data", {})
        
        print("\n📊 解析結果對比:")
        print(f"   舊版輸出（只有城市）: {data.get('city')}, {data.get('admin')}")
        print(f"   新版標籤（精確地址）: {data.get('label')}")
        print(f"   新版詳細地址: {data.get('detailed_address')}")
        
        print("\n🔍 詳細欄位:")
        print(f"   名稱: {data.get('name')}")
        print(f"   路段: {data.get('road')}")
        print(f"   門牌: {data.get('house_number')}")
        print(f"   區域: {data.get('suburb')}")
        print(f"   行政區: {data.get('city_district')}")
        print(f"   城市: {data.get('city')}")
        print(f"   郵遞區號: {data.get('postcode')}")
        print(f"   設施類型: {data.get('amenity')}")
        print(f"   建築類型: {data.get('building')}")

async def main():
    """執行所有測試"""
    await test_reverse_geocode()
    await test_forward_geocode()
    await test_precision_comparison()
    
    print("\n" + "="*60)
    print("測試完成！")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(main())
