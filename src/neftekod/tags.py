"""Аудит справочника тегов.

Организаторы прямо предупредили: «смысл тега берите из справочника, не делайте
вывод по букве в коротком имени». Разведка это подтвердила — часть описаний
не сходится с физикой сигнала. Поэтому мы не доверяем ни букве, ни описанию
по отдельности, а сводим три источника и помечаем расхождения:

1. буква в имени тега (T/F/P/L/D/W/Q);
2. описание из листа КИП;
3. фактический диапазон значений в телеметрии.

Результат — таблица «тег -> величина -> верю/не верю», на которую опирается
выбор признаков и управляющих воздействий.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

# Что означает первая буква короткого имени тега (соглашение КИПиА)
LETTER_QUANTITY = {
    "T": "temperature",
    "F": "flow",
    "P": "pressure",
    "L": "level",
    "D": "density",
    "W": "mass_flow",
    "Q": "quality",
}

# Как узнать величину по описанию. Порядок важен: правила проверяются сверху вниз,
# первое сработавшее выигрывает.
_DESCRIPTION_RULES: list[tuple[str, str]] = [
    (r"поточн\w* анализатор|качеств\w* продукц|содержани\w+ серы", "quality"),
    (r"перепад давлени|вакуум|давлени", "pressure"),
    (r"массов\w+ расход", "mass_flow"),
    (r"плотност", "density"),
    (r"уровен", "level"),
    (r"температур", "temperature"),
    (r"расход|переток|производительност|орошени", "flow"),
]

# Ожидаемые физические диапазоны — грубый фильтр «похоже ли это вообще на величину»
PLAUSIBLE_RANGE = {
    "temperature": (-50.0, 600.0),
    "pressure": (-2.0, 100.0),
    "level": (0.0, 100.0),
    "density": (600.0, 1100.0),
    "quality": (0.0, 100.0),
}

# Значение-маркер залипшего датчика: встречается точно, без разброса,
# в обеих установках и в физически несовместимых тегах.
SENTINEL_VALUE = 307.0


def quantity_from_description(description: str) -> str:
    text = (description or "").lower()
    for pattern, quantity in _DESCRIPTION_RULES:
        if re.search(pattern, text):
            return quantity
    return "unknown"


def quantity_from_letter(tag: str) -> str:
    return LETTER_QUANTITY.get(tag[:1].upper(), "unknown")


def _longest_constant_run(values: np.ndarray) -> int:
    """Длина самого длинного участка, где значение не менялось (заморозка датчика)."""
    if values.size == 0:
        return 0
    changed = np.empty(values.size, dtype=bool)
    changed[0] = True
    changed[1:] = values[1:] != values[:-1]
    starts = np.flatnonzero(changed)
    lengths = np.diff(np.append(starts, values.size))
    return int(lengths.max())


def audit_tags(telemetry: dict[str, pd.DataFrame], dictionary: pd.DataFrame) -> pd.DataFrame:
    """Сводит описание, букву и фактические значения в одну таблицу.

    telemetry: {'AVT': df, 'GO': df} — широкие таблицы телеметрии.
    dictionary: результат load_tag_dictionary().
    """
    described = dictionary.set_index("full_tag")["description"].to_dict()

    rows = []
    for plant, frame in telemetry.items():
        for column in frame.columns:
            tag = column.split(":", 1)[1]
            values = frame[column].to_numpy(dtype="float64")
            finite = values[np.isfinite(values)]
            description = described.get(column, "")

            by_description = quantity_from_description(description)
            by_letter = quantity_from_letter(tag)
            percentiles = np.percentile(finite, [1, 5, 25, 50, 75, 95, 99]) if finite.size else [np.nan] * 7

            row = {
                "full_tag": column,
                "plant": plant,
                "tag": tag,
                "description": description,
                "quantity_by_description": by_description,
                "quantity_by_letter": by_letter,
                "n": int(finite.size),
                "min": float(finite.min()) if finite.size else np.nan,
                "p01": percentiles[0],
                "p05": percentiles[1],
                "p25": percentiles[2],
                "median": percentiles[3],
                "p75": percentiles[4],
                "p95": percentiles[5],
                "p99": percentiles[6],
                "max": float(finite.max()) if finite.size else np.nan,
                "n_unique": int(np.unique(finite).size),
                "share_sentinel": float(np.mean(finite == SENTINEL_VALUE)) if finite.size else np.nan,
                "share_zero": float(np.mean(finite == 0.0)) if finite.size else np.nan,
                "share_negative": float(np.mean(finite < 0.0)) if finite.size else np.nan,
                "longest_frozen_steps": _longest_constant_run(values),
            }
            row["flags"] = _flags(row)
            row["trust"] = "no" if row["flags"] else "yes"
            rows.append(row)

    return pd.DataFrame(rows)


def _flags(row: dict) -> str:
    """Человекочитаемый список претензий к тегу (через «;»)."""
    problems = []

    by_description = row["quantity_by_description"]
    by_letter = row["quantity_by_letter"]
    if by_description == "unknown":
        problems.append("описание не распознано")
    elif by_description != by_letter and not {by_description, by_letter} <= {"flow", "mass_flow"}:
        problems.append(f"буква говорит {by_letter}, описание — {by_description}")

    low, high = PLAUSIBLE_RANGE.get(by_description, (-np.inf, np.inf))
    if np.isfinite(row["median"]) and not (low <= row["median"] <= high):
        problems.append(f"медиана {row['median']:.1f} вне диапазона для {by_description}")

    if row["share_sentinel"] and row["share_sentinel"] > 0.001:
        problems.append(f"маркер {SENTINEL_VALUE:g} в {row['share_sentinel']:.1%} точек")
    if row["share_negative"] and row["share_negative"] > 0.001 and by_description in {"flow", "mass_flow", "level"}:
        problems.append(f"отрицательные значения в {row['share_negative']:.1%} точек")
    # Один день на 10-минутной сетке = 144 шага
    if row["longest_frozen_steps"] >= 144:
        problems.append(f"заморозка до {row['longest_frozen_steps']} шагов подряд")

    return "; ".join(problems)
