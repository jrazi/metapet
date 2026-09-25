"""Render all ideas as a Markdown index or a JSON dump."""

from __future__ import annotations

import datetime as dt
import json

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


def to_markdown(ideas: list[Idea]) -> str:
    lines = ["# Ideas", "", f"_{len(ideas)} ideas · exported {dt.date.today()}_", ""]
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
                f"| [{idea.title}](ideas/{idea.id}.md) | {', '.join(idea.tags)} "
                f"| {idea.excitement or ''} | {idea.impact or ''} "
                f"| {idea.effort.value if idea.effort else ''} "
                f"| {idea.created} |"
            )
        lines.append("")
    return "\n".join(lines)
