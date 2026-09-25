"""Section templates appended to an idea as it matures."""

from __future__ import annotations

import re
from importlib import resources

from metapet.model import Idea, Status
from metapet.paths import DataHome

# Which template a status brings in; seeds carry just their one-liner.
TEMPLATE_FOR = {
    Status.SKETCH: "sketch",
    Status.SPEC: "spec",
    Status.BUILDING: "building",
    Status.SHIPPED: "retro",
    Status.SHELVED: "retro",
}
LIFECYCLE = [Status.SEED, Status.SKETCH, Status.SPEC, Status.BUILDING, Status.SHIPPED]
HEADING = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def load(name: str, home: DataHome | None = None) -> str:
    """A template's text, preferring the user's override in <home>/templates."""
    if home is not None:
        override = home.templates / f"{name}.md"
        if override.is_file():
            return override.read_text(encoding="utf-8")
    return resources.files("metapet").joinpath("templates", f"{name}.md").read_text("utf-8")


def sections(text: str) -> list[tuple[str, str]]:
    """Split markdown into (heading, block) pairs at `## ` headings."""
    matches = list(HEADING.finditer(text))
    ends = [m.start() for m in matches[1:]] + ([len(text)] if matches else [])
    return [
        (m.group(1).strip().lower(), text[m.start() : end].strip())
        for m, end in zip(matches, ends, strict=True)
    ]


def append_sections(body: str, template: str) -> str:
    """Append the template's sections that the body doesn't already have."""
    present = {heading for heading, _ in sections(body)}
    missing = [block for heading, block in sections(template) if heading not in present]
    if not missing:
        return body
    return "\n\n".join(part for part in [body.strip(), *missing] if part) + "\n"


def statuses_between(old: Status, new: Status) -> list[Status]:
    """Statuses newly reached when moving old → new (empty when moving back)."""
    if new == Status.SHELVED:
        return [Status.SHELVED]
    if old not in LIFECYCLE or LIFECYCLE.index(new) <= LIFECYCLE.index(old):
        return []
    return LIFECYCLE[LIFECYCLE.index(old) + 1 : LIFECYCLE.index(new) + 1]


def move(idea: Idea, new: Status, home: DataHome | None = None) -> None:
    """Change an idea's status, growing its body with each newly reached stage."""
    for status in statuses_between(idea.status, new):
        idea.body = append_sections(idea.body, load(TEMPLATE_FOR[status], home))
    idea.status = new
    idea.touch()
