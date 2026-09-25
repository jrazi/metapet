"""Rank ideas for `pet next`.

score = (excitement + impact) / effort weight + stage bonus + age bonus
"""

from __future__ import annotations

import datetime as dt

from metapet.model import Effort, Idea, Status

DEFAULT_EXCITEMENT = 3
DEFAULT_IMPACT = 3
DEFAULT_EFFORT = Effort.M
STAGE_BONUS = {Status.SEED: 0.0, Status.SKETCH: 0.25, Status.SPEC: 0.5, Status.BUILDING: 0.75}
AGE_BONUS_MAX = 0.5
AGE_BONUS_DAYS = 180


def score(idea: Idea, today: dt.date | None = None) -> float:
    if idea.status.terminal:
        return 0.0
    today = today or dt.date.today()
    excitement = idea.excitement or DEFAULT_EXCITEMENT
    impact = idea.impact or DEFAULT_IMPACT
    effort = idea.effort or DEFAULT_EFFORT
    age_days = max((today - idea.created).days, 0)
    age_bonus = AGE_BONUS_MAX * min(age_days / AGE_BONUS_DAYS, 1.0)
    return (excitement + impact) / effort.weight + STAGE_BONUS[idea.status] + age_bonus


def rank(ideas: list[Idea], today: dt.date | None = None) -> list[tuple[Idea, float]]:
    live = [idea for idea in ideas if not idea.status.terminal]
    scored = [(idea, score(idea, today)) for idea in live]
    return sorted(scored, key=lambda pair: (-pair[1], pair[0].created))
