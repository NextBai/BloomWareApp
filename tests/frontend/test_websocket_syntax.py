import os
import subprocess
from pathlib import Path


def test_websocket_js_has_no_syntax_errors():
    root = Path(__file__).resolve().parents[2]
    js_path = root / "static" / "frontend" / "js" / "websocket.js"

    result = subprocess.run(
        ["node", "--check", str(js_path)],
        capture_output=True,
        text=True,
        env=os.environ,
    )

    assert result.returncode == 0, (
        f"websocket.js has syntax errors: {result.stderr.strip() or result.stdout.strip()}"
    )
