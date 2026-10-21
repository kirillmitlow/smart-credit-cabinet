"""Правила вызовов по системам: таймауты, число попыток, бюджет времени (50-08, раздел «Правила»).

Значения из спецификации моков 9.2. Множитель `INTEGRATION_TIMEOUT_SCALE` растягивает таймауты
и бюджет на слабом ПК; паузы между повторами он не меняет.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.modules.integrations.results import System


@dataclass(frozen=True, slots=True)
class CallPolicy:
    system: System
    # Таймаут одной попытки, секунды (до множителя)
    timeout_s: float
    # Всего попыток: 1 + число повторов
    attempts: int
    # Сумма всех попыток и пауз одного вызова не больше этого («таймаут шага конвейера»), секунды
    budget_s: float
    # Статусы, после которых повторяем. Отчёт БКИ повторяем только после 503 (и обрыва)
    retry_statuses: frozenset[int] = frozenset({502, 503, 504})
    # Повторять ли после таймаута. У отчёта БКИ нет: повтор только после 503 или обрыва (9.2)
    retry_on_timeout: bool = True

    def scaled(self, scale: float) -> CallPolicy:
        return replace(self, timeout_s=self.timeout_s * scale, budget_s=self.budget_s * scale)


# Паузы: экспонента от 0,3 с с полным разбросом, потолок 2 с
BACKOFF_BASE_S = 0.3
BACKOFF_CAP_S = 2.0
# Больше этого `Retry-After` при 429 не ждём: сразу считаем недоступностью (50-08)
MAX_RETRY_AFTER_S = 5.0
# Сколько раз подряд ждём `409 IDEMPOTENCY_IN_PROGRESS`, не тратя попытку
MAX_IN_PROGRESS_WAITS = 5

REGISTRY = CallPolicy(System.REGISTRY, timeout_s=2.0, attempts=3, budget_s=8.0)
TAX = CallPolicy(System.TAX, timeout_s=2.0, attempts=3, budget_s=8.0)
BANK_CORE_READ = CallPolicy(System.BANK_CORE, timeout_s=1.0, attempts=3, budget_s=4.5)
BUREAU_REPORT = CallPolicy(
    System.CREDIT_BUREAU,
    timeout_s=5.0,
    attempts=2,
    budget_s=12.0,
    retry_statuses=frozenset({503}),
    retry_on_timeout=False,
)
# submissions повторяет outbox, внутри вызова только ожидание 409 IN_PROGRESS
BUREAU_SUBMIT = CallPolicy(System.CREDIT_BUREAU, timeout_s=5.0, attempts=1, budget_s=8.0)
