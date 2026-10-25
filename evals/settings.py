"""Loads evals/config.yaml and exposes repo-relative paths."""

from functools import lru_cache
from pathlib import Path

import yaml

from evals import REPO_ROOT

CONFIG_PATH = REPO_ROOT / "evals" / "config.yaml"


@lru_cache(maxsize=1)
def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def repo_path(relative: str) -> Path:
    path = REPO_ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_thresholds() -> dict:
    with open(repo_path(load_config()["paths"]["thresholds"]), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["thresholds"]
