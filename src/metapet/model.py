"""The idea model and its frontmatter (de)serialization."""

from __future__ import annotations

import datetime as dt
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
    """Raised when an idea file cannot be parsed into a valid idea."""


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
            raise IdeaError(f"unreadable frontmatter: {exc}") from exc
        meta = dict(post.metadata)
        missing = [key for key in REQUIRED_KEYS if not meta.get(key)]
        if missing:
            raise IdeaError(f"missing required field(s): {', '.join(missing)}")
        try:
            idea = cls(
                id=str(meta.pop("id")),
                title=str(meta.pop("title")),
                status=Status(meta.pop("status")),
                created=_as_date(meta.pop("created")),
                updated=_as_date(meta.pop("updated", None)),
                reviewed=_as_date(meta.pop("reviewed", None)),
                tags=_as_list(meta.pop("tags", None)),
                excitement=_as_scale("excitement", meta.pop("excitement", None)),
                impact=_as_scale("impact", meta.pop("impact", None)),
                effort=_as_effort(meta.pop("effort", None)),
                repo=meta.pop("repo", None),
                related=_as_list(meta.pop("related", None)),
                shelved_reason=meta.pop("shelved_reason", None),
                body=post.content,
                path=path,
            )
        except (ValueError, TypeError) as exc:
            raise IdeaError(str(exc)) from exc
        idea.extra = meta
        return idea

    @classmethod
    def load(cls, path: Path) -> Idea:
        return cls.from_markdown(path.read_text(encoding="utf-8"), path=path)

    def touch(self) -> None:
        self.updated = dt.date.today()

    def mark_reviewed(self, today: dt.date | None = None) -> None:
        self.reviewed = today or dt.date.today()


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


def _as_scale(name: str, value: Any) -> int | None:
    if value is None:
        return None
    number = int(value)
    if not 1 <= number <= 5:
        raise ValueError(f"{name} must be 1-5, got {number}")
    return number
