"""Загрузка сырых файлов пакета в единый формат.

Договорённости, на которых стоит вся дальнейшая работа:

* Телеметрия — «широкая» таблица: индекс `ts` (10-минутная сетка), колонки
  вида `AVT:T33`, `GO:F15`. Префикс установки обязателен: короткие имена тегов
  в двух файлах совпадают (`T6` есть и там, и там), без префикса они склеятся.
* ЛИМС и ПАК — «длинные» таблицы: одна строка = один замер
  (`ts`, `key`, `value`, `unit_meas`, ...). Они редкие и асинхронные,
  раскладывать их в широкую сетку на этом этапе нельзя — потеряем возраст замера.
"""

from __future__ import annotations

import re

import pandas as pd

from ..paths import raw_file
from .excel import read_paired_sheet

# Коды установок, которыми префиксуются теги телеметрии
AVT = "AVT"  # ЭЛОУ-АВТ-6, атмосферно-вакуумная трубчатка
GO = "GO"    # установка 24-2000, гидроочистка + стабилизация

_TELEMETRY_FILES = {AVT: "telemetry_avt", GO: "telemetry_go"}

# «Установка 'Гидроочистка'.. Точка отбора '2'. Продукт 'Дизельное топливо'»
_BLOCK_RE = re.compile(
    r"Установка\s*'(?P<unit>[^']*)'\.*\s*"
    r"Точка отбора\s*'(?P<point>[^']*)'\.*\s*"
    r"Продукт\s*'(?P<product>[^']*)'"
)


def load_telemetry(unit: str) -> pd.DataFrame:
    """Телеметрия одной установки: широкая таблица с индексом `ts`."""
    if unit not in _TELEMETRY_FILES:
        raise ValueError(f"Неизвестная установка {unit!r}, ожидалось {list(_TELEMETRY_FILES)}")

    frame = pd.read_csv(raw_file(_TELEMETRY_FILES[unit]), parse_dates=["date"])
    # «Unnamed: 0», «Unnamed: 0.1» — служебные индексы выгрузки, смысла не несут
    frame = frame.drop(columns=[c for c in frame.columns if c.startswith("Unnamed")])
    frame = frame.rename(columns={"date": "ts"}).set_index("ts").sort_index()
    frame.columns = [f"{unit}:{c}" for c in frame.columns]
    return frame.astype("float32")


def load_lims() -> pd.DataFrame:
    """Лабораторные анализы в длинном формате.

    Структура листа: строка 0 — блок «установка / точка отбора / продукт»,
    строка 1 — показатель, строка 2 — единица измерения,
    строка 3 — «Количество значений», данные с строки 4.
    """
    long = read_paired_sheet(
        raw_file("lims"),
        block_row=0,
        label_row=1,
        unit_row=2,
        data_start_row=4,
    )

    parsed = long["block"].fillna("").apply(_parse_block)
    long["plant"] = [p[0] for p in parsed]
    long["point"] = [p[1] for p in parsed]
    long["product"] = [p[2] for p in parsed]
    long["source"] = "LIMS"
    long["key"] = (
        "LIMS:" + long["plant"] + ":" + long["point"].astype(str) + ":" + long["param"]
    )
    return long[
        ["ts", "source", "key", "plant", "point", "product", "param", "unit_meas", "value"]
    ].reset_index(drop=True)


def load_pak() -> pd.DataFrame:
    """Поточные анализаторы в длинном формате.

    Структура листа: строка 0 — имя тега («24-2000:Mg.Sulfur»),
    строка 1 — единица измерения, данные с строки 2.
    """
    long = read_paired_sheet(raw_file("pak"), label_row=0, unit_row=1, data_start_row=2)
    long["source"] = "PAK"
    long["key"] = "PAK:" + long["param"]
    return long[["ts", "source", "key", "param", "unit_meas", "value"]].reset_index(drop=True)


def load_tag_dictionary() -> pd.DataFrame:
    """Лист КИП справочника: тег -> описание, по обеим установкам."""
    frame = pd.read_excel(raw_file("tags"), sheet_name="КИП")
    columns = list(frame.columns)

    rows = []
    # Лист устроен парами колонок: «<установка> (описание)» и «<установка>»
    for descr_col, tag_col, plant in (
        (columns[0], columns[1], AVT),
        (columns[2], columns[3], GO),
    ):
        part = frame[[descr_col, tag_col]].dropna(subset=[tag_col])
        for description, tag in part.itertuples(index=False):
            rows.append(
                {
                    "plant": plant,
                    "tag": str(tag).strip(),
                    "full_tag": f"{plant}:{str(tag).strip()}",
                    "description": str(description).strip(),
                }
            )
    return pd.DataFrame(rows)


def load_vak_formulas() -> pd.DataFrame:
    """Лист ВАК: готовые формулы виртуальных анализаторов «имя -> выражение»."""
    frame = pd.read_excel(raw_file("tags"), sheet_name="ВАК", header=None)

    rows = []
    # Блоки идут парами колонок: слева имя показателя, справа формула
    for col in range(0, frame.shape[1] - 1, 2):
        block = frame.iloc[0, col]
        for name, formula in frame.iloc[1:, [col, col + 1]].dropna().itertuples(index=False):
            rows.append(
                {
                    "block": None if pd.isna(block) else str(block).strip(),
                    "name": str(name).strip(),
                    "formula": str(formula).strip(),
                }
            )
    return pd.DataFrame(rows)


def _parse_block(text: str) -> tuple[str, str, str]:
    match = _BLOCK_RE.search(text)
    if not match:
        return ("?", "?", "?")
    return (match["unit"], match["point"], match["product"])
