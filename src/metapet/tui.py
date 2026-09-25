"""Full-screen terminal UI for browsing and growing ideas (`pet ui`, or `pet` alone).

Questions that need several answers (add, promote, refine) and the editor run with the UI
suspended, through the same question flows as the command line.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable

import click
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult, SuspendNotSupported
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Input, Label, Markdown

from metapet import fields, stages, views, wizard
from metapet.model import Idea, IdeaError, Status
from metapet.prompter import Prompter
from metapet.review import EXCITEMENT
from metapet.schema import Schema
from metapet.store import Store

EMPTY_STORE = "No ideas yet. Press a to add one."
NO_MATCH = "No ideas match the filter."
STATUS_STYLE = {
    Status.SEED: "green",
    Status.SKETCH: "cyan",
    Status.SPEC: "blue",
    Status.BUILDING: "magenta",
    Status.SHIPPED: "bold yellow",
    Status.SHELVED: "dim",
}


class TextPrompt(ModalScreen[str | None]):
    """Ask for one line of text. Enter submits, Escape cancels."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, question: str):
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.question, markup=False)
            yield Input(id="answer")
            yield Label("Enter to save, Escape to cancel.", classes="hint")
        # Covers the main footer, whose keys do not work while the dialog is open.
        yield Footer()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.dismiss(event.value.strip() or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ScalePrompt(ModalScreen[int | None]):
    """Ask for a number from 1 to 5. The keys 1-5 pick, Escape cancels."""

    BINDINGS = [
        *(Binding(str(n), f"pick({n})", str(n), show=False) for n in range(1, 6)),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, question: str):
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.question, markup=False)
            yield Label("Press 1 to 5, or Escape to cancel.", classes="hint")
        yield Footer()

    def action_pick(self, value: int) -> None:
        self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class FilterInput(Input):
    BINDINGS = [Binding("escape", "app.close_filter", "Close filter")]


def _run_in_thread(fn: Callable[[], None]) -> None:
    """Run fn in a separate thread and wait for it.

    Terminal prompts start their own event loop, which cannot run inside the UI's loop.
    """
    errors: list[BaseException] = []

    def target() -> None:
        try:
            fn()
        except BaseException as exc:  # handed back to the caller below
            errors.append(exc)

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    if errors:
        raise errors[0]


