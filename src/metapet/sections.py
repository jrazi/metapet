"""Split an idea's Markdown body into its preamble and `## ` sections, and put it back together.

Limitation: a `## ` line inside a fenced code block is still read as a heading.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

HEADING = re.compile(r"^##[ \t]+(.+?)[ \t]*$", re.MULTILINE)  # "### x" is not a match
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
BARE_MARKER = re.compile(r"^\s*(?:[-*+]|\d+\.)\s*$")
ITEM = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+(.*)$")


@dataclass
class Section:
    heading: str  # as written
    content: str  # text after the heading line, stripped


@dataclass
class Body:
    preamble: str  # text before the first "## " heading, stripped
    sections: list[Section] = field(default_factory=list)


def parse(text: str) -> Body:
    matches = list(HEADING.finditer(text))
    if not matches:
        return Body(text.strip(), [])
    ends = [m.start() for m in matches[1:]] + [len(text)]
    return Body(
        text[: matches[0].start()].strip(),
        [
            Section(m.group(1).strip(), text[m.end() : end].strip())
            for m, end in zip(matches, ends, strict=True)
        ],
    )


def render(body: Body) -> str:
    parts = [body.preamble] if body.preamble else []
    for section in body.sections:
        heading = f"## {section.heading}"
        parts.append(f"{heading}\n{section.content}" if section.content else heading)
    return "\n\n".join(parts) + "\n" if parts else ""


def strip_comments(text: str) -> str:
    return COMMENT.sub("", text)


def is_empty(text: str) -> bool:
    """True for whitespace, HTML comments and bare list markers (the old placeholders)."""
    lines = strip_comments(text).splitlines()
    return not "".join(line for line in lines if not BARE_MARKER.match(line)).strip()


def items(text: str) -> list[str]:
    """One item per list line; any other non-empty line counts as an item too."""
    result = []
    for line in strip_comments(text).splitlines():
        match = ITEM.match(line)
        item = (match.group(1) if match else line).strip()
        if item and not BARE_MARKER.match(line):
            result.append(item)
    return result


def render_items(values: list[str]) -> str:
    return "\n".join("- " + " ".join(value.split()) for value in values)


def extend_items(content: str, values: list[str]) -> str:
    """Add list items at the end of a section, keeping the text before them as written."""
    added = render_items(values)
    return f"{content.rstrip()}\n{added}" if not is_empty(content) else added


def find(body: Body, match: Callable[[str], bool]) -> Section | None:
    return next((s for s in body.sections if match(s.heading)), None)


def upsert(
    body: Body,
    heading: str,
    content: str,
    match: Callable[[str], bool],
    order: Callable[[str], int | None],
) -> None:
    """Replace a matching section's content, or insert a new section in schema order."""
    existing = find(body, match)
    if existing is not None:
        existing.content = content.strip()
        return
    new = Section(heading, content.strip())
    rank = order(heading)
    if rank is not None:
        for index, section in enumerate(body.sections):
            other = order(section.heading)
            if other is not None and other > rank:
                body.sections.insert(index, new)
                return
    body.sections.append(new)


def append_item(content: str, item: str) -> str:
    kept = strip_comments(content).strip()
    kept = "\n".join(line for line in kept.splitlines() if not BARE_MARKER.match(line)).strip()
    return f"{kept}\n- {item}" if kept else f"- {item}"
