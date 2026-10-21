"""Проверка документов: относительные ссылки в Markdown ведут на существующие файлы.

Запуск: `python scripts/check_docs.py [корень ...]` (по умолчанию docs/, AGENTS.md, README.md).
Полная проверка (шапки, mermaid) — задача T-522; здесь минимум, который нужен CI с первого дня.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

REPO = Path(__file__).resolve().parent.parent
DEFAULT_ROOTS = ("docs", "AGENTS.md", "README.md")
# [текст](цель) — без картинок-ссылок на внешние ресурсы; код в обратных кавычках вырезаем заранее.
LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE = re.compile(r"^(```|~~~)")
INLINE_CODE = re.compile(r"`[^`]*`")
EXTERNAL = ("http://", "https://", "mailto:", "#")


def iter_markdown(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if root.is_file() and root.suffix == ".md":
            files.append(root)
        elif root.is_dir():
            files.extend(sorted(root.rglob("*.md")))
    return files


def broken_links(md: Path) -> list[tuple[int, str]]:
    """Вернуть (номер строки, цель) для каждой битой относительной ссылки."""
    problems: list[tuple[int, str]] = []
    in_fence = False
    for lineno, line in enumerate(md.read_text(encoding="utf-8").splitlines(), start=1):
        if FENCE.match(line.strip()):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for target in LINK.findall(INLINE_CODE.sub("", line)):
            if target.startswith(EXTERNAL):
                continue
            path_part = unquote(target.split("#", 1)[0])
            if not path_part:
                continue
            if not (md.parent / path_part).exists():
                problems.append((lineno, target))
    return problems


def main(argv: list[str]) -> int:
    roots = [REPO / a for a in (argv or DEFAULT_ROOTS)]
    total = 0
    for md in iter_markdown([r for r in roots if r.exists()]):
        for lineno, target in broken_links(md):
            print(f"{md.relative_to(REPO)}:{lineno}: битая ссылка → {target}")
            total += 1
    if total:
        print(f"Найдено битых ссылок: {total}")
        return 1
    print("Ссылки в документах в порядке")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
