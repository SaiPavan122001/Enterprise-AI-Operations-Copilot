"""Offline evaluation harness for the Enterprise AI Operations Copilot.

Importing this package puts ``backend/`` on ``sys.path`` (the backend uses
top-level imports such as ``from config import settings``) and loads ``.env``.
Nothing here modifies production code; the pipeline is only called.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")
load_dotenv(BACKEND_DIR / ".env")
