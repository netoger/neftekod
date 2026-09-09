"""Целевая переменная: содержание серы в гидроочищенном ДТ.

Иерархия источников качества задана ТЗ: **ЛИМС → ПАК → расчётные модели**.
Лабораторный результат — контрольный факт, поточный анализатор — оперативная
оценка, которая к тому же периодически выходит из строя.

Практически это значит:
* учим и валидируем модель на ПАК (189 тыс. точек на 10-минутной сетке),
  потому что редких лабораторных замеров на обучение не хватит;
* но там, где ЛИМС есть, он используется для проверки и калибровки ПАК —
  если анализатор врёт, мы должны это видеть, а не тихо учиться на его ошибке.
"""

from __future__ import annotations

import pandas as pd

# Ключи источников качества по сере
PAK_SULFUR = "PAK:24-2000:Mg.Sulfur"
LIMS_SULFUR = "LIMS:Гидроочистка:2:Mg.Sulfur"

# Предел спецификации по ТЗ
SULFUR_SPEC_MG_KG = 10.0
# Потолок шкалы анализатора: выше он просто не показывает
SULFUR_CEILING = 20.0


def sulfur_from_pak(pak: pd.DataFrame, index: pd.DatetimeIndex) -> pd.Series:
    """Ряд серы по поточному анализатору, выровненный на сетку телеметрии.

    Выравнивание — строго по времени (`reindex`), без интерполяции вперёд:
    выдумывать значение анализатора мы не имеем права.
    """
    series = (
        pak.loc[pak["key"] == PAK_SULFUR, ["ts", "value"]]
        .drop_duplicates(subset="ts")
        .set_index("ts")["value"]
        .sort_index()
    )
    return series.reindex(index).rename("sulfur_pak")


def sulfur_from_lims(lims: pd.DataFrame) -> pd.Series:
    """Редкий ряд лабораторных замеров серы (контрольный факт)."""
    series = (
        lims.loc[lims["key"] == LIMS_SULFUR, ["ts", "value"]]
        .drop_duplicates(subset="ts")
        .set_index("ts")["value"]
        .sort_index()
    )
    return series.rename("sulfur_lims")


def censored_mask(sulfur: pd.Series, ceiling: float = SULFUR_CEILING) -> pd.Series:
    """Точки, где анализатор упёрся в предел шкалы: значение «не менее ceiling»."""
    return sulfur >= ceiling


def make_target(
    sulfur: pd.Series,
    horizon_steps: int,
    *,
    drop_censored: bool = True,
) -> pd.DataFrame:
    """Целевая переменная со сдвигом вперёд на `horizon_steps` шагов сетки.

    Сдвиг вперёд — принципиальный момент: система должна предсказывать, каким
    качество СТАНЕТ, а не каким оно уже стало. Признаки при этом берутся только
    из прошлого, поэтому утечки из будущего не возникает.
    """
    future = sulfur.shift(-horizon_steps)
    frame = pd.DataFrame(
        {
            "sulfur_future": future,
            "over_spec_future": (future > SULFUR_SPEC_MG_KG).astype("float32"),
            "censored_future": censored_mask(future).astype("float32"),
        }
    )
    if drop_censored:
        # На потолке шкалы истинное значение неизвестно — как точную цель не используем
        frame.loc[frame["censored_future"] == 1, "sulfur_future"] = pd.NA
    return frame
