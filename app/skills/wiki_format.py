"""Build consistent Markdown wiki pages for skills."""
from __future__ import annotations


def _body(value: str | list[str]) -> str:
    if isinstance(value, list):
        return "\n".join(f"- {item}" for item in value)
    return value.strip()


def wiki_page(
    title: str,
    overview: str,
    *,
    does: str | list[str],
    when: list[str],
    how: list[str],
    uses: str | list[str],
    output: str | list[str],
    safety: str | list[str],
    related: list[str],
    maps_to: str,
    extra: str = "",
) -> str:
    """Return a long-form Markdown wiki page with a standard section layout."""
    parts = [
        f"## {title}",
        "",
        overview.strip(),
        "",
        "### What it does",
        "",
        _body(does),
        "",
        "### When to use it",
        "",
        _body(when),
        "",
        "### How to run it",
        "",
        _body(how),
        "",
        "### Inputs and connections",
        "",
        _body(uses),
        "",
        "### What you get back",
        "",
        _body(output),
        "",
        "### Safety and limits",
        "",
        _body(safety),
        "",
        "### Related skills",
        "",
        _body(related),
        "",
        "### Maps to",
        "",
        maps_to.strip(),
    ]
    if extra.strip():
        parts.extend(["", extra.strip()])
    return "\n".join(parts).strip() + "\n"
