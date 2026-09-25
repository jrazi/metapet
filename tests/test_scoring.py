import datetime as dt

from metapet import scoring
from metapet.model import Effort, Idea, Status

TODAY = dt.date(2026, 9, 25)


def idea(id_, **kw):
    return Idea(id=id_, title=id_, created=kw.pop("created", TODAY), **kw)


def test_rank_prefers_excited_cheap_advanced_and_old():
    ideas = [
        idea("meh-huge", excitement=2, effort=Effort.XL),
        idea("fun-small", excitement=5, effort=Effort.S),
        idea("fun-small-spec", excitement=5, effort=Effort.S, status=Status.SPEC),
        idea("old-default", created=TODAY - dt.timedelta(days=365)),
        idea("new-default"),
        idea("done", excitement=5, effort=Effort.S, status=Status.SHIPPED),
    ]
    order = [i.id for i, _ in scoring.rank(ideas, TODAY)]
    assert order == ["fun-small-spec", "fun-small", "old-default", "new-default", "meh-huge"]


def test_impact_changes_the_order():
    ideas = [
        idea("exciting", excitement=5, impact=1),
        idea("useful", excitement=3, impact=5),
    ]
    assert [i.id for i, _ in scoring.rank(ideas, TODAY)] == ["useful", "exciting"]
    assert scoring.score(idea("defaults"), TODAY) == 3.0  # (3 + 3) / M