class PetApp(App[None]):
    TITLE = "metapet"
    CSS = """
    #filter { display: none; }
    #ideas { width: 3fr; }
    #preview-pane { width: 2fr; border-left: solid $primary; padding: 0 1; }
    TextPrompt, ScalePrompt { align: center middle; }
    .dialog {
        width: 60; height: auto; padding: 1 2;
        border: round $accent; background: $surface;
    }
    .hint { color: $text-muted; }
    """
    BINDINGS = [
        Binding("a", "add", "Add"),
        Binding("p", "promote", "Promote"),
        Binding("r", "refine", "Refine"),
        Binding("n", "note", "Note"),
        Binding("s", "shelve", "Shelve"),
        Binding("e", "edit", "Edit"),
        Binding("x", "excitement", "Excitement"),
        Binding("slash", "filter", "Filter"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        store: Store,
        schema: Schema,
        *,
        prompter: Callable[[], Prompter],
        run_outside: Callable[[Callable[[], None]], None] | None = None,
    ):
        super().__init__()
        self.store = store
        self.schema = schema
        self.prompter = prompter
        self.run_outside = run_outside or self._suspend_and_run
        self.ideas: list[Idea] = []
        self.shown: list[Idea] = []
        self.broken = 0

    # -- layout ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield FilterInput(placeholder="filter: words, status:spec, tag:cli", id="filter")
        with Horizontal():
            yield DataTable(id="ideas", cursor_type="row", zebra_stripes=True)
            with VerticalScroll(id="preview-pane"):
                yield Markdown(id="preview")
        yield Footer()

    def on_mount(self) -> None:
        self.table.add_columns("id", "title", "status", "exc", "imp", "effort")
        self.reload()
        self.table.focus()

    @property
    def table(self) -> DataTable:
        return self.query_one("#ideas", DataTable)

    @property
    def filter_input(self) -> Input:
        return self.query_one("#filter", Input)

    # -- data --------------------------------------------------------------------

    def reload(self, select: str | None = None) -> None:
        """Read the store again and keep the cursor on `select` or the current idea."""
        keep = select or self.current_id()
        ideas, broken = self.store.scan()
        if broken and len(broken) != self.broken:
            count = len(broken)
            self.notify(
                f"{count} idea file{'' if count == 1 else 's'} could not be read; "
                "run pet check to see why.",
                severity="warning",
            )
        self.broken = len(broken)
        self.ideas = sorted(ideas, key=lambda i: (i.created, i.id), reverse=True)
        self.fill_table(keep)

    def fill_table(self, keep: str | None = None) -> None:
        table = self.table
        row = table.cursor_row
        table.clear()
        self.shown = views.filter_ideas(self.ideas, self.filter_input.value)
        for idea in self.shown:
            table.add_row(
                Text(idea.id),
                Text(idea.title),
                Text(idea.status.value, style=STATUS_STYLE[idea.status]),
                str(idea.excitement or ""),
                str(idea.impact or ""),
                idea.effort.value if idea.effort else "",
                key=idea.id,
            )
        ids = [idea.id for idea in self.shown]
        if keep in ids:
            row = ids.index(keep)
        if self.shown:
            table.move_cursor(row=max(0, min(row, len(ids) - 1)))
        self.show_preview()

    def current(self) -> Idea | None:
        row = self.table.cursor_row
        return self.shown[row] if 0 <= row < len(self.shown) else None

    def current_id(self) -> str | None:
        idea = self.current()
        return idea.id if idea else None

    def show_preview(self) -> None:
        idea = self.current()
        if idea is not None:
            text = views.preview_markdown(idea)
        else:
            text = NO_MATCH if self.ideas else EMPTY_STORE
        self.query_one("#preview", Markdown).update(text)

    def selected(self) -> Idea | None:
        """The idea under the cursor, read again from its file."""
        idea = self.current()
        if idea is None:
            self.notify("No idea selected.")
            return None
        try:
            return Idea.load(idea.path) if idea.path else idea
        except (OSError, IdeaError) as exc:
            self.notify(f"Could not read {idea.id}: {exc}", severity="error", markup=False)
            self.reload()
            return None

    def session(self) -> wizard.Session:
        return wizard.Session(self.schema, self.prompter(), self.store.save, self.store.all_tags())

    # -- events ------------------------------------------------------------------

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self.show_preview()

    @on(Input.Changed, "#filter")
    def filter_changed(self) -> None:
        self.fill_table(self.current_id())

    @on(Input.Submitted, "#filter")
    def filter_submitted(self) -> None:
        self.table.focus()

    def action_filter(self) -> None:
        self.filter_input.display = True
        self.filter_input.focus()

    def action_close_filter(self) -> None:
        self.filter_input.value = ""
        self.filter_input.display = False
        self.table.focus()

    # -- quick actions -----------------------------------------------------------

    def action_note(self) -> None:
        idea = self.selected()
        if idea is None:
            return

        def done(text: str | None) -> None:
            if text:
                fields.add_note(idea, self.schema, text)
                self.store.save(idea)
                self.reload(idea.id)

        self.push_screen(TextPrompt(f"Note for {idea.title}:"), done)

    def action_shelve(self) -> None:
        idea = self.selected()
        if idea is None:
            return
        if idea.status == Status.SHELVED:
            self.notify(f"{idea.id} is already shelved.")
            return

        def done(reason: str | None) -> None:
            if reason:
                stages.move(idea, Status.SHELVED, self.schema)
                idea.shelved_reason = reason
                self.store.save(idea)
                self.reload()
                self.notify(f"{idea.id} shelved. Type status:shelved in the filter to see it.")

        self.push_screen(TextPrompt(f"Why are you shelving {idea.title}?"), done)

    def action_excitement(self) -> None:
        idea = self.selected()
        if idea is None:
            return
        try:
            field = self.schema.field("excitement", labels=False)
        except KeyError:
            field = EXCITEMENT

        def done(value: int | None) -> None:
            if value is not None and value != fields.get(idea, field):
                fields.put(idea, field, value, self.schema.section_order)
                idea.touch()
                self.store.save(idea)
                self.reload(idea.id)

        self.push_screen(ScalePrompt(f"How excited are you about {idea.title}?"), done)

    # -- actions outside the UI --------------------------------------------------

    def _suspend_and_run(self, fn: Callable[[], None]) -> None:
        try:
            with self.suspend(), contextlib.suppress(KeyboardInterrupt):
                _run_in_thread(fn)
        except SuspendNotSupported:
            self.notify("Not supported in this terminal", severity="error")

    def outside(self, fn: Callable[[], None]) -> None:
        """Run fn with the UI suspended, then report Ctrl-C or editor problems."""
        problems: list[str] = []

        def guarded() -> None:
            try:
                fn()
            except KeyboardInterrupt:
                problems.append("Stopped. Answers so far are saved.")
            except click.ClickException as exc:
                problems.append(exc.format_message())

        self.run_outside(guarded)
        for problem in problems:
            self.notify(problem, severity="warning", markup=False)

    def action_add(self) -> None:
        created: list[str] = []

        def fn() -> None:
            s = self.session()
            title = wizard.ask_title(s)
            idea = self.store.create(title)
            created.append(idea.id)
            wizard.new_idea(s, idea, {"title"})
            wizard.continue_stages(s, idea)

        self.outside(fn)
        self.reload(created[0] if created else None)

    def action_promote(self) -> None:
        idea = self.selected()
        if idea is None:
            return
        target = idea.status.next()
        if target is None:
            self.notify(f"{idea.id} is {idea.status.value}; use pet promote ID --to STAGE.")
            return
        old = idea.status
        result: list[bool] = []
        self.outside(lambda: result.append(wizard.promote(self.session(), idea, target)))
        self.reload(idea.id)
        if result == [False]:
            self.notify("Not promoted.")
        elif result:
            self.notify(f"{idea.id}: {old.value} → {target.value}")

    def action_refine(self) -> None:
        idea = self.selected()
        if idea is not None:
            self.outside(lambda: wizard.refine(self.session(), idea, None))
            self.reload(idea.id)

    def action_edit(self) -> None:
        idea = self.selected()
        if idea is not None and idea.path is not None:
            path = str(idea.path)
            self.outside(lambda: click.edit(filename=path))
            self.reload(idea.id)
