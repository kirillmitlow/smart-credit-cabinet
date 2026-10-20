"""Conservative Russian amount parser. No model, network, or product decision."""
import re
from decimal import Decimal

NUMBER_WORDS = {"один": "1", "одна": "1", "одну": "1", "два": "2", "две": "2", "три": "3",
                "четыре": "4", "пять": "5", "шесть": "6", "семь": "7", "восемь": "8",
                "девять": "9", "десять": "10", "полтора": "1.5", "полторы": "1.5",
                "половина": "0.5"}
UNIT = r"(?:миллион(?:а|ов)?|млн\.?|лям(?:а|ов)?|тысяч(?:а|и|у)?|тыс\.?|тыщ|к|k|руб(?:лей|ля|ль|\.)?|₽)"
AMOUNT = re.compile(r"(?<![\w.,])(?P<number>\d+(?:[ \u00a0\u202f]\d{3})*(?:[.,]\d+)?)\s*(?P<unit>" + UNIT + r")(?!\w)", re.I)


def parse_amount(text):
    t = text.lower().replace("ё", "е").replace("−", "-").replace("–", "-").replace("—", "-")
    for word, number in NUMBER_WORDS.items():
        t = re.sub(r"\b" + word + r"\b", number, t)
    # Ranges are intentionally not collapsed into a guessed point estimate.
    if re.search(r"\d[\d .,]*\s*(?:-|до|или)\s*\d", t):
        return None
    candidates = []
    for m in AMOUNT.finditer(t):
        before, after = t[max(0, m.start() - 65):m.start()], t[m.end():m.end() + 30]
        if m.start() and t[m.start() - 1] == "-":
            continue
        if re.match(r"\s*(?:евро|доллар|usd|eur|\$)", after):
            continue
        # Do not treat an explicitly negated amount as the desired amount.
        if re.search(r"\bне\s*$", before):
            continue
        n = Decimal(m.group("number").replace(" ", "").replace("\u00a0", "").replace("\u202f", "").replace(",", "."))
        unit = m.group("unit")
        multiplier = 1000000 if unit.startswith(("миллион", "млн", "лям")) else 1000 if unit.startswith(("тыс", "тыщ", "к", "k")) else 1
        value = n * multiplier
        if value <= 0 or value != value.to_integral_value():
            continue
        # Prefer an explicit borrowing request to turnover, revenue, or asset price.
        segment = re.split(r"[,;.!?]", before)[-1]
        explicit = bool(re.search(r"(?:нуж\w*|прошу|хочу|не хватает|занять|займ|заем|кредит\w*)\b", segment))
        background = bool(re.search(r"(?:оборот|выручка|стоит|стоимость|цена|прибыль|остаток|заложить)\b", segment)) and not explicit
        if not background:
            candidates.append((int(value), explicit))
    explicit = {v for v, is_explicit in candidates if is_explicit}
    values = explicit or {v for v, _ in candidates}
    return next(iter(values)) if len(values) == 1 else None


if __name__ == "__main__":
    import sys
    print(parse_amount(" ".join(sys.argv[1:])))
