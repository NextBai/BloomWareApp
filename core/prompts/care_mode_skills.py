import os
from pathlib import Path
from typing import List

CARE_SKILLS_ROOT = Path(__file__).resolve().parents[2] / "features" / "care_mode" / "skills"

def load_care_mode_skills() -> str:
    """
    載入並格式化情緒關懷模式的對話技巧 (Skills)
    """
    if not CARE_SKILLS_ROOT.exists():
        return ""
    
    skills_content = []
    skills_content.append("\n【情緒關懷對話技巧 (Care Mode Skills)】")
    skills_content.append("在關懷模式下，請靈活運用以下專業對話技巧來提升共鳴感：")
    
    try:
        # 獲取所有 .md 檔案
        skill_files = list(CARE_SKILLS_ROOT.glob("*.md"))
        
        for file_path in skill_files:
            content = file_path.read_text(encoding="utf-8")
            # 移除 Frontmatter (--- ... ---)
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    content = parts[2].strip()
            
            skills_content.append(f"\n--- {file_path.stem} ---\n{content}")
            
        return "\n".join(skills_content)
    except Exception as e:
        print(f"載入關懷模式技巧失敗: {e}")
        return ""

def get_care_mode_skills_block() -> str:
    """
    獲取用於 System Prompt 的技巧區塊
    """
    return load_care_mode_skills()
