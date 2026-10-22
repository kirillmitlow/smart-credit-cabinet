"""Тексты согласий и правил подписи (T-260, 20-04): файл `policy/consents/<имя>-v<N>.txt`.

Версия в имени файла. В `consents` пишутся версия и SHA-256 текста, нормализованного по пробелам
(любая серия пробелов, переносов и табуляций → один пробел, края обрезаны). Хеш считается по
шаблону с подстановками `{name}`, `{inn}` …: подставленные значения лежат в самой записи согласия.
Изменение текста = новый файл `…-v2.txt`: прошлые подписи ссылаются на свою версию и не меняются.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from app.modules import catalog
from app.shared.errors import AppError

PEP_RULES = "pep-rules"
PREFIX_BY_KIND = {
    "BKI": "bki-consent",
    "TURNOVER": "turnover-consent",
    "PERSONAL_DATA": "pd-consent",
}
_NAME_RE = re.compile(r"^(?P<prefix>[a-z-]+)-v(?P<version>\d+)\.txt$")


@dataclass(frozen=True, slots=True)
class ConsentText:
    key: str  # bki-consent-v1
    prefix: str
    version: int
    text: str
    sha256: str

    def render(self, **values: str) -> str:
        return self.text.format_map(_Defaults(values))


class _Defaults(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def normalize(text: str) -> str:
    return " ".join(text.split())


def text_hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def _directory() -> Path:
    return catalog.policy_dir() / "consents"


def available() -> dict[str, ConsentText]:
    """Все версии текстов с диска по ключу (`bki-consent-v1`). Чтение дешёвое, кэша нет."""
    found: dict[str, ConsentText] = {}
    for path in sorted(_directory().glob("*.txt")):
        match = _NAME_RE.match(path.name)
        if match is None:
            continue
        text = path.read_text(encoding="utf-8")
        key = path.stem
        found[key] = ConsentText(
            key, match["prefix"], int(match["version"]), text.strip(), text_hash(text)
        )
    return found


def current(prefix: str) -> ConsentText:
    """Действующая версия — с наибольшим номером."""
    versions = [t for t in available().values() if t.prefix == prefix]
    if not versions:
        raise AppError(500, "CONSENT_TEXT_MISSING", f"Нет текста {prefix} в policy/consents")
    return max(versions, key=lambda t: t.version)


def current_for_kind(kind: str) -> ConsentText:
    return current(PREFIX_BY_KIND[kind])


def pep_rules() -> ConsentText:
    return current(PEP_RULES)
