import os
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import json

# 設置日誌
LOG_LEVEL_NAME = os.getenv("BLOOMWARE_LOG_LEVEL", "WARNING").upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_NAME, logging.WARNING)
logging.basicConfig(level=LOG_LEVEL, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("MemorySystem")
logger.setLevel(LOG_LEVEL)

# 載入環境變數
from dotenv import load_dotenv
load_dotenv()

# 嘗試導入 OpenAI
try:
    from openai import OpenAI
    memory_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    logger.info("記憶系統成功導入 OpenAI SDK")
except ImportError:
    logger.error("Failed to import OpenAI for memory system")
    memory_client = None
except Exception as e:
    logger.error(f"初始化記憶系統 OpenAI 客戶端時出錯: {e}")
    memory_client = None

# 導入數據庫函數
try:
    from .database import save_memory, get_user_memories, search_memories
    db_available = True
except ImportError:
    db_available = False
    logger.warning("無法導入記憶數據庫函數")


class MemoryExtractor:
    """記憶提取器：從對話中提取重要信息"""

    def __init__(self):
        self.memory_types = {
            "personal_info": {
                "keywords": ["我叫", "我的名字", "我今年", "我的年齡", "我是", "我從事", "我的工作", "我住在", "我的地址", "我的電話", "我的email", "我的興趣"],
                "description": "個人基本信息",
                "importance_base": 0.9
            },
            "preferences": {
                "keywords": ["我喜歡", "我不喜歡", "我的偏好", "我討厭", "我想要", "我需要", "我習慣", "我通常"],
                "description": "個人偏好和習慣",
                "importance_base": 0.8
            },
            "events": {
                "keywords": ["我有個約", "我約了", "我預計", "我計劃", "我會", "我要", "記得", "提醒我", "下次", "明天", "後天", "下週"],
                "description": "重要事件和約定",
                "importance_base": 0.8
            },
            "knowledge": {
                "keywords": ["我知道", "我學到", "我發現", "我了解", "我學會", "經驗", "教訓", "總結"],
                "description": "學習到的知識和經驗",
                "importance_base": 0.7
            },
            "goals": {
                "keywords": ["我的目標", "我想達成", "我希望", "我的夢想", "我的計劃", "長期目標", "短期目標"],
                "description": "長期和短期目標",
                "importance_base": 0.8
            }
        }

    def extract_memories(self, user_message: str, assistant_response: str = "") -> List[Dict[str, Any]]:
        """從用戶消息和助手回應中提取記憶"""
        memories = []

        # 合併用戶消息和助手回應進行分析
        full_text = f"用戶: {user_message}\n助手: {assistant_response}"

        for memory_type, config in self.memory_types.items():
            # 檢查關鍵字匹配
            matched_keywords = []
            for keyword in config["keywords"]:
                if keyword in user_message.lower():
                    matched_keywords.append(keyword)

            if matched_keywords:
                # 提取相關內容
                extracted_content = self._extract_content(user_message, matched_keywords)
                if extracted_content:
                    importance = self._calculate_importance(extracted_content, config["importance_base"])

                    memory = {
                        "type": memory_type,
                        "content": extracted_content,
                        "importance": importance,
                        "trigger_keywords": matched_keywords,
                        "source": "keyword_extraction",
                        "metadata": {
                            "extracted_at": datetime.now().isoformat(),
                            "confidence": len(matched_keywords) / len(config["keywords"])
                        }
                    }
                    memories.append(memory)

        return memories

    def _extract_content(self, text: str, keywords: List[str]) -> Optional[str]:
        """從文本中提取記憶內容"""
        # 簡單的內容提取邏輯
        sentences = text.split('。')
        relevant_sentences = []

        for sentence in sentences:
            if any(keyword in sentence for keyword in keywords):
                relevant_sentences.append(sentence.strip())

        if relevant_sentences:
            return '。'.join(relevant_sentences) + '。'

        return None

    def _calculate_importance(self, content: str, base_importance: float) -> float:
        """計算記憶的重要性分數"""
        # 基於內容長度和關鍵字密度調整重要性
        content_length = len(content)
        if content_length < 10:
            return base_importance * 0.5
        elif content_length > 100:
            return min(base_importance * 1.2, 1.0)
        else:
            return base_importance


class MemoryAnalyzer:
    """記憶分析器：使用AI分析對話內容"""

    def __init__(self):
        pass

    async def analyze_conversation(self, user_message: str, assistant_response: str = "",
                                  conversation_history: List[Dict] = None) -> List[Dict[str, Any]]:
        """使用AI分析對話內容，提取重要記憶"""
        if not memory_client:
            logger.warning("OpenAI客戶端不可用，跳過AI記憶分析")
            return []

        try:
            # 構建簡潔的分析提示
            system_prompt = """你是記憶分析助手。從用戶對話中提取重要資訊。

規則：
1. 只提取重要且持久的資訊
2. 避免記住無關緊要的內容
3. 區分類型：personal_info（個人信息）、preferences（偏好）、goals（目標）

返回JSON格式：
{
  "memories": [
    {
      "type": "personal_info|preferences|goals",
      "content": "具體內容",
      "importance": 0.8
    }
  ]
}

如果沒有重要資訊，返回空列表。"""

            # 準備對話歷史（最近幾條）
            recent_history = ""
            if conversation_history:
                recent_messages = conversation_history[-6:]  # 最近3輪對話
                for msg in recent_messages:
                    role = "用戶" if msg.get("role") == "user" else "助手"
                    recent_history += f"{role}: {msg.get('content', '')}\n"

            user_prompt = f"""分析對話，提取重要記憶：

用戶: {user_message}
助手: {assistant_response}

提取任何重要資訊。"""

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

            # 嘗試調用OpenAI API，最多重試2次
            max_retries = 2
            for attempt in range(max_retries + 1):
                try:
                    if attempt > 0:
                        # 如果是重試，增加token限制
                        max_tokens_value = 2000 + (attempt * 1000)
                        logger.info(f"重試AI分析 (嘗試 {attempt + 1}/{max_retries + 1})，增加token限制到 {max_tokens_value}")
                    else:
                        max_tokens_value = 2000

                    response = memory_client.chat.completions.create(
                        model="gpt-5-nano",
                        messages=messages,
                        max_completion_tokens=max_tokens_value,  # 修正：使用 max_completion_tokens 而非 max_tokens
                        reasoning_effort="low"  # 記憶分析需要理解，但不需深度推理
                    )
                    break  # 成功後跳出重試循環

                except Exception as api_error:
                    error_str = str(api_error).lower()
                    if "max_tokens" in error_str or "token limit" in error_str:
                        if attempt < max_retries:
                            logger.warning(f"AI分析遇到token限制錯誤，正在重試 ({attempt + 1}/{max_retries + 1}): {api_error}")
                            continue
                        else:
                            logger.error(f"AI分析在 {max_retries + 1} 次嘗試後仍然遇到token限制錯誤: {api_error}")
                            return []  # 返回空列表，回退到關鍵字提取
                    else:
                        # 其他類型的錯誤，直接拋出
                        raise api_error

            result_text = response.choices[0].message.content.strip()

            # 解析JSON結果 - 嘗試多種解析方式
            try:
                # 首先嘗試直接解析
                result = json.loads(result_text)
                memories = result.get("memories", [])
            except json.JSONDecodeError:
                # 如果直接解析失敗，嘗試提取JSON部分
                import re
                json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
                if json_match:
                    try:
                        result = json.loads(json_match.group())
                        memories = result.get("memories", [])
                    except json.JSONDecodeError:
                        logger.warning(f"提取的JSON仍然無效: {json_match.group()[:200]}...")
                        memories = []
                else:
                    logger.warning(f"無法在AI響應中找到JSON: {result_text[:200]}...")
                    memories = []

            # 添加元數據
            for memory in memories:
                if isinstance(memory, dict):
                    memory["source"] = "ai_analysis"
                    memory["metadata"] = {
                        "analyzed_at": datetime.now().isoformat(),
                        "conversation_context": user_message[:100] + "..." if len(user_message) > 100 else user_message
                    }

            logger.info(f"AI分析提取到 {len(memories)} 條記憶")
            return memories

        except Exception as e:
            logger.error(f"AI記憶分析時發生錯誤: {e}")
            return []


class MemoryManager:
    """記憶管理器：統籌記憶的提取、存儲和檢索"""

    def __init__(self):
        self.extractor = MemoryExtractor()
        self.analyzer = MemoryAnalyzer()

    async def process_conversation(self, user_id: str, user_message: str,
                                 assistant_response: str = "",
                                 conversation_history: List[Dict] = None) -> Dict[str, Any]:
        """處理對話，提取並存儲記憶"""
        result = {
            "extracted_memories": 0,
            "saved_memories": 0,
            "errors": []
        }

        try:
            # 1. 使用關鍵字提取記憶
            keyword_memories = self.extractor.extract_memories(user_message, assistant_response)

            # 2. 使用AI分析提取記憶（如果可用）
            ai_memories = []
            if memory_client:
                ai_memories = await self.analyzer.analyze_conversation(
                    user_message, assistant_response, conversation_history
                )

            # 3. 合併記憶（去重）
            all_memories = self._merge_memories(keyword_memories, ai_memories)
            result["extracted_memories"] = len(all_memories)

            # 4. 存儲記憶
            if db_available and all_memories:
                saved_count = 0
                for memory in all_memories:
                    try:
                        save_result = await save_memory(
                            user_id=user_id,
                            memory_type=memory["type"],
                            content=memory["content"],
                            importance=memory["importance"],
                            metadata=memory.get("metadata", {})
                        )
                        if save_result["success"]:
                            saved_count += 1
                    except Exception as e:
                        logger.error(f"保存記憶失敗: {e}")
                        result["errors"].append(str(e))

                result["saved_memories"] = saved_count

            logger.info(f"處理用戶 {user_id} 的對話，提取 {len(all_memories)} 條記憶，保存 {result['saved_memories']} 條")

        except Exception as e:
            logger.error(f"處理對話記憶時發生錯誤: {e}")
            result["errors"].append(str(e))

        return result

    def _merge_memories(self, keyword_memories: List[Dict], ai_memories: List[Dict]) -> List[Dict]:
        """合併關鍵字和AI提取的記憶，去除重複"""
        merged = []

        # 優先使用AI記憶（更準確），只有在沒有AI記憶時才使用關鍵字記憶
        if ai_memories:
            # 如果有AI記憶，使用AI記憶
            merged.extend(ai_memories)
            logger.debug(f"使用AI分析記憶，共 {len(ai_memories)} 條")
        elif keyword_memories:
            # 如果沒有AI記憶但有關鍵字記憶，使用關鍵字記憶
            merged.extend(keyword_memories)
            logger.debug(f"使用關鍵字提取記憶，共 {len(keyword_memories)} 條")

        return merged

    def _is_similar_memory(self, memory1: Dict, memory2: Dict) -> bool:
        """檢查兩個記憶是否相似"""
        # 簡單的相似度檢查：類型相同且內容相似
        if memory1["type"] != memory2["type"]:
            return False

        content1 = memory1["content"].lower()
        content2 = memory2["content"].lower()

        # 計算相似度（簡單的Jaccard相似度）
        words1 = set(content1.split())
        words2 = set(content2.split())

        if not words1 or not words2:
            return False

        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))

        similarity = intersection / union if union > 0 else 0

        return similarity > 0.6  # 相似度大於60%視為重複

    async def get_relevant_memories(
        self,
        user_id: str,
        current_message: str,
        max_memories: int = 5,
        context_tags: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """獲取與當前消息相關的記憶"""
        if not db_available:
            return []

        try:
            collected: List[Dict[str, Any]] = []
            seen_ids: set[str] = set()

            async def _consume_query(query: str) -> None:
                if not query:
                    return
                result = await search_memories(user_id, query, limit=max_memories)
                if result.get("success"):
                    for mem in result.get("memories", []):
                        mem_id = mem.get("memory_id") or mem.get("id")
                        if mem_id and mem_id not in seen_ids:
                            collected.append(mem)
                            seen_ids.add(mem_id)
                        if len(collected) >= max_memories:
                            return

            await _consume_query(current_message)
            if len(collected) < max_memories and context_tags:
                for tag in context_tags:
                    await _consume_query(tag)
                    if len(collected) >= max_memories:
                        break

            if collected:
                return collected[:max_memories]

            general_result = await get_user_memories(
                user_id=user_id,
                limit=max_memories,
                min_importance=0.6,
            )

            if general_result["success"]:
                return general_result["memories"]

        except Exception as e:
            logger.error(f"獲取相關記憶時發生錯誤: {e}")

        return []

    def format_memories_for_context(self, memories: List[Dict[str, Any]]) -> str:
        """將記憶格式化為上下文字符串"""
        if not memories:
            return ""

        context_parts = []
        for memory in memories:
            memory_type = memory.get("type", "general")
            content = memory.get("content", "")
            importance = memory.get("importance", 0.5)

            # 只包含重要性較高的記憶
            if importance >= 0.6:
                type_labels = {
                    "personal_info": "個人信息",
                    "preferences": "偏好",
                    "events": "事件",
                    "knowledge": "知識",
                    "goals": "目標"
                }

                type_label = type_labels.get(memory_type, memory_type)
                context_parts.append(f"[{type_label}] {content}")

        if context_parts:
            return "\n".join(context_parts)
        else:
            return ""


# 全局記憶管理器實例
memory_manager = MemoryManager()
