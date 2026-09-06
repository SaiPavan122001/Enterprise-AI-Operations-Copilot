import logging
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]

# Make the backend package importable regardless of where pytest is invoked.
sys.path.insert(0, str(BACKEND_DIR))

logging.getLogger().setLevel(logging.WARNING)
