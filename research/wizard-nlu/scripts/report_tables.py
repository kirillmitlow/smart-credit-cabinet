"""Render Russian Markdown tables using only recorded CSVs; no new model decisions."""
import csv
from pathlib import Path

from common import ROOT, SLOTS


def read(name):
    with (ROOT / "results" / name).open() as f:
        return list(csv.DictReader(f))


def pct(value):
    return f"{float(value) * 100:.1f}%" if value not in (None, "") else "—"


def number(value):
    return f"{float(value):.3f}" if value not in (None, "") else "—"


def table(headers, rows):
    result = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    result.extend("| " + " | ".join(str(v) for v in row) + " |" for row in rows)
    return "\n".join(result)


def main():
    summary = read("summary.csv")
    measured = [r for r in summary if r["status"] == "ok"]
    measured.sort(key=lambda r: (float(r["coverage"]) if r["selective_accuracy_micro"] and float(r["selective_accuracy_micro"]) >= .95 else -1,
                                 float(r["accuracy_mean"])), reverse=True)
    lines = ["# Таблицы итогового замера", "", "Сформированы из сохранённых CSV без повторного инференса.", ""]
    lines += [table(["Кандидат", "Точность сред.", "macro-F1", "Точность подстановок", "Доля подстановок", "ECE", "p50 / p95, с", "RAM, МиБ", "Диск, МиБ", "Загрузка, с", "Лицензия"],
                    [[r["candidate"], pct(r["accuracy_mean"]), number(r["macro_f1_mean"]), pct(r["selective_accuracy_micro"]),
                      pct(r["coverage"]), number(r["ece_mean"]), f"{number(r['latency_p50_s'])} / {number(r['latency_p95_s'])}",
                      f"{float(r['peak_ram_mib']):.0f}", f"{float(r['disk_mib']):.0f}", number(r["load_seconds"]), r["license"]]
                     for r in measured]), ""]
    not_measured = [r for r in summary if r["status"] != "ok"]
    if not_measured:
        lines += ["Без итогового измерения: " + ", ".join(r["candidate"] for r in not_measured) + ". Причины — в status_dev.csv / status_test.csv.", ""]
    slots = [r for r in read("slot_metrics.csv") if r["split"] == "test"]
    lines += ["## Каждый слот", "", table(["Кандидат", "Слот", "Точность", "macro-F1", "Подстановки верны", "Доля", "ECE", "Порог", "Верных/всего"],
        [[r["candidate"], r["slot"], pct(r["accuracy"]), number(r["macro_f1"]), pct(r["selective_accuracy"]),
          pct(r["coverage"]), number(r["ece"]), number(r["threshold"]), f"{r['accepted_correct']}/{r['accepted']}"] for r in slots]), ""]
    lines += ["## Заказ и кассовый разрыв", "", table(["Кандидат", "На самом деле", "Выбран заказ", "Выбран разрыв", "Выбрано другое", "Ошибок среди подставленных"],
        [[r["candidate"], r["gold"], r["predicted_order"], r["predicted_gap"], r["predicted_other"], r["accepted_errors"]]
         for r in read("critical_confusion.csv")]), ""]
    lines += ["## Парсер суммы", "", table(["Набор", "Фраз", "Верно", "Точность", "Сумма названа", "Точность на названных суммах", "Лишних сумм"],
        [[r["split"], r["n"], r["correct"], pct(r["accuracy"]), r["stated_amount_n"], pct(r["stated_amount_accuracy"]), r["hallucinated_amount_n"]]
         for r in read("parser_summary.csv")]), ""]
    lines += ["## Неопределённость точности подстановок", "", "95%-й интервал Уилсона описывает неопределённость доли верных ответов. Он не учитывает зависимость шести слотов одной фразы и синтетическое происхождение данных, поэтому может быть слишком узким.", "",
              table(["Кандидат", "Верных/подставлено", "Доля", "Интервал"],
                    [[r["candidate"], f"{r['accepted_correct']}/{r['accepted']}", pct(r["coverage"]),
                      f"{pct(r['selective_wilson_low'])} – {pct(r['selective_wilson_high'])}"] for r in measured]), ""]
    (ROOT / "RESULT_TABLES.md").write_text("\n".join(lines))
    print("RESULT_TABLES.md written")


if __name__ == "__main__":
    main()
