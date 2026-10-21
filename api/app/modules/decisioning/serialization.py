"""Сериализация входа ядра в JSON и обратно без потерь; `inputs_hash` (T-280, 30-13).

Вход хранится в `decisions.inputs`, по нему решение воспроизводится. Канонический вид: ключи по
алфавиту, без пробелов, `Decimal` строкой; хеш — SHA-256 от этой строки.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from typing import Any

from pydantic import TypeAdapter

from app.modules.decisioning.policy import Policy
from app.modules.decisioning.types import Application, Context, DecisionInput, Snapshot


@lru_cache(maxsize=1)
def _input_adapter() -> TypeAdapter[DecisionInput]:
    return TypeAdapter(DecisionInput)


@lru_cache(maxsize=1)
def _facts_adapter() -> TypeAdapter[tuple[Application, Snapshot, Context]]:
    return TypeAdapter(tuple[Application, Snapshot, Context])


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def input_to_json(inp: DecisionInput) -> str:
    """Весь вход (заявка, снимок, контекст, политика) каноническим JSON."""
    return _canonical(_input_adapter().dump_python(inp, mode="json"))


def input_from_json(text: str) -> DecisionInput:
    return _input_adapter().validate_python(json.loads(text))


def inputs_hash(inp: DecisionInput) -> str:
    """Хеш входных фактов (заявка, снимок, контекст). Политика версионируется отдельно."""
    facts = (inp.application, inp.snapshot, inp.context)
    return hashlib.sha256(
        _canonical(_facts_adapter().dump_python(facts, mode="json")).encode("utf-8")
    ).hexdigest()


def policy_hash(policy: Policy) -> str:
    """SHA-256 канонической формы политики (ключи по алфавиту, без пробелов)."""
    return hashlib.sha256(_canonical(policy.model_dump(mode="json")).encode("utf-8")).hexdigest()
