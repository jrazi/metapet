"""Render all ideas as a Markdown index or a JSON dump."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path, PurePath

from metapet.model import Idea, Status


def to_json(ideas: list[Idea]) -> str:
    def row(idea: Idea) -> dict:
        return {
            "id": idea.id,
            "title": idea.title,
            "status": idea.status.value,
            "created": idea.created.isoformat(),
            "updated": idea.updated.isoformat() if idea.updated else None,
            "reviewed": idea.reviewed.isoformat() if idea.reviewed else None,
            "tags": idea.tags,
            "excitement": idea.excitement,
            "impact": idea.impact,
            "effort": idea.effort.value if idea.effort else None,
            "repo": idea.repo,
            "related": idea.related,
            "shelved_reason": idea.shelved_reason,
            **idea.extra,
            "body": idea.body,
        }

    return json.dumps([row(i) for i in ideas], indent=2, ensure_ascii=False, default=str) + "\n"


def _cell(text: str) -> str:
    """Text for a Markdown table cell: | would end the cell, brackets would end a link."""
    for char in ("\\", "|", "[", "]"):
        text = text.replace(char, "\\" + char)
    return text


def _link(idea: Idea, target_dir: Path) -> str:
    """The path of the idea file relative to the directory of the index, with / separators."""
    path = idea.path or Path("ideas") / f"{idea.id}.md"
    try:
        relative = os.path.relpath(path.resolve(), target_dir.resolve())
    except ValueError:  # on another drive (Windows)
        return path.resolve().as_uri()
    return PurePath(relative).as_posix().replace(" ", "%20")


def to_markdown(ideas: list[Idea], target_dir: Path | None = None) -> str:
    """A Markdown index; links are relative to target_dir, where the index is written."""
    target_dir = target_dir or Path.cwd()
    count = "1 idea" if len(ideas) == 1 else f"{len(ideas)} ideas"
    lines = ["# Ideas", "", f"_{count} · exported {dt.date.today()}_", ""]
    for status in Status:
        group = sorted((i for i in ideas if i.status == status), key=lambda i: i.created)
        if not group:
            continue
        lines += [f"## {status.value.capitalize()} ({len(group)})", ""]
        lines += [
            "| Idea | Tags | Excitement | Impact | Effort | Created |",
            "|---|---|---|---|---|---|",
        ]
        for idea in group:
            lines.append(
                f"| [{_cell(idea.title)}]({_link(idea, target_dir)}) "
                f"| {_cell(', '.join(idea.tags))} "
                f"| {idea.excitement or ''} | {idea.impact or ''} "
                f"| {idea.effort.value if idea.effort else ''} "
                f"| {idea.created} |"
            )
        lines.append("")
    return "\n".join(lines)
