"""
Reasoning Effort 分級策略（2025 最佳實踐）
根據任務類型和用戶情緒動態調整 GPT-5 推理強度

參考：https://cookbook.openai.com/examples/gpt-5/gpt-5_new_params_and_tools
"""

import logging
from typing import Optional, Literal

logger = logging.getLogger(__name__)

# GPT-5 Reasoning Effort 類型
ReasoningEffort = Literal["minimal", "low", "medium", "high"]


class ReasoningStrategy:
    """
    動態推理強度策略

    根據任務特性自動選擇最佳 reasoning_effort：
    - minimal: 極速回應（<1秒），節省 80% reasoning tokens
    - low: 快速回應（1-2秒），適合簡單任務
    - medium: 標準推理（2-5秒），預設值
    - high: 深度推理（5-15秒），複雜任務
    """

    @staticmethod
    def get_effort_for_task(
        task_type: str,
        user_emotion: Optional[str] = None,
        complexity_hint: Optional[str] = None
    ) -> ReasoningEffort:
        """
        根據任務類型選擇推理強度

        Args:
            task_type: 任務類型（intent_detection, tool_call, chat, complex_reasoning）
            user_emotion: 用戶情緒（sad, angry, fear 等負面情緒優先速度）
            complexity_hint: 複雜度提示（simple, moderate, complex）

        Returns:
            reasoning_effort: minimal/low/medium/high
        """

        # 🔥 規則 1：意圖檢測使用 minimal reasoning（極速模式，減少初始延遲）
        if task_type == "intent_detection":
            logger.debug("🧠 意圖檢測 → minimal reasoning（極速回應）")
            return "minimal"

        # 🔥 規則 2：關懷模式優先速度（用戶情緒不佳時不要讓他等）
        if user_emotion in ["sad", "angry", "fear"]:
            logger.info(f"💙 檢測到負面情緒 [{user_emotion}] → minimal reasoning（快速關懷）")
            return "minimal"

        # 🔥 規則 3：工具調用使用 low（快速但準確）
        if task_type == "tool_call":
            logger.debug("🔧 工具調用 → low reasoning（快速執行）")
            return "low"

        # 🔥 規則 4：格式化回應使用 low（不需深度推理）
        if task_type == "format_response":
            logger.debug("🎨 格式化回應 → low reasoning")
            return "low"

        # 🔥 規則 5：複雜對話根據複雜度調整
        if task_type == "chat":
            if complexity_hint == "simple":
                logger.debug("💬 簡單對話 → low reasoning")
                return "low"
            elif complexity_hint == "complex":
                logger.debug("💬 複雜對話 → medium reasoning")
                return "medium"
            else:
                # 預設：一般對話用 low（節省成本）
                logger.debug("💬 一般對話 → low reasoning")
                return "low"

        # 🔥 規則 6：複雜推理任務使用 medium/high
        if task_type == "complex_reasoning":
            logger.info("🧩 複雜推理任務 → medium reasoning")
            return "medium"

        # 🔥 規則 7：記憶摘要等批次任務可用 medium（非即時）
        if task_type == "memory_summary":
            logger.debug("📚 記憶摘要 → medium reasoning（批次任務）")
            return "medium"

        # 預設：low（保守策略，平衡速度與品質）
        logger.debug(f"⚙️ 未知任務類型 [{task_type}] → low reasoning（預設）")
        return "low"

    @staticmethod
    def get_effort_description(effort: ReasoningEffort) -> str:
        """獲取推理強度描述（用於日誌）"""
        descriptions = {
            "minimal": "極速模式（<1秒，省 80% tokens）",
            "low": "快速模式（1-2秒）",
            "medium": "標準模式（2-5秒）",
            "high": "深度推理（5-15秒）"
        }
        return descriptions.get(effort, "未知")

    @staticmethod
    def estimate_latency(effort: ReasoningEffort) -> tuple[float, float]:
        """
        估算延遲範圍（秒）

        Returns:
            (min_latency, max_latency)
        """
        latency_map = {
            "minimal": (0.5, 1.0),
            "low": (1.0, 2.0),
            "medium": (2.0, 5.0),
            "high": (5.0, 15.0)
        }
        return latency_map.get(effort, (1.0, 3.0))


# 全域單例
reasoning_strategy = ReasoningStrategy()


def get_optimal_reasoning_effort(
    task_type: str,
    user_emotion: Optional[str] = None,
    complexity_hint: Optional[str] = None
) -> ReasoningEffort:
    """
    便捷函數：獲取最佳推理強度

    範例：
        # 意圖檢測
        effort = get_optimal_reasoning_effort("intent_detection")
        # → "minimal"

        # 關懷模式
        effort = get_optimal_reasoning_effort("chat", user_emotion="sad")
        # → "minimal"

        # 工具調用
        effort = get_optimal_reasoning_effort("tool_call")
        # → "low"

        # 複雜對話
        effort = get_optimal_reasoning_effort("chat", complexity_hint="complex")
        # → "medium"
    """
    return reasoning_strategy.get_effort_for_task(task_type, user_emotion, complexity_hint)
