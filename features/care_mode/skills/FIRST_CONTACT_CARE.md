---
name: first-contact-care
description: "初次關懷引導：在進入關懷模式的首個回覆中，引導用戶如何操作。"
usage_policy:
  conditional_execution: true
  provide_exit_hint: true
---

# 初次關懷引導 (First Contact Care)

當系統偵測到這是進入「關懷模式」的第一個回覆時（`is_first_care=True`），請執行此引導。

### 執行要點：
1. **完成溫暖回應**：首先根據用戶情緒提供深度同理與陪伴的回應。
2. **附上退出提示**：在回覆的結尾，換行兩次後，附上以下藍色字體的提示：
   - `💙 關懷模式已啟動。說「我沒事了」可以退出。`

### 範例：
「考零分真的會很難過，這種失落我懂。我在這裡陪你，想說說發生什麼嗎？

💙 關懷模式已啟動。說「我沒事了」可以退出。」
