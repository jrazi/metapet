"""Full-screen terminal UI for browsing and growing ideas (`pet ui`, or `pet` alone).

Questions that need several answers (add, promote, refine) and the editor run with the UI
suspended, through the same question flows as the command line.
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable

import click
from rich.text import Text
from textual import events, on
from textual.app import App, ComposeResult, SuspendNotSupported
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Input, Label, Markdown

from metapet import fields, stages, views, wizard
from metapet.model import Idea, IdeaError, Status
from metapet.prompter import Prompter
from metapet.review import EXCITEMENT
from metapet.schema import Schema
from metapet.store import BrokenFile, Store

EMPTY_STORE = "No ideas yet. Press a to add one."
NOTICE_SECONDS = 3
BACK_TO = (Status.SEED, Status.SKETCH, Status.SPEC, Status.BUILDING)
TITLE_MIN = 10
TITLE_DEFAULT = 40  # before the table has a size
SCROLLBAR = 2
NO_MATCH = "No ideas match the filter."
UNREADABLE = "unreadable"
FIX_FIRST = "Fix this file first (press e)."
EMPTY_ANSWER = "Type something, or press Escape to cancel."
STATUS_STYLE = {
    Status.SEED: "green",
    Status.SKETCH: "cyan",
    Status.SPEC: "blue",
    Status.BUILDING: "magenta",
    Status.SHIPPED: "bold yellow",
    Status.SHELVED: "dim",
}


def _mtime(idea: Idea) -> float:
    try:
        return idea.path.stat().st_mtime if idea.path else 0.0
    except OSError:
        return 0.0


def _status_label(item: Idea | BrokenFile) -> str:
    return UNREADABLE if isinstance(item, BrokenFile) else item.status.value


def _key(item: Idea | BrokenFile) -> str:
    """A row's key: the file name without .md (the id, for files named after it)."""
    if isinstance(item, BrokenFile):
        return item.path.stem
    return item.path.stem if item.path else item.id


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
        if not event.value.strip():
            self.query_one(".hint", Label).update(EMPTY_ANSWER)
            return
        self.dismiss(event.value.strip())

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


