"""One manual target-PC benchmark, not a timing-sensitive CI assertion.

Run at the final validation stage: uv run --directory api python -m tests.fixtures.statements.benchmark
"""

import json
from datetime import date
from time import perf_counter

from app.modules.documents import parse_statement
from app.modules.documents.validation import STATEMENT_LIMIT
from tests.fixtures.statements.cases import INN, account, payment, statement


def main() -> None:
    count = 5_000
    documents = [payment(str(index), "0.01") for index in range(count)]
    sections = [account(incoming="50.00", closing="10050.00")]
    available = STATEMENT_LIMIT - len(statement(sections, documents))
    padding, remainder = divmod(available, count)
    documents = [
        document.replace(
            "НазначениеПлатежа=", "НазначениеПлатежа=" + "x" * (padding + (index < remainder))
        )
        for index, document in enumerate(documents)
    ]
    content = statement(sections, documents)
    started = perf_counter()
    result = parse_statement(content, INN, as_of=date(2026, 4, 1))
    elapsed = perf_counter() - started
    if len(content) != STATEMENT_LIMIT or result.months[0].incoming_kopecks != 5_000:
        raise AssertionError("Benchmark fixture or parsed total is incorrect")
    print(
        json.dumps(
            {
                "bytes": len(content),
                "documents": result.payment_count,
                "parseSeconds": round(elapsed, 6),
                "targetSeconds": 1.0,
                "withinTarget": elapsed < 1.0,
                "completeMonths": len(result.complete_months),
            }
        )
    )
    if elapsed >= 1.0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
