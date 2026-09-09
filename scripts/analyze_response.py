"""Разведка отклика: какие теги двигают серу и с каким запаздыванием.

Запуск (после prepare_data.py и build_tag_config.py):
    python scripts/analyze_response.py

Зачем. Две задачи решаются одним расчётом:

1. **Выбор управляющих воздействий.** Имена тегов гидроочистки обезличены,
   описаниям в справочнике верить нельзя (аудит показал 38 % согласия против
   97 % на АВТ). Значит, кандидатов в MV ищем по данным: тег, изменение
   которого предшествует изменению серы, — кандидат; тег без связи — нет.

2. **Величина запаздывания.** Технологический параметр влияет на качество не
   мгновенно. Лаг, на котором связь максимальна, задаёт и горизонт прогноза,
   и глубину лаговых признаков.

Важно: считается корреляция «тег в прошлом -> сера сейчас». Обратное
направление (сера в прошлом -> тег сейчас) — это реакция ОПЕРАТОРА на анализ,
а не влияние параметра на качество, и её мы отдельно отмечаем, чтобы не
принять управляющее действие человека за физику процесса.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from neftekod.features.target import sulfur_from_pak  # noqa: E402
from neftekod.io import read_interim  # noqa: E402
from neftekod.paths import CONFIG_DIR, REPORTS_DIR, ensure_dirs  # noqa: E402
from neftekod.quality import apply, combine, detect_all  # noqa: E402

# Шаг сетки — 10 минут. Лаги: от 10 минут до 24 часов.
LAG_STEPS = [0, 1, 3, 6, 12, 18, 24, 36, 48, 72, 108, 144]


def main() -> None:
    ensure_dirs()

    with open(CONFIG_DIR / "tags.yaml", encoding="utf-8") as fh:
        tag_config = yaml.safe_load(fh)["tags"]

    telemetry = pd.concat(
        [read_interim("telemetry_avt"), read_interim("telemetry_go")], axis=1
    )
    print(f"Телеметрия: {telemetry.shape[1]} тегов, {len(telemetry)} точек")

    # 1. Чистим данные: показания мёртвых датчиков в корреляцию пускать нельзя
    quantities = {tag: cfg["quantity"] for tag, cfg in tag_config.items()}
    model_ranges = {tag: tuple(cfg["model_range"]) for tag, cfg in tag_config.items()}
    masks = detect_all(telemetry, quantities=quantities, model_ranges=model_ranges)
    bad = combine(masks)
    clean = apply(telemetry, bad)
    print(f"Помечено дефектными: {bad.to_numpy().mean():.2%} всех значений")

    # 2. Целевая переменная
    pak = read_interim("pak")
    sulfur = sulfur_from_pak(pak, telemetry.index)
    print(
        f"Сера ПАК: {sulfur.notna().sum()} точек, медиана {sulfur.median():.2f} мг/кг, "
        f"выше спецификации {(sulfur > 10).mean():.2%} времени"
    )

    # 3. Корреляция на сетке лагов
    rows = []
    for column in clean.columns:
        series = clean[column]
        if series.notna().sum() < 1000:
            continue
        best = {"full_tag": column, "best_lag_steps": None, "best_corr": 0.0}
        for lag in LAG_STEPS:
            value = series.shift(lag).corr(sulfur)
            if np.isfinite(value) and abs(value) > abs(best["best_corr"]):
                best.update(best_lag_steps=lag, best_corr=float(value))
        # Обратное направление: реагировал ли оператор на анализ
        reverse = max(
            (abs(series.corr(sulfur.shift(lag))) for lag in LAG_STEPS if lag),
            default=np.nan,
        )
        best["reverse_corr"] = float(reverse)
        best["direction"] = (
            "оператор реагирует" if reverse > abs(best["best_corr"]) else "параметр влияет"
        )
        best["description"] = tag_config.get(column, {}).get("description", "")
        best["trust"] = tag_config.get(column, {}).get("trust", "?")
        rows.append(best)

    report = pd.DataFrame(rows)
    report["abs_corr"] = report["best_corr"].abs()
    report = report.sort_values("abs_corr", ascending=False)

    path = REPORTS_DIR / "response_analysis.csv"
    report.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"\nОтчёт: {path}")

    print("\n--- Топ-20 связей с серой (лаг в шагах по 10 мин) ---")
    header = f"{'тег':10s} {'corr':>7s} {'лаг':>8s} {'направление':>18s}  описание"
    print(header)
    for row in report.head(20).to_dict("records"):
        hours = row["best_lag_steps"] / 6
        print(
            f"{row['full_tag']:10s} {row['best_corr']:+7.3f} {hours:6.1f} ч "
            f"{row['direction']:>18s}  {row['description'][:42]}"
        )

    print("\n--- Распределение лучших лагов ---")
    print((report["best_lag_steps"] / 6).describe().round(2).to_string())


if __name__ == "__main__":
    main()