class ChoicePrompt(ModalScreen[str | None]):
    """Pick one of a few options with the keys 1, 2, 3...; Escape cancels."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, question: str, options: list[str]):
        super().__init__()
        self.question = question
        self.options = options

    def compose(self) -> ComposeResult:
        listed = ", ".join(f"{n} {option}" for n, option in enumerate(self.options, start=1))
        with Vertical(classes="dialog"):
            yield Label(f"{self.question} {listed}", markup=False)
            yield Label(f"Press 1 to {len(self.options)}, or Escape to cancel.", classes="hint")
        yield Footer()

    def on_key(self, event) -> None:
        if event.character and event.character.isdigit():
            index = int(event.character) - 1
            if 0 <= index < len(self.options):
                event.stop()
                self.dismiss(self.options[index])

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


class IdeaTable(DataTable):
    """The idea list; tells the app when its width changes, so titles can be refitted."""

    class WidthChanged(Message):
        pass

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.last_width = 0

    def on_resize(self, event: events.Resize) -> None:
        # The table's own size, not the terminal's: the app's resize comes before layout.
        if event.size.width != self.last_width:
            self.last_width = event.size.width
            self.post_message(self.WidthChanged())


class PetApp(App[None]):
    TITLE = "metapet"
    CSS = """
    #filter { display: none; }
    #ideas { width: 3fr; }
    #preview-pane { width: 2fr; border-left: solid $primary; padding: 0 1; }
    TextPrompt, ScalePrompt, ChoicePrompt { align: center middle; }
    .dialog {
        width: 60; height: auto; padding: 1 2;
        border: round $accent; background: $surface;
    }
    .dialog Label { width: 1fr; }
    .hint { color: $text-muted; }
    """
    # Filter and Quit come first so that a narrow footer still shows them.
    BINDINGS = [
        Binding("slash", "filter", "Filter"),
        Binding("q", "quit", "Quit"),
        Binding("a", "add", "Add"),
        Binding("p", "promote", "Promote"),
        Binding("r", "refine", "Refine"),
        Binding("n", "note", "Note"),
        Binding("s", "shelve", "Shelve"),
        Binding("e", "edit", "Edit"),
        Binding("x", "excitement", "Excite"),
        Binding("escape", "clear_filter", "Clear filter", show=False),
    ]
    ENABLE_COMMAND_PALETTE = False

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
        self.shown: list[Idea | BrokenFile] = []
        self.broken_files: list[BrokenFile] = []
        self.hint_shown = False  # the "Press Enter to skip" hint, shown once per run
        self.last_notice = ""
        self.last_notice_time = 0.0
        self.sessions: list[wizard.Session] = []

    # -- layout ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield FilterInput(placeholder="filter: words, status:spec, tag:cli", id="filter")
        with Horizontal():
            yield IdeaTable(id="ideas", cursor_type="row", zebra_stripes=True)
            with VerticalScroll(id="preview-pane"):
                yield Markdown(id="preview")
        yield Footer()

    def on_mount(self) -> None:
        self.reload()
        self.table.focus()

    @on(IdeaTable.WidthChanged)
    def refit_titles(self) -> None:
        self.fill_table()

    @property
    def table(self) -> DataTable:
        return self.query_one("#ideas", DataTable)

    @property
    def filter_input(self) -> Input:
        return self.query_one("#filter", Input)

    # -- data --------------------------------------------------------------------

    def reload(self, select: str | None = None) -> None:
        """Read the store again and keep the cursor on `select` or the current row."""
        keep = select or self.current_id()
        ideas, broken = self.store.scan()
        if broken and len(broken) != len(self.broken_files):
            count = len(broken)
            self.notify(
                "1 idea file could not be read; it is listed as unreadable. "
                "Press e on it to fix it."
                if count == 1
                else f"{count} idea files could not be read; they are listed as unreadable. "
                "Press e on one to fix it.",
                severity="warning",
            )
        self.broken_files = broken
        # Newest first; among ideas created the same day, the last one changed first.
        self.ideas = sorted(ideas, key=lambda i: (i.created, _mtime(i), i.id), reverse=True)
        self.fill_table(keep)

    def fill_table(self, keep: str | None = None) -> None:
        """Show the ideas that match the filter; titles take the width the rest leaves."""
        table = self.table
        keep = keep or self.current_id()
        row = table.cursor_row
        table.clear(columns=True)
        query = self.filter_input.value
        words = query.casefold().split()
        broken = [b for b in self.broken_files if all(w in b.path.name.casefold() for w in words)]
        self.shown = [*broken, *views.filter_ideas(self.ideas, query)]
        status_width = max([len("status"), *(len(_status_label(item)) for item in self.shown)])
        widths = [status_width, 3, 3, len("effort")]
        # Each column has one cell of padding on both sides; leave room for a scrollbar.
        spare = table.size.width - sum(w + 2 for w in widths) - 2 - SCROLLBAR
        title_width = max(TITLE_MIN, spare if table.size.width else TITLE_DEFAULT)
        table.add_column("title", width=title_width)
        for name, width in zip(("status", "exc", "imp", "effort"), widths, strict=True):
            table.add_column(name, width=width)
        for item in self.shown:
            if isinstance(item, BrokenFile):
                title = Text(item.path.name)
                title.truncate(title_width, overflow="ellipsis")
                table.add_row(title, Text(UNREADABLE, style="bold red"), "", "", "", key=_key(item))
                continue
            title = Text(item.title)
            title.truncate(title_width, overflow="ellipsis")
            table.add_row(
                title,
                Text(item.status.value, style=STATUS_STYLE[item.status]),
                str(item.excitement or ""),
                str(item.impact or ""),
                item.effort.value if item.effort else "",
                key=_key(item),
            )
        keys = [_key(item) for item in self.shown]
        if keep in keys:
            row = keys.index(keep)
        if self.shown:
            table.move_cursor(row=max(0, min(row, len(keys) - 1)))
        self.show_preview()

    def current_item(self) -> Idea | BrokenFile | None:
        row = self.table.cursor_row
        return self.shown[row] if 0 <= row < len(self.shown) else None

    def current(self) -> Idea | None:
        item = self.current_item()
        return item if isinstance(item, Idea) else None

    def current_id(self) -> str | None:
        """The key of the row under the cursor: the file name without .md."""
        item = self.current_item()
        return _key(item) if item is not None else None

    def show_preview(self) -> None:
        item = self.current_item()
        if isinstance(item, BrokenFile):
            text = (
                f"# {item.path.name}\n\nThis file cannot be read: {item.error}\n\n"
                "Press e to fix it in your editor."
            )
        elif item is not None:
            text = views.preview_markdown(item, self.schema)
        else:
            text = NO_MATCH if self.ideas or self.broken_files else EMPTY_STORE
            unknown = views.parse_query(self.filter_input.value).unknown_statuses
            if unknown:
                names = ", ".join(status.value for status in Status)
                text = f"Unknown status: {', '.join(unknown)} ({names})"
        self.query_one("#preview", Markdown).update(text)

    def selected(self) -> Idea | None:
        """The idea under the cursor, read again from its file."""
        item = self.current_item()
        if isinstance(item, BrokenFile):
            self.notify_once(FIX_FIRST)
            return None
        if item is None:
            self.notify_once(EMPTY_STORE if not self.ideas else "No idea selected.")
            return None
        try:
            return Idea.load(item.path) if item.path else item
        except (OSError, IdeaError) as exc:
            self.notify(f"Could not read {item.id}: {exc}", severity="error", markup=False)
            self.reload()
            return None

    def session(self) -> wizard.Session:
        """A question session; the start hint is shown only in the first one that starts."""
        s = wizard.Session(
            self.schema,
            self.prompter(),
            self.store.save,
            self.store.all_tags(),
            started=self.hint_shown,
            exists=self.store.exists,
            same_title=self.store.same_title,
        )
        self.sessions.append(s)
        return s

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

    def action_clear_filter(self) -> None:
        """Escape in the list: clear the filter if there is one."""
        if self.filter_input.value:
            self.action_close_filter()

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
                stages.shelve(idea, reason, self.schema)
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

        now = fields.get(idea, field)
        question = f"How excited are you about {idea.title}?"
        if now:
            question += f" (now {now})"
        self.push_screen(ScalePrompt(question), done)

    # -- actions outside the UI --------------------------------------------------

    def _suspend_and_run(self, fn: Callable[[], None]) -> None:
        try:
            with self.suspend(), contextlib.suppress(KeyboardInterrupt, EOFError):
                _run_in_thread(fn)
        except SuspendNotSupported:
            self.notify("Not supported in this terminal", severity="error")

    def notify_once(self, message: str) -> None:
        """A short notification, not repeated while the same one is still showing."""
        now = time.monotonic()
        if message == self.last_notice and now - self.last_notice_time < NOTICE_SECONDS:
            return
        self.last_notice, self.last_notice_time = message, now
        self.notify(message, timeout=NOTICE_SECONDS, markup=False)

    def outside(self, fn: Callable[[], None], created: Callable[[], bool] = lambda: True) -> None:
        """Run fn with the UI suspended, then report Ctrl-C or editor problems.

        `created` tells whether an idea exists yet, and so whether stopping kept anything.
        """
        problems: list[str] = []

        def guarded() -> None:
            try:
                fn()
            except (KeyboardInterrupt, EOFError):
                if created():
                    problems.append("Stopped. Answers so far are saved.")
            except click.ClickException as exc:
                problems.append(exc.format_message())

        self.run_outside(guarded)
        self.hint_shown = self.hint_shown or any(s.started for s in self.sessions)
        self.sessions.clear()
        for problem in problems:
            self.notify(problem, severity="warning", markup=False)

    def action_add(self) -> None:
        created: list[str] = []

        def fn() -> None:
            s = self.session()
            name = wizard.ask_name(s)
            if name is None:
                return
            idea = self.store.create(name.title, id=name.id, body=name.extra_summary or "")
            created.append(idea.id)
            wizard.new_idea(s, idea, {"title"})
            wizard.continue_stages(s, idea)

        self.outside(fn, created=lambda: bool(created))
        self.reload(created[0] if created else None)
        if not created:
            self.notify_once("Nothing added.")

    def action_promote(self) -> None:
        idea = self.selected()
        if idea is None:
            return
        target = idea.status.next()
        if target is None:
            self.move_back(idea)
            return
        old = idea.status
        result: list[bool] = []
        self.outside(lambda: result.append(wizard.promote(self.session(), idea, target)))
        self.reload(idea.id)
        if result == [False]:
            self.notify("Not promoted.")
        elif result:
            self.notify(f"{idea.id}: {old.value} → {target.value}")

    def move_back(self, idea: Idea) -> None:
        """Bring a shelved or shipped idea back to a stage of the user's choice."""
        old = idea.status
        options = [status.value for status in BACK_TO]

        def done(choice: str | None) -> None:
            if choice is None:
                return
            stages.promote(idea, Status(choice), self.schema)
            self.store.save(idea)
            self.reload(idea.id)
            self.notify(f"{idea.id}: {old.value} → {choice}", markup=False)

        self.push_screen(ChoicePrompt(f"Move {idea.title} back to:", options), done)

    def action_refine(self) -> None:
        idea = self.selected()
        if idea is not None:
            self.outside(lambda: wizard.refine(self.session(), idea, None))
            self.reload(idea.id)

    def action_edit(self) -> None:
        item = self.current_item()
        if item is None:
            self.notify_once(EMPTY_STORE if not self.ideas else "No idea selected.")
            return
        path = item.path
        if path is None:
            return
        key = _key(item)
        self.outside(lambda: click.edit(filename=str(path)))
        # Stay on the same row, whether or not the file can be read now.
        self.reload(key)
