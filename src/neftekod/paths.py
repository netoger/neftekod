"""Единая точка правды про пути.

Сырые файлы организаторов лежат вне репозитория (они большие и их нельзя
коммитить), поэтому путь к ним берётся из config/paths.yaml или из переменной
окружения NEFTEKOD_DATA — так у каждого в команде может быть свой каталог.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

# src/neftekod/paths.py -> src/neftekod -> src -> корень репозитория
REPO_ROOT = Path(__file__).resolve().parents[2]

CONFIG_DIR = REPO_ROOT / "config"
DATA_DIR = REPO_ROOT / "data"
INTERIM_DIR = DATA_DIR / "interim"      # parquet-кэш после разбора сырья
PROCESSED_DIR = DATA_DIR / "processed"  # витрины признаков
MODELS_DIR = REPO_ROOT / "models"
LOGS_DIR = REPO_ROOT / "logs"
REPORTS_DIR = REPO_ROOT / "reports"


@lru_cache(maxsize=1)
def _paths_config() -> dict:
    with open(CONFIG_DIR / "paths.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@lru_cache(maxsize=1)
def raw_dir() -> Path:
    """Каталог с выданным пакетом данных."""
    env = os.environ.get("NEFTEKOD_DATA")
    if env:
        return Path(env).expanduser().resolve()
    return (REPO_ROOT / _paths_config()["raw_dir"]).resolve()


def raw_file(key: str) -> Path:
    """Путь к конкретному файлу пакета по ключу из config/paths.yaml."""
    rel = _paths_config()["files"][key]
    path = raw_dir() / rel
    if not path.exists():
        raise FileNotFoundError(
            f"Не найден файл '{key}': {path}\n"
            f"Проверь raw_dir в config/paths.yaml или переменную NEFTEKOD_DATA."
        )
    return path


def ensure_dirs() -> None:
    """Создаёт служебные каталоги репозитория, если их ещё нет."""
    for path in (INTERIM_DIR, PROCESSED_DIR, MODELS_DIR, LOGS_DIR, REPORTS_DIR):
        path.mkdir(parents=True, exist_ok=True)
