"""Load, save and look up ideas in a data home."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from metapet import ids
from metapet.model import Idea, IdeaError, clean_title
from metapet.paths import DataHome


class IdeaLookupError(LookupError):
    """No idea, or more than one idea, matches a query."""

    def __init__(self, message: str, candidates: list[Idea] | None = None):
        super().__init__(message)
        self.candidates = candidates or []


@dataclass(frozen=True)
class BrokenFile:
    path: Path
    error: str


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
                broken.append(BrokenFile(path, str(exc)))
        return ideas, broken

    def all(self) -> list[Idea]:
        return self.scan()[0]

    def find(self, query: str) -> Idea:
        """Match by exact id, then id prefix, then substring of id or title."""
        ideas = self.all()
        q = query.lower().strip()
        for tier in (
            lambda i: i.id == q,
            lambda i: i.id.startswith(q),
            lambda i: q in i.id or q in i.title.lower(),
        ):
            matches = [idea for idea in ideas if tier(idea)]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise IdeaLookupError(f"'{query}' matches {len(matches)} ideas", matches)
        raise IdeaLookupError(f"no idea matches '{query}'")

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

    def save(self, idea: Idea) -> Path:
        path = idea.path or self.home.ideas / f"{idea.id}.md"
        path.write_text(idea.to_markdown(), encoding="utf-8")
        idea.path = path
        return path
