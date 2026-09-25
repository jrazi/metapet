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

    def create(self, title: str, **fields) -> Idea:
        self.require()
        title = clean_title(title)
        idea = Idea(id=self.unique_id(title), title=title, **fields)
        self.save(idea)
        return idea

    def save(self, idea: Idea) -> Path:
        path = idea.path or self.home.ideas / f"{idea.id}.md"
        path.write_text(idea.to_markdown(), encoding="utf-8")
        idea.path = path
        return path
