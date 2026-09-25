"""The `pet` command-line interface."""

from __future__ import annotations

from typing import Annotated

import click
import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from metapet import paths, stages
from metapet.model import Effort, Idea, Status
from metapet.store import IdeaLookupError, Store

app = typer.Typer(
    help="Capture and grow pet-project ideas.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
console = Console()
err = Console(stderr=True)

STATUS_STYLE = {
    Status.SEED: "green",
    Status.SKETCH: "cyan",
    Status.SPEC: "blue",
    Status.BUILDING: "magenta",
    Status.SHIPPED: "bold yellow",
    Status.SHELVED: "dim",
}


@app.callback()
def main(
    ctx: typer.Context,
    home: Annotated[
        str | None,
        typer.Option("--home", help="Data directory to use (overrides $METAPET_HOME)."),
    ] = None,
) -> None:
    ctx.obj = paths.resolve(home)


# -- helpers -----------------------------------------------------------------


def _store(ctx: typer.Context, *, must_exist: bool = True) -> Store:
    store = Store(ctx.obj)
    if must_exist and not ctx.obj.exists:
        _fail(
            f"No idea store at [bold]{ctx.obj.path}[/] (from {ctx.obj.source}).\n"
            "Run [bold]pet init[/] first."
        )
    return store


def _fail(message: str) -> None:
    err.print(f"[red]error:[/] {message}")
    raise typer.Exit(1)


def _find(store: Store, query: str) -> Idea:
    try:
        return store.find(query)
    except IdeaLookupError as exc:
        if exc.candidates:
            ids = "\n".join(f"  • {i.id}  [dim]{i.title}[/]" for i in exc.candidates)
            _fail(f"{exc}; be more specific:\n{ids}")
        _fail(str(exc))
        raise  # unreachable, keeps type checkers happy


def _status(status: Status) -> str:
    return f"[{STATUS_STYLE[status]}]{status.value}[/]"


def _ideas_table(ideas: list[Idea], extra: dict[str, list[str]] | None = None) -> Table:
    table = Table(box=None, header_style="bold", pad_edge=False)
    table.add_column("id", style="bold")
    table.add_column("title")
    table.add_column("status")
    table.add_column("exc", justify="right")
    table.add_column("effort")
    table.add_column("tags", style="dim")
    table.add_column("created", style="dim")
    for name in extra or {}:
        table.add_column(name, justify="right")
    for row, idea in enumerate(ideas):
        table.add_row(
            idea.id,
            idea.title,
            _status(idea.status),
            str(idea.excitement or ""),
            idea.effort.value if idea.effort else "",
            ", ".join(idea.tags),
            idea.created.isoformat(),
            *[values[row] for values in (extra or {}).values()],
        )
    return table


def _print_idea(idea: Idea) -> None:
    meta = [f"{_status(idea.status)}  [dim]created {idea.created}[/]"]
    if idea.updated:
        meta[0] += f" [dim]· updated {idea.updated}[/]"
    details = []
    if idea.excitement:
        details.append(f"excitement {'★' * idea.excitement}{'☆' * (5 - idea.excitement)}")
    if idea.effort:
        details.append(f"effort {idea.effort.value}")
    if idea.tags:
        details.append("tags " + ", ".join(idea.tags))
    if details:
        meta.append("  ·  ".join(details))
    if idea.repo:
        meta.append(f"repo {idea.repo}")
    if idea.related:
        meta.append("related " + ", ".join(idea.related))
    if idea.shelved_reason:
        meta.append(f"[dim]shelved: {idea.shelved_reason}[/]")
    console.print(
        Panel("\n".join(meta), title=f"[bold]{idea.title}[/]", subtitle=idea.id, expand=False)
    )
    if idea.body.strip():
        console.print(Markdown(idea.body))


# -- setup -------------------------------------------------------------------


@app.command()
def init(
    ctx: typer.Context,
    local: Annotated[
        bool, typer.Option("--local", help="Store ideas in ./data inside this checkout.")
    ] = False,
) -> None:
    """Create the idea store."""
    home: paths.DataHome = ctx.obj
    if local:
        portable = paths.portable_dir()
        if portable is None:
            _fail("--local only works when running from a source checkout.")
        home = paths.DataHome(portable, "portable ./data in checkout")
        ctx.obj = home
    store = Store(home)
    already = home.exists
    store.init()
    verb = "Using existing" if already else "Created"
    console.print(f"{verb} idea store at [bold]{home.path}[/] [dim]({home.source})[/]")


@app.command()
def where(ctx: typer.Context) -> None:
    """Show which data directory is in use, and why."""
    home: paths.DataHome = ctx.obj
    state = "" if home.exists else "  [yellow](not initialized — run `pet init`)[/]"
    console.print(f"{home.path}  [dim]← {home.source}[/]{state}")


# -- capture -----------------------------------------------------------------


@app.command()
def add(
    ctx: typer.Context,
    title: Annotated[str, typer.Argument(help="The idea, in a few words.")],
    tag: Annotated[list[str] | None, typer.Option("--tag", "-t", help="Tag (repeatable).")] = None,
    note: Annotated[str | None, typer.Option("--note", "-m", help="One-line description.")] = None,
) -> None:
    """Capture a seed instantly, without opening an editor."""
    store = _store(ctx)
    idea = store.create(title, tags=list(tag or []), body=note or "")
    console.print(f"[green]+[/] {idea.id}  [dim]{idea.path}[/]")


@app.command()
def new(
    ctx: typer.Context,
    edit: Annotated[bool, typer.Option(help="Open the idea in $EDITOR afterwards.")] = True,
) -> None:
    """Capture an idea interactively."""
    store = _store(ctx)
    title = typer.prompt("Title")
    note = typer.prompt("One-liner", default="", show_default=False)
    tags = typer.prompt("Tags (comma separated)", default="", show_default=False)
    excitement = typer.prompt(
        "Excitement 1-5", default="", show_default=False, type=click.Choice(["", *"12345"])
    )
    effort = typer.prompt(
        "Effort S/M/L/XL",
        default="",
        show_default=False,
        type=click.Choice(["", *[e.value for e in Effort]], case_sensitive=False),
    )
    idea = store.create(
        title,
        body=note,
        tags=[t.strip() for t in tags.split(",") if t.strip()],
        excitement=int(excitement) if excitement else None,
        effort=Effort(effort.upper()) if effort else None,
    )
    console.print(f"[green]+[/] {idea.id}  [dim]{idea.path}[/]")
    if edit:
        click.edit(filename=str(idea.path))


# -- browsing ----------------------------------------------------------------


@app.command("ls")
def list_ideas(
    ctx: typer.Context,
    status: Annotated[
        list[Status] | None, typer.Option("--status", "-s", help="Filter by status (repeatable).")
    ] = None,
    tag: Annotated[list[str] | None, typer.Option("--tag", "-t", help="Filter by tag.")] = None,
    sort: Annotated[
        str, typer.Option(help="Sort by: created, excitement, title.")
    ] = "created",
    all_: Annotated[
        bool, typer.Option("--all", "-a", help="Include shipped and shelved ideas.")
    ] = False,
) -> None:
    """List ideas."""
    ideas = _store(ctx).all()
    if status:
        ideas = [i for i in ideas if i.status in status]
    elif not all_:
        ideas = [i for i in ideas if not i.status.terminal]
    if tag:
        wanted = {t.lower() for t in tag}
        ideas = [i for i in ideas if wanted & {t.lower() for t in i.tags}]
    keys = {
        "created": lambda i: (i.created, i.id),
        "excitement": lambda i: (i.excitement or 0, i.created),
        "title": lambda i: i.title.lower(),
    }
    if sort not in keys:
        _fail(f"unknown sort '{sort}'; choose from: {', '.join(keys)}")
    ideas.sort(key=keys[sort], reverse=sort != "title")
    if not ideas:
        console.print("[dim]No ideas match. Capture one with[/] pet add \"...\"")
        return
    console.print(_ideas_table(ideas))


@app.command()
def show(ctx: typer.Context, idea_id: Annotated[str, typer.Argument(metavar="ID")]) -> None:
    """Show one idea."""
    _print_idea(_find(_store(ctx), idea_id))


@app.command()
def edit(ctx: typer.Context, idea_id: Annotated[str, typer.Argument(metavar="ID")]) -> None:
    """Open an idea in $EDITOR."""
    idea = _find(_store(ctx), idea_id)
    click.edit(filename=str(idea.path))


# -- lifecycle ---------------------------------------------------------------


@app.command()
def promote(
    ctx: typer.Context,
    idea_id: Annotated[str, typer.Argument(metavar="ID")],
    to: Annotated[
        Status | None, typer.Option("--to", help="Target status (default: the next one).")
    ] = None,
) -> None:
    """Move an idea to its next stage, adding that stage's sections."""
    store = _store(ctx)
    idea = _find(store, idea_id)
    target = to or idea.status.next()
    if target is None:
        _fail(f"{idea.id} is {idea.status.value}; pass --to to move it elsewhere.")
    if target == Status.SHELVED:
        _fail("use `pet shelve ID REASON` to shelve an idea.")
    old = idea.status
    stages.move(idea, target, ctx.obj)
    if old == Status.SHELVED:
        idea.shelved_reason = None
    store.save(idea)
    console.print(f"{idea.id}: {_status(old)} → {_status(target)}  [dim]{idea.path}[/]")


@app.command()
def shelve(
    ctx: typer.Context,
    idea_id: Annotated[str, typer.Argument(metavar="ID")],
    reason: Annotated[str, typer.Argument(help="Why you're putting it aside.")],
) -> None:
    """Shelve an idea, keeping the reason for future you."""
    store = _store(ctx)
    idea = _find(store, idea_id)
    stages.move(idea, Status.SHELVED, ctx.obj)
    idea.shelved_reason = reason
    store.save(idea)
    console.print(f"{idea.id}: {_status(Status.SHELVED)}  [dim]{reason}[/]")
