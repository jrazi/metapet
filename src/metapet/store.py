"""Load, save and look up ideas in a data home."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from metapet.model import Idea, IdeaError
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


def slugify(text: str, max_len: int = 60) -> str:
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    slug = slug[:max_len].rstrip("-")
    return slug or "idea"


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

    # -- writing -------------------------------------------------------------

    def unique_id(self, title: str) -> str:
        base = slugify(title)
        candidate, n = base, 2
        while (self.home.ideas / f"{candidate}.md").exists():
            candidate, n = f"{base}-{n}", n + 1
        return candidate

    def create(self, title: str, **fields) -> Idea:
        self.require()
        idea = Idea(id=self.unique_id(title), title=title.strip(), **fields)
        self.save(idea)
        return idea

    def save(self, idea: Idea) -> Path:
        path = idea.path or self.home.ideas / f"{idea.id}.md"
        path.write_text(idea.to_markdown(), encoding="utf-8")
        idea.path = path
        return path
