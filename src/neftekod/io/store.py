"""Кэш разобранных данных в parquet.

Разбор сырья занимает десятки секунд (247 МБ CSV и два тяжёлых xlsx),
поэтому делаем это один раз скриптом prepare_data.py, а все агенты и
ноутбуки читают уже готовый parquet за доли секунды.
"""

from __future__ import annotations

import pandas as pd

from ..paths import INTERIM_DIR


def write_interim(frame: pd.DataFrame, name: str) -> None:
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(INTERIM_DIR / f"{name}.parquet", compression="zstd")


def read_interim(name: str) -> pd.DataFrame:
    path = INTERIM_DIR / f"{name}.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"Нет кэша {path}. Сначала выполни: python scripts/prepare_data.py"
        )
    return pd.read_parquet(path)
