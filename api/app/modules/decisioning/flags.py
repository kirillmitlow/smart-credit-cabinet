"""Флаги (30-04): подозрение или нехватка данных → `MANUAL_REVIEW`. ЗАГЛУШКА.

Флаги `MASS_REGISTRATION`, `OVERDUE_30_89` (T-290) и `DATA_MISMATCH`, `TURNOVER_ANOMALY`
(T-288, антифрод) в эту поставку не входят. Маршрут уже принимает список флагов на входе
(T-296), поэтому подключение — это реализация `evaluate_flags` без правки остальных модулей.
`SOURCE_UNAVAILABLE` формирует `eligibility.unavailable_sources`.

TODO(T-288, T-290): реализовать четыре флага по 30-04 и 30-02 (сверка источников, накачка,
транзит, один плательщик, массовость, просрочка 30–89 дней).
"""

from __future__ import annotations

from app.modules.decisioning.types import DecisionInput, Features, ReasonCode


def evaluate_flags(inp: DecisionInput, feats: Features) -> tuple[ReasonCode, ...]:
    """Пока флагов нет: см. TODO(T-288, T-290) в докстринге модуля."""
    del inp, feats
    return ()
