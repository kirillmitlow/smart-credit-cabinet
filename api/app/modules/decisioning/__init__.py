"""Чистое ядро решения: признаки, скоринг, лимиты, ставка, встречные, объяснения.

Без сети, БД, времени и случайности (R2, D-030): данные и правила приходят аргументами,
результат возвращается значением. Спецификации — docs/plan/30-decisioning/.
"""

from app.modules.decisioning.decide import DecisionInput, DecisionResult, decide

__all__ = ["DecisionInput", "DecisionResult", "decide"]
