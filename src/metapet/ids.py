"""Make idea ids from titles, and check ids that people type.

An id is what you type in commands, so it uses only lowercase ASCII letters, digits and
single hyphens, and stays short. Titles in other scripts are transliterated so that the id
can be typed on any keyboard; the title itself is kept as written.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from anyascii import anyascii

from metapet.model import STOP_WORDS

ID_MAX = 40
ID_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
ID_RULE = "an id uses lowercase letters, digits and single hyphens, up to 40 characters"
LEADING_ARTICLES = {"a", "an", "the"}
_SHARP = re.compile(r"(?<=[^\W\d_])#")
_WORD_SPLIT = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class Suggestion:
    id: str
    exact: bool  # False when words were cut, letters transliterated, or the fallback used


def _transliterated(text: str) -> tuple[str, bool]:
    """ASCII text, and whether any letter or symbol had to be spelled differently."""
    changed = any(ord(c) > 127 and any(ch.isalnum() for ch in anyascii(c)) for c in text)
    return anyascii(text), changed


def suggest(title: str, today: dt.date | None = None) -> Suggestion:
    """An id for this title, made of whole words and at most ID_MAX characters."""
    text = title.replace("++", "pp").replace("&", " and ")
    text = _SHARP.sub("sharp", text)
    text, changed = _transliterated(text)
    words = [w for w in _WORD_SPLIT.split(text.lower()) if w]
    if len(words) > 1 and words[0] in LEADING_ARTICLES:
        words = words[1:]
    kept: list[str] = []
    cut = False
    for word in words:
        if not kept and len(word) > ID_MAX:
            kept.append(word[:ID_MAX])
            cut = True
            break
        if len("-".join([*kept, word])) > ID_MAX:
            cut = True
            break
        kept.append(word)
    if cut:
        while len(kept) > 1 and kept[-1] in STOP_WORDS:
            kept.pop()
    if not kept:
        return Suggestion(f"idea-{(today or dt.date.today()):%Y%m%d}", exact=False)
    return Suggestion("-".join(kept), exact=not (cut or changed))


def validate(text: str) -> str:
    """The id as it will be stored (lowercased); ValueError when it breaks the rule."""
    value = text.strip().lower()
    if len(value) > ID_MAX or not ID_PATTERN.match(value):
        raise ValueError(ID_RULE)
    return value


def with_suffix(base: str, n: int) -> str:
    """base-n, shortening base so the result still fits in ID_MAX."""
    suffix = f"-{n}"
    return base[: ID_MAX - len(suffix)].rstrip("-") + suffix
