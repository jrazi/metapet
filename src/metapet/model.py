"""The idea model and its frontmatter (de)serialization."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import frontmatter


class Status(StrEnum):
    SEED = "seed"
    SKETCH = "sketch"
    SPEC = "spec"
    BUILDING = "building"
    SHIPPED = "shipped"
    SHELVED = "shelved"

    @property
    def terminal(self) -> bool:
        return self in (Status.SHIPPED, Status.SHELVED)

    def next(self) -> Status | None:
        """The natural next step in the lifecycle, or None when terminal."""
        order = [Status.SEED, Status.SKETCH, Status.SPEC, Status.BUILDING, Status.SHIPPED]
        if self.terminal:
            return None
        return order[order.index(self) + 1]


class Effort(StrEnum):
    S = "S"
    M = "M"
    L = "L"
    XL = "XL"

    @property
    def weight(self) -> int:
        return {"S": 1, "M": 2, "L": 4, "XL": 8}[self.value]


# Frontmatter keys in the order they are written; anything else is preserved after them.
KNOWN_KEYS = (
    "id",
    "title",
    "status",
    "created",
    "updated",
    "reviewed",
    "tags",
    "excitement",
    "impact",
    "effort",
    "repo",
    "related",
    "shelved_reason",
)
REQUIRED_KEYS = ("id", "title", "status", "created")


class IdeaError(ValueError):
    """Raised when an idea file cannot be parsed into a valid idea.

    `problems` lists each problem; the message joins them with "; ".
    """

    def __init__(self, *problems: str):
        super().__init__("; ".join(problems))
        self.problems = list(problems)


LONG_TITLE_CHARS = 60
LONG_TITLE_WORDS = 8
_CLAUSE_END = re.compile(r"[.,:;!?(—–]")
_TRAILING_PUNCTUATION = " \t.,:;!?()—–-\"'"
# Words a short title should not end with.
STOP_WORDS = frozenset(
    ("a", "an", "the", "and", "or", "of", "for", "to", "with", "that", "in", "on", "by", "from")
)


def is_long_title(text: str) -> bool:
    """True for text that reads like a description rather than a name."""
    title = " ".join(text.split())
    return len(title) > LONG_TITLE_CHARS or len(title.split()) > LONG_TITLE_WORDS


def short_title(text: str) -> str:
    """A name made from the start of a longer text, cut at whole words."""
    text = " ".join(text.split())
    clause = _CLAUSE_END.split(text, maxsplit=1)[0].split()
    if 3 <= len(clause) <= LONG_TITLE_WORDS:
        words = clause
    else:
        words = []
        for word in text.split()[:LONG_TITLE_WORDS]:
            if len(" ".join([*words, word])) > LONG_TITLE_CHARS:
                break
            words.append(word)
        if not words:
            words = [text[:LONG_TITLE_CHARS]]
    while True:
        words[-1] = words[-1].rstrip(_TRAILING_PUNCTUATION)
        if len(words) > 1 and (not words[-1] or words[-1].casefold() in STOP_WORDS):
            words.pop()
            continue
        break
    return " ".join(words).strip() or text[:LONG_TITLE_CHARS]


def clean_title(text: str) -> str:
    """The title with every run of whitespace made one space; ValueError when empty."""
    title = " ".join(str(text).split())
    if not title:
        raise ValueError("a title is required")
    return title


@dataclass
class Idea:
    id: str
    title: str
    status: Status = Status.SEED
    created: dt.date = field(default_factory=dt.date.today)
    updated: dt.date | None = None
    reviewed: dt.date | None = None
    tags: list[str] = field(default_factory=list)
    excitement: int | None = None
    impact: int | None = None
    effort: Effort | None = None
    repo: str | None = None
    related: list[str] = field(default_factory=list)
    shelved_reason: str | None = None
    body: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    path: Path | None = None

    # -- serialization -----------------------------------------------------

    def to_markdown(self) -> str:
        meta: dict[str, Any] = {}
        for key in KNOWN_KEYS:
            value = getattr(self, key)
            if value is None or value == []:
                continue
            if isinstance(value, StrEnum):
                value = value.value
            meta[key] = value
        meta.update(self.extra)
        post = frontmatter.Post(self.body.strip() + "\n", **meta)
        return frontmatter.dumps(post, sort_keys=False) + "\n"

    @classmethod
    def from_markdown(cls, text: str, path: Path | None = None) -> Idea:
        try:
            post = frontmatter.loads(text)
        except Exception as exc:  # yaml errors come in many flavours
            raise IdeaError(f"unreadable frontmatter: {_yaml_problem(exc)}") from exc
        meta = dict(post.metadata)
        problems: list[str] = []
        missing = [key for key in REQUIRED_KEYS if not meta.get(key)]
        if missing:
            problems.append(f"missing required field(s): {', '.join(missing)}")

        def check(key: str, convert, default=None):
            """Convert one key, noting its problem instead of stopping at the first."""
            value = meta.pop(key, None)
            if value is None or value == "":
                return default
            try:
                return convert(value)
            except (ValueError, TypeError) as exc:
                problems.append(f"{key}: {_problem(key, value, exc)}")
                return default

        values = {
            "id": check("id", str, ""),
            "title": check("title", str, ""),
            "status": check("status", Status, Status.SEED),
            "created": check("created", _as_date, dt.date.today()),
            "updated": check("updated", _as_date),
            "reviewed": check("reviewed", _as_date),
            "tags": check("tags", _as_list, []),
            "excitement": check("excitement", _as_scale),
            "impact": check("impact", _as_scale),
            "effort": check("effort", _as_effort),
            "repo": check("repo", str),
            "related": check("related", _as_list, []),
            "shelved_reason": check("shelved_reason", str),
        }
        if problems:
            raise IdeaError(*problems)
        return cls(**values, body=post.content, extra=meta, path=path)

    @classmethod
    def load(cls, path: Path) -> Idea:
        return cls.from_markdown(path.read_text(encoding="utf-8"), path=path)

    def touch(self) -> None:
        self.updated = dt.date.today()

    def mark_reviewed(self, today: dt.date | None = None) -> None:
        self.reviewed = today or dt.date.today()


def _yaml_problem(exc: Exception) -> str:
    """A YAML error in one line, with the line number in the file when known."""
    problem = getattr(exc, "problem", None)
    mark = getattr(exc, "problem_mark", None)
    if problem and mark is not None:
        # The frontmatter text starts on the first --- line, and marks count from 0.
        return f"{problem} (line {mark.line + 1})"
    return " ".join(str(exc).split())


def _problem(key: str, value: Any, exc: Exception) -> str:
    """The problem with a frontmatter value, in words a person can act on."""
    if key == "status":
        return f"'{value}' is not one of {', '.join(Status)}"
    if key in ("created", "updated", "reviewed"):
        return f"'{value}' is not a date (YYYY-MM-DD)"
    if key == "effort":
        return f"'{value}' must be S, M, L or XL"
    if key in ("excitement", "impact"):
        return str(exc) if isinstance(exc, _ScaleError) else f"'{value}' is not a number from 1 to 5"
    return str(exc)


class _ScaleError(ValueError):
    pass


def _as_date(value: Any) -> dt.date | None:
    if value is None or isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.datetime):
        return value.date()
    return dt.date.fromisoformat(str(value))


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(item) for item in value]


def _as_effort(value: Any) -> Effort | None:
    return Effort(str(value).upper()) if value else None


def _as_scale(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(value)
    number = int(value)
    if not 1 <= number <= 5:
        raise _ScaleError(f"must be 1-5, got {number}")
    return number
