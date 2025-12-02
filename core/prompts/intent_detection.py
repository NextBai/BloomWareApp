"""
意圖檢測 Prompt 模板
精簡化設計，減少 token 消耗約 40%
"""

# 工具特定規則（按需載入）
TOOL_RULES = {
    "weather": """天氣查詢：城市必須用英文（台北→Taipei, 高雄→Kaohsiung），預設 Taipei""",

    "exchange": """匯率查詢：貨幣必須用 ISO 4217 代碼（美元→USD, 台幣→TWD），預設 USD→TWD""",

    "news": """新聞查詢：「新聞」「消息」「報導」→ news_query，country/language 用英文代碼（tw, zh）""",

    "bus": """公車查詢：「公車」「巴士」→ tdx_bus_arrival
- route_name 必須是公車路線號碼（如 137、307、紅30）
- 「往 X 的公車」「去 X 的公車」不是路線查詢，應使用 directions 或 forward_geocode
- 「附近公車」「公車站」不需 route_name，系統用 GPS 查詢
例：「137公車」→ tdx_bus_arrival:route_name=137
例：「往台北的公車」→ forward_geocode:query=台北（這是導航需求）""",

    "train": """台鐵查詢：「火車」「台鐵」→ tdx_train
「往XX」「到XX」是目的地（destination_station），不是起點
沒說起點就不填 origin_station，讓 GPS 決定
例：「往台北的火車」→ tdx_train:destination_station=台北""",

    "youbike": """YouBike 查詢：「YouBike」「Ubike」「微笑單車」「共享單車」→ tdx_youbike
城市參數必須用英文（台北→Taipei, 桃園→Taoyuan），站名可用中文
不是 tdx_parking！這是單車不是停車場""",

    "location": """位置查詢：
「我在哪」「這是哪裡」→ reverse_geocode（不需參數）
「怎麼去 X」→ forward_geocode:query=X""",
}

# 情緒標籤說明
EMOTION_RULES = """情緒判斷：neutral/happy/sad/angry/fear/surprise
- happy: 開心、興奮（「好開心！」「太棒了」）
- sad: 難過、沮喪（「好難過」「心情不好」）
- angry: 生氣、煩躁（「煩死了」「氣死我了」）
- fear: 恐懼、擔心（「好害怕」「怎麼辦」）
- surprise: 驚訝（「什麼！」「真的假的」）
- neutral: 其他"""


def get_intent_prompt(tools_description: str, include_rules: list = None) -> str:
    """
    生成意圖檢測 Prompt

    Args:
        tools_description: 可用工具描述
        include_rules: 要包含的工具規則列表，None 表示全部

    Returns:
        精簡化的 System Prompt
    """
    # 基礎 Prompt
    base = f"""你是意圖解析助手。分析用戶消息，決定是否調用工具。

可用工具：
{tools_description}

"""

    # 添加工具規則
    if include_rules is None:
        include_rules = list(TOOL_RULES.keys())

    rules_text = "\n".join(
        f"- {TOOL_RULES[rule]}"
        for rule in include_rules
        if rule in TOOL_RULES
    )

    if rules_text:
        base += f"""工具規則：
{rules_text}

"""

    # 添加情緒規則
    base += f"""{EMOTION_RULES}

回應格式：
- is_tool_call: true/false
- tool_name: 工具名稱:參數（is_tool_call=true 時）
- emotion: 情緒標籤

示例：
- "台北天氣" → {{"is_tool_call": true, "tool_name": "weather_query:city=Taipei", "emotion": "neutral"}}
- "你好" → {{"is_tool_call": false, "tool_name": "", "emotion": "neutral"}}
- "我好難過" → {{"is_tool_call": false, "tool_name": "", "emotion": "sad"}}"""

    return base
