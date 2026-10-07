"""Recover explicit page headings only; never invent an entity association."""
import re


def page_heading(text: str | None) -> tuple[str, ...]:
    first = next((line.strip() for line in (text or '').splitlines() if line.strip()), '')
    if len(first) > 120:
        return ()
    if re.match(r'^(?:\d{1,3}(?:[.、]|\s)|第[一二三四五六七八九十百\d]+[章节]|#{1,6}\s)', first):
        return (first,)
    return ()
