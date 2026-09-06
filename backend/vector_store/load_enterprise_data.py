"""Deprecated: use the canonical seed command instead.

    python -m scripts.seed

Kept as a thin wrapper so existing commands keep working.
"""

from scripts.seed import seed

if __name__ == "__main__":
    seed()
