import sys
from pathlib import Path

# 確保專案根目錄在 sys.path，便於 tests 直接 import 本地模組
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

