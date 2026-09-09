"""Детекторы дефектов телеметрии.

В выгрузке нет ни одного пропуска: все дефекты замаскированы под нормальные
числа. Значит, «пропуски» надо сначала найти самим, иначе модель обучится на
показаниях мёртвых датчиков.

Что ищем (всё найдено при разведке данных, см. PLAN.md, раздел 2.5):

* **sentinel** — значение ровно 307.0. Встречается в физически несовместимых
  тегах (плотность нефти, расходы, температуры) и без единого разброса.
  Трактуем как «датчик отдал константу-заглушку».
* **frozen** — значение не меняется много шагов подряд. Реальный аналоговый
  сигнал всегда шумит хотя бы в последнем знаке.
* **impossible** — отрицательный расход, отрицательный уровень: физика запрещает.
* **clipped** — сигнал упёрся в предел шкалы прибора (у анализатора серы это
  ровно 20.0). Значение не ложное, но цензурированное: «не менее 20».
* **out_of_range** — далеко за модельным диапазоном тега из config/tags.yaml.

Каждый детектор возвращает булеву маску той же формы, что и данные, — маски
складываются, и уже по ним считается доверие к данным в конкретный момент.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Типы дефектов в порядке убывания тяжести
ISSUE_TYPES = ("sentinel", "frozen", "impossible", "out_of_range", "clipped")

# Величины, для которых отрицательное значение физически невозможно
NON_NEGATIVE_QUANTITIES = {"flow", "mass_flow", "level", "density", "quality"}


def run_lengths(values: np.ndarray) -> np.ndarray:
    """Для каждой точки — длина серии одинаковых подряд идущих значений."""
    size = values.size
    if size == 0:
        return np.empty(0, dtype=np.int64)
    changed = np.empty(size, dtype=bool)
    changed[0] = True
    changed[1:] = values[1:] != values[:-1]
    starts = np.flatnonzero(changed)
    lengths = np.diff(np.append(starts, size))
    return np.repeat(lengths, lengths)


def detect_sentinel(frame: pd.DataFrame, sentinel: float) -> pd.DataFrame:
    return frame.eq(sentinel)


def detect_frozen(frame: pd.DataFrame, min_steps: int) -> pd.DataFrame:
    mask = pd.DataFrame(False, index=frame.index, columns=frame.columns)
    for column in frame.columns:
        mask[column] = run_lengths(frame[column].to_numpy()) >= min_steps
    return mask


def detect_impossible(frame: pd.DataFrame, quantities: dict[str, str]) -> pd.DataFrame:
    mask = pd.DataFrame(False, index=frame.index, columns=frame.columns)
    for column in frame.columns:
        if quantities.get(column) in NON_NEGATIVE_QUANTITIES:
            mask[column] = frame[column] < 0
    return mask


def detect_clipped(frame: pd.DataFrame, ceilings: dict[str, float]) -> pd.DataFrame:
    """Упор в предел шкалы прибора. Считаем по фактическому максимуму тега."""
    mask = pd.DataFrame(False, index=frame.index, columns=frame.columns)
    for column, ceiling in ceilings.items():
        if column in frame.columns:
            mask[column] = frame[column] >= ceiling
    return mask


def detect_out_of_range(
    frame: pd.DataFrame,
    model_ranges: dict[str, tuple[float, float]],
    margin: float = 0.25,
) -> pd.DataFrame:
    """Выход далеко за модельный диапазон.

    Диапазон p05..p95 сам по себе накрывает лишь 90 % истории, поэтому границы
    расширяются на `margin` от ширины диапазона — иначе бы каждая десятая точка
    считалась дефектной.
    """
    mask = pd.DataFrame(False, index=frame.index, columns=frame.columns)
    for column, (low, high) in model_ranges.items():
        if column not in frame.columns or not np.isfinite([low, high]).all():
            continue
        width = high - low
        mask[column] = (frame[column] < low - margin * width) | (
            frame[column] > high + margin * width
        )
    return mask


def detect_all(
    frame: pd.DataFrame,
    *,
    quantities: dict[str, str],
    model_ranges: dict[str, tuple[float, float]],
    sentinel: float = 307.0,
    min_frozen_steps: int = 6,
    ceilings: dict[str, float] | None = None,
) -> dict[str, pd.DataFrame]:
    """Все детекторы разом: {тип дефекта -> булева маска}."""
    return {
        "sentinel": detect_sentinel(frame, sentinel),
        "frozen": detect_frozen(frame, min_frozen_steps),
        "impossible": detect_impossible(frame, quantities),
        "out_of_range": detect_out_of_range(frame, model_ranges),
        "clipped": detect_clipped(frame, ceilings or {}),
    }


def combine(masks: dict[str, pd.DataFrame], exclude: tuple[str, ...] = ("clipped",)) -> pd.DataFrame:
    """Сводит маски в одну «значению верить нельзя».

    Клиппинг по умолчанию не исключается: значение цензурировано, но всё ещё
    информативно («не менее предела шкалы»), выбрасывать его нельзя.
    """
    combined = None
    for name, mask in masks.items():
        if name in exclude:
            continue
        combined = mask if combined is None else (combined | mask)
    return combined


def apply(frame: pd.DataFrame, bad: pd.DataFrame) -> pd.DataFrame:
    """Помечает дефектные значения как пропуски — дальше их можно честно
    интерполировать или оставить NaN, но они больше не притворяются данными."""
    return frame.mask(bad)


def issue_report(masks: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Сводка «сколько какого дефекта в каком теге», для отчёта и дашборда."""
    rows = []
    any_mask = next(iter(masks.values()))
    total = len(any_mask)
    for column in any_mask.columns:
        row = {"full_tag": column}
        for name, mask in masks.items():
            row[name] = float(mask[column].mean())
        row["bad_total"] = float(combine(masks)[column].mean())
        rows.append(row)
    report = pd.DataFrame(rows).sort_values("bad_total", ascending=False)
    report.attrs["n_points"] = total
    return report
