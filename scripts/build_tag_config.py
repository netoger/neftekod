"""Этап 2: аудит справочника тегов -> config/tags.yaml + reports/tag_audit.csv.

Запуск (после prepare_data.py):
    python scripts/build_tag_config.py

Что делает: по каждому тегу сводит описание из листа КИП, букву в имени и
фактические значения из телеметрии, помечает расхождения и мёртвые датчики.

config/tags.yaml после этого нужно ОТКРЫТЬ РУКАМИ и проставить роли:
    MV  — управляющее воздействие (то, чем система может двигать);
    DV  — возмущение (меряем, но не управляем: состав сырья, погода, загрузка);
    CV  — контролируемая переменная (то, что стараемся удержать).
Роль по описанию автоматически не выводится — это инженерное решение команды,
и его придётся защищать на демо.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import yaml  # noqa: E402

from neftekod.io import AVT, GO, read_interim  # noqa: E402
from neftekod.paths import CONFIG_DIR, REPORTS_DIR, ensure_dirs  # noqa: E402
from neftekod.tags import audit_tags  # noqa: E402

TAGS_YAML = CONFIG_DIR / "tags.yaml"


def main() -> None:
    ensure_dirs()

    telemetry = {
        AVT: read_interim("telemetry_avt"),
        GO: read_interim("telemetry_go"),
    }
    dictionary = read_interim("tag_dictionary")

    audit = audit_tags(telemetry, dictionary)

    audit_path = REPORTS_DIR / "tag_audit.csv"
    audit.to_csv(audit_path, index=False, encoding="utf-8-sig")
    print(f"Полный аудит: {audit_path}")

    _write_tags_yaml(audit)
    _print_summary(audit)


def _write_tags_yaml(audit) -> None:
    """Пишет config/tags.yaml, сохраняя уже проставленные вручную роли."""
    previous: dict = {}
    if TAGS_YAML.exists():
        with open(TAGS_YAML, encoding="utf-8") as fh:
            previous = yaml.safe_load(fh) or {}
        previous = previous.get("tags", {})

    tags = {}
    for row in audit.to_dict("records"):
        old = previous.get(row["full_tag"], {})
        tags[row["full_tag"]] = {
            "plant": row["plant"],
            "description": row["description"],
            # Величина по описанию — букве в имени не верим (см. src/neftekod/tags.py)
            "quantity": row["quantity_by_description"],
            # Роль заполняется вручную и при перегенерации не затирается
            "role": old.get("role", "unknown"),
            "trust": row["trust"],
            "flags": row["flags"],
            # Модельный диапазон: НЕ промышленный предел, а p05..p95 истории.
            # Это допущение эксперимента, оно обязано быть явным (см. README).
            "model_range": [round(float(row["p05"]), 3), round(float(row["p95"]), 3)],
        }

    document = {
        "_note": (
            "Сгенерировано scripts/build_tag_config.py. "
            "Поле role заполняется вручную и сохраняется при перегенерации. "
            "model_range — p05..p95 истории, это ДОПУЩЕНИЕ, а не паспортный предел."
        ),
        "tags": tags,
    }
    with open(TAGS_YAML, "w", encoding="utf-8") as fh:
        yaml.safe_dump(document, fh, allow_unicode=True, sort_keys=False, width=120)
    print(f"Конфиг тегов: {TAGS_YAML} ({len(tags)} тегов)")


def _print_summary(audit) -> None:
    suspicious = audit[audit["flags"] != ""]
    print(f"\nТегов всего: {len(audit)}, с претензиями: {len(suspicious)}")

    print("\n--- Буква имени против описания ---")
    mismatch = audit[audit["flags"].str.contains("буква говорит", na=False)]
    for row in mismatch.to_dict("records"):
        print(f"  {row['full_tag']:10s} {row['quantity_by_letter']:12s} -> "
              f"{row['quantity_by_description']:12s}  медиана={row['median']:.2f}  {row['description'][:45]}")

    print("\n--- Медиана вне физического диапазона (описание не сходится с данными) ---")
    impossible = audit[audit["flags"].str.contains("вне диапазона", na=False)]
    for row in impossible.to_dict("records"):
        print(f"  {row['full_tag']:10s} медиана={row['median']:10.2f}  "
              f"[{row['p05']:.1f} .. {row['p95']:.1f}]  {row['description'][:55]}")

    print("\n--- Мёртвые и залипшие датчики (топ-10 по доле маркера 307) ---")
    dead = audit.nlargest(10, "share_sentinel")
    for row in dead.to_dict("records"):
        if row["share_sentinel"] <= 0:
            continue
        print(f"  {row['full_tag']:10s} маркер в {row['share_sentinel']:6.2%}, "
              f"заморозка до {row['longest_frozen_steps']:6d} шагов  {row['description'][:40]}")

    print("\nДальше: открыть config/tags.yaml и проставить role для кандидатов в MV.")


if __name__ == "__main__":
    main()
