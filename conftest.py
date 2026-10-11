import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

# .env가 없을 때만 키 기본값을 둔다. .env가 있으면 건드리지 않는다.
if not Path(__file__).with_name(".env").exists():
    os.environ.setdefault("OPENAI_API_KEY", "test")
    os.environ.setdefault(
        "JWT_SECRET_KEY", "test-only-default-secret-at-least-32-characters"
    )
