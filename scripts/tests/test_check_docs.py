from pathlib import Path

from scripts.check_docs import broken_links, main


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_existing_relative_link_is_ok(tmp_path: Path) -> None:
    write(tmp_path / "b.md", "# B")
    md = write(tmp_path / "a.md", "см. [B](b.md) и [якорь](b.md#раздел)")
    assert broken_links(md) == []


def test_missing_target_is_reported_with_line(tmp_path: Path) -> None:
    md = write(tmp_path / "a.md", "строка\n[нет](missing.md)")
    assert broken_links(md) == [(2, "missing.md")]


def test_external_anchor_code_and_fences_are_ignored(tmp_path: Path) -> None:
    md = write(
        tmp_path / "a.md",
        "[w](https://example.org) [a](#x) `[c](nope.md)`\n```\n[f](nope.md)\n```\n",
    )
    assert broken_links(md) == []


def test_percent_encoded_cyrillic_path(tmp_path: Path) -> None:
    write(tmp_path / "дом.md", "# Д")
    md = write(tmp_path / "a.md", "[д](%D0%B4%D0%BE%D0%BC.md)")
    assert broken_links(md) == []


def test_repository_docs_have_no_broken_links() -> None:
    assert main([]) == 0
