"""Load, save and look up ideas in a data home."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from metapet import ids
from metapet.fields import normalize_tags
from metapet.model import Idea, IdeaError, clean_title
from metapet.paths import DataHome

T = TypeVar("T")


class IdeaLookupError(LookupError):
    """No idea, or more than one idea, matches a query."""

    def __init__(self, message: str, candidates: list[Idea] | None = None):
        super().__init__(message)
        self.candidates = candidates or []


@dataclass(frozen=True)
class BrokenFile:
    path: Path
    error: str  # every problem, joined with "; "
    problems: tuple[str, ...] = ()


def _match(query: str, items: list[T], names: Callable[[T], tuple[str, str]]) -> list[T]:
    """Items matching by exact id, else id prefix, else a fragment of the id or title."""
    q = query.lower().strip()
    for tier in (
        lambda id_, title: id_ == q,
        lambda id_, title: id_.startswith(q),
        lambda id_, title: q in id_ or q in title.lower(),
    ):
        matches = [item for item in items if tier(*names(item))]
        if matches:
            return matches
    return []


def _title_key(title: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", title.casefold()).split())


class Store:
    def __init__(self, home: DataHome):
        self.home = home

    # -- setup ---------------------------------------------------------------

    def init(self) -> None:
        self.home.ideas.mkdir(parents=True, exist_ok=True)

    def require(self) -> None:
        if not self.home.exists:
            raise FileNotFoundError(
                f"no idea store at {self.home.path} (from {self.home.source}); run `pet init` first"
            )

    # -- reading -------------------------------------------------------------

    def scan(self) -> tuple[list[Idea], list[BrokenFile]]:
        """Load every idea file, collecting the ones that fail to parse."""
        self.require()
        ideas: list[Idea] = []
        broken: list[BrokenFile] = []
        for path in sorted(self.home.ideas.glob("*.md")):
            try:
                ideas.append(Idea.load(path))
            except IdeaError as exc:
                broken.append(BrokenFile(path, str(exc), tuple(exc.problems)))
        return ideas, broken

    def all(self) -> list[Idea]:
        return self.scan()[0]

    def find(self, query: str) -> Idea:
        """Match by exact id, then id prefix, then substring of id or title.

        When nothing matches but an unreadable file does, the error says so.
        """
        ideas, broken = self.scan()
        matches = _match(query, ideas, lambda i: (i.id, i.title))
        if len(matches) == 1:
            return matches[0]
        if matches:
            raise IdeaLookupError(f"'{query}' matches {len(matches)} ideas", matches)
        hits = _match(query, broken, lambda b: (b.path.stem.lower(), ""))
        if len(hits) == 1:
            bad = hits[0]
            raise IdeaLookupError(
                f"{bad.path.name} cannot be read: {bad.error}; fix it with pet edit {bad.path.stem}"
            )
        raise IdeaLookupError(f"no idea matches '{query}'")

    def find_path(self, query: str) -> Path:
        """Like find, but also finds files that cannot be read, so they can be fixed."""
        try:
            idea = self.find(query)
        except IdeaLookupError as exc:
            if exc.candidates:
                raise
            hits = _match(query, self.scan()[1], lambda b: (b.path.stem.lower(), ""))
            if len(hits) != 1:
                raise
            return hits[0].path
        return idea.path or self.home.ideas / f"{idea.id}.md"

    def same_title(self, title: str) -> list[Idea]:
        """Ideas with the same title, ignoring case, spacing and punctuation."""
        wanted = _title_key(title)
        return [idea for idea in self.all() if _title_key(idea.title) == wanted]

    def all_tags(self) -> list[str]:
        """Every tag in use, once each (first spelling wins), sorted ignoring case."""
        tags: dict[str, str] = {}
        for idea in self.all():
            for tag in idea.tags:
                tags.setdefault(tag.casefold(), tag)
        return sorted(tags.values(), key=str.casefold)

    # -- writing -------------------------------------------------------------

    def exists(self, idea_id: str) -> bool:
        return (self.home.ideas / f"{idea_id}.md").exists()

    def unique(self, base: str) -> str:
        """base, or base-2, base-3, ... when an idea already uses it."""
        candidate, n = base, 2
        while self.exists(candidate):
            candidate, n = ids.with_suffix(base, n), n + 1
        return candidate

    def unique_id(self, title: str, today: dt.date | None = None) -> str:
        return self.unique(ids.suggest(title, today).id)

    def check_new_id(self, idea_id: str) -> str:
        """A typed id, validated and not in use yet; ValueError otherwise."""
        idea_id = ids.validate(idea_id)
        if self.exists(idea_id):
            raise ValueError(f"an idea with id '{idea_id}' already exists")
        return idea_id

    def create(self, title: str, *, id: str | None = None, **fields) -> Idea:
        """Create and save an idea; `id` is checked with check_new_id when given."""
        self.require()
        title = clean_title(title)
        if "tags" in fields:
            fields["tags"] = normalize_tags(fields["tags"], self.all_tags())
        idea_id = self.check_new_id(id) if id is not None else self.unique_id(title)
        idea = Idea(id=idea_id, title=title, **fields)
        self.save(idea)
        return idea

    def rename(self, idea: Idea, new_id: str) -> list[Idea]:
        """Give an idea a new id and file name, and update the related lists that name it.

        Returns the other ideas whose related list changed.
        """
        new_id = ids.validate(new_id)
        if new_id == idea.id:
            raise ValueError(f"{idea.id}: no change")
        if self.exists(new_id):
            raise ValueError(f"an idea with id '{new_id}' already exists")
        old_id, old_path = idea.id, idea.path
        others = [other for other in self.all() if other.path != old_path]
        idea.id = new_id
        idea.path = self.home.ideas / f"{new_id}.md"
        self.save(idea)
        if old_path is not None and old_path != idea.path:
            old_path.unlink(missing_ok=True)
        changed = []
        for other in others:
            if old_id in other.related:
                other.related = [new_id if item == old_id else item for item in other.related]
                self.save(other)
                changed.append(other)
        return changed

    def delete(self, idea: Idea) -> list[Idea]:
        """Delete an idea's file and remove its id from other ideas' related lists.

        Returns the other ideas whose related list changed.
        """
        if idea.path is not None:
            idea.path.unlink(missing_ok=True)
        changed = []
        for other in self.all():
            if idea.id in other.related:
                other.related = [item for item in other.related if item != idea.id]
                self.save(other)
                changed.append(other)
        return changed

    def save(self, idea: Idea) -> Path:
        path = idea.path or self.home.ideas / f"{idea.id}.md"
        path.write_text(idea.to_markdown(), encoding="utf-8")
        idea.path = path
        return path
