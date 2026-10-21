"""Meaningful protocol/metric/parser checks, without loading held-out texts."""
import argparse
import hashlib
import json

import numpy as np

from amount_parser import parse_amount
from common import ROOT, SLOTS, read_data, write_csv
from metrics import choose_threshold, reliability, wilson

PARSER_CASES = [
    ("Нужно 1,5 млн", 1500000), ("Нужно 500 тыс", 500000),
    ("Нужно полтора миллиона", 1500000), ("Нужно 300к", 300000), ("Нужно 2 ляма", 2000000),
    ("Нужно 1.25 млн рублей", 1250000), ("Прошу 1 500 000 рублей", 1500000),
    ("Нужно 1\u00a0500\u00a0000 ₽", 1500000), ("Прошу 250 000 руб.", 250000),
    ("Хочу 50тыс.", 50000), ("Нужно 300K", 300000), ("Две тысячи рублей", 2000),
    ("Нужно три миллиона", 3000000), ("Нужно полторы тысячи", 1500),
    ("Нужно пять миллионов рублей", 5000000), ("Нужно 0,5 млн", 500000),
    ("Нужно примерно 700 тысяч", 700000), ("Нужно около 2 млн руб", 2000000),
    ("Прошу 1 рубль", 1), ("Кредит 100000 рублей", 100000),
    ("Нужны деньги на печь", None), ("Оплата через 2 месяца", None),
    ("Госконтракт по 44-ФЗ", None), ("Номер заказа 500", None),
    ("Нужно 1-2 млн", None), ("Нужно от 500 тыс до 1 млн", None),
    ("Нужно 300 или 500 тыс", None), ("Нужно 500 тыс и 1 млн", None),
    ("Нужно 500 тысяч евро", None), ("Нужно 500 USD", None),
    ("Нужно 2 млн долларов", None), ("Нужно -100 рублей", None),
    ("Нужно 0 рублей", None), ("Оборот 2 млн, нужно 500 тыс", 500000),
    ("Станок стоит 3 млн, прошу 1,5 млн", 1500000), ("Выручка 500 тыс в месяц", None),
    ("Нужны не 500 тыс, а 300 тыс", 300000), ("Нужно 500 тыс. Ещё раз: 500 тыс", 500000),
    ("Нужно 2 лямов на закупку", 2000000), ("Надо 200 тыщ", 200000),
    ("Нужно 1\u202f200\u202f000 рублей", 1200000), ("Нужно 1200,50 рублей", None),
    ("Нужно 1200.00 рублей", 1200), ("Нужно 3,75 миллиона", 3750000),
    ("Контракт 223, оплата через 90 дней", None), ("Нужно 2 миллиона или 3 миллиона", None),
    ("Цена 800 тыс, сумма кредита пока неизвестна", None), ("Нужно десять тысяч", 10000),
    ("Могу заложить машину за 500 тыс", None), ("Закупка 400 тысяч, кредит 200 тысяч", 200000),
]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--split", choices=["dev", "test", "human"])
    args = p.parse_args()
    if args.split:
        rows = read_data(args.split)
        records = []
        import time
        for r in rows:
            start = time.perf_counter()
            predicted = parse_amount(r["text"])
            elapsed = time.perf_counter() - start
            records.append(dict(id=r["id"], text=r["text"], gold=r["labels"]["amount_rub"],
                                predicted=predicted, correct=predicted == r["labels"]["amount_rub"], seconds=elapsed))
        if records:
            write_csv(ROOT / "results" / f"amount_{args.split}.csv", records)
        print(args.split, len(records), sum(r["correct"] for r in records))
        return
    # Verify integrity of test bytes, but do not parse or inspect its contents here.
    manifest = json.loads((ROOT / "dataset/manifest.json").read_text())
    for file, item in manifest.items():
        assert hashlib.sha256((ROOT / "dataset" / file).read_bytes()).hexdigest() == item["sha256"]
    rows = read_data("dev") + read_data("examples")
    assert len(set(r["text"] for r in rows)) == len(rows)
    assert len(read_data("dev")) == 60 and len(read_data("examples")) == 42
    assert all(len({r["labels"][s] for r in read_data("examples")}) >= 3 for s in SLOTS)
    probs = np.array([[.97, .02, .01], [.96, .03, .01], [.1, .1, .8], [.3, .6, .1], [.96, .03, .01]])
    y = np.array([0, 0, 2, 0, 0])
    threshold = choose_threshold(probs, y, "frequency", min_count=3)
    assert threshold["dev_accepted"] == 3  # UNKNOWN never counts as an autofilled answer.
    assert threshold["threshold"] >= .96
    assert sum(b["n"] for b in reliability(probs, y)) == 5
    assert wilson(0, 0) == (None, None)
    assert wilson(5, 5)[0] < .95  # Five successes are not proof of 95% population precision.
    cases = []
    for text, expected in PARSER_CASES:
        value = parse_amount(text)
        cases.append(dict(text=text, gold=expected, predicted=value, correct=value == expected))
    write_csv(ROOT / "results/amount_cases.csv", cases)
    (ROOT / "dataset/parser_cases.jsonl").write_text("".join(json.dumps({"text": t, "amount_rub": v}, ensure_ascii=False) + "\n" for t, v in PARSER_CASES))
    print("Protocol and metric checks passed. Parser cases:", sum(c["correct"] for c in cases), "/", len(cases))
    for c in cases:
        if not c["correct"]:
            print("PARSER ERROR", c)


if __name__ == "__main__":
    main()
