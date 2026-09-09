"""Этап 1: сырые файлы организаторов -> parquet-кэш.

Запуск (из корня репозитория):
    python scripts/prepare_data.py

Скрипт ничего не «чинит» и не фильтрует: его задача — только привести четыре
источника к общему формату и один раз заплатить за разбор xlsx и 247 МБ CSV.
Поиск аномалий и заполнение пропусков — отдельный этап, чтобы всегда можно
было вернуться к тому, что реально было в выгрузке.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from neftekod.io import (  # noqa: E402
    AVT,
    GO,
    load_lims,
    load_pak,
    load_tag_dictionary,
    load_telemetry,
    load_vak_formulas,
    write_interim,
)
from neftekod.paths import INTERIM_DIR, ensure_dirs, raw_dir  # noqa: E402


def _step(title: str):
    print(f"\n>>> {title}", flush=True)
    return time.perf_counter()


def main() -> None:
    ensure_dirs()
    print(f"Сырые данные: {raw_dir()}")
    print(f"Кэш:          {INTERIM_DIR}")

    for plant in (AVT, GO):
        started = _step(f"Телеметрия {plant}")
        frame = load_telemetry(plant)
        write_interim(frame, f"telemetry_{plant.lower()}")
        print(
            f"    тегов: {frame.shape[1]}, точек: {len(frame)}, "
            f"период: {frame.index.min()} .. {frame.index.max()}"
        )
        step = frame.index.to_series().diff().dropna().value_counts()
        print(f"    шаг сетки: {dict(list(step.items())[:3])}")
        print(f"    {time.perf_counter() - started:.1f} с")

    started = _step("ЛИМС")
    lims = load_lims()
    write_interim(lims, "lims")
    print(f"    замеров: {len(lims)}, показателей: {lims['key'].nunique()}")
    print(f"    период: {lims['ts'].min()} .. {lims['ts'].max()}")
    print(f"    {time.perf_counter() - started:.1f} с")

    started = _step("ПАК")
    pak = load_pak()
    write_interim(pak, "pak")
    for key, part in pak.groupby("key"):
        print(
            f"    {key:28s} n={len(part):7d}  {part['ts'].min()} .. {part['ts'].max()}"
            f"  [{part['unit_meas'].iloc[0]}]"
        )
    print(f"    {time.perf_counter() - started:.1f} с")

    started = _step("Справочники")
    tags = load_tag_dictionary()
    write_interim(tags, "tag_dictionary")
    vak = load_vak_formulas()
    write_interim(vak, "vak_formulas")
    print(f"    тегов в КИП: {len(tags)}, формул ВАК: {len(vak)}")
    print(f"    {time.perf_counter() - started:.1f} с")

    print("\nГотово. Дальше: python scripts/build_tag_config.py")


if __name__ == "__main__":
    main()
