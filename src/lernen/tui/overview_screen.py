"""Overview tab: every word you are learning with its mastery, weakest first."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import DataTable, Static

from lernen.exercises import LABELS
from lernen.render.card import MUTED, render_card
from lernen.store import WordStats


def mastery_bar(value: int, width: int = 10) -> Text:
    filled = round(value / 100 * width)
    return Text("█" * filled, style="bold") + Text("░" * (width - filled), style=MUTED) + Text(f" {value:>3}%")


def due_label(due: datetime | None, now: datetime) -> Text:
    if due is None:
        return Text("new", style="italic")
    if due <= now:
        return Text("now", style="bold")
    days = (due - now).total_seconds() / 86400
    return Text(f"in {days:.0f} d" if days >= 1 else f"in {days * 24:.0f} h", style=MUTED)


class PracticeWords(Message):
    def __init__(self, word_ids: set[int]) -> None:
        super().__init__()
        self.word_ids = word_ids


class OverviewPane(Vertical):
    BINDINGS = [
        Binding("p", "practice", "Practice word"),
        Binding("d", "delete", "Delete"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.stats: dict[str, WordStats] = {}
        self._pending_delete: str | None = None

    def compose(self) -> ComposeResult:
        yield Static("", id="summary")
        yield DataTable(id="words", cursor_type="row", zebra_stripes=True)
        yield Static("", id="detail")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Word", "Type", "Mastery", "Attempts", *LABELS.values(), "Review")
        self.refresh_table()

    def refresh_table(self) -> None:
        now = datetime.now()
        stats = self.app.store.all_stats()
        self.stats = {str(s.word.id): s for s in stats}
        table = self.query_one(DataTable)
        table.clear()
        for s in stats:
            cells = [
                Text(s.word.lemma, style="bold"),
                s.word.pos,
                mastery_bar(s.mastery),
                str(s.attempts),
                *[f"{s.by_exercise[k] * 100:.0f}%" if k in s.by_exercise else "·" for k in LABELS],
                due_label(s.due, now),
            ]
            table.add_row(*cells, key=str(s.word.id))
        due = sum(1 for s in stats if s.due is None or s.due <= now)
        avg = round(sum(s.mastery for s in stats) / len(stats)) if stats else 0
        self.query_one("#summary", Static).update(
            Text.assemble(("Words: ", MUTED), (str(len(stats)), "bold"), ("   Average mastery: ", MUTED),
                          (f"{avg}%", "bold"), ("   Due: ", MUTED), (str(due), "bold"),
                          ("   ·  p — practice, d — delete", MUTED))
            if stats else Text("No words yet — add them in the «Translate» tab.", style=MUTED)
        )
        if not stats:
            self.query_one("#detail", Static).update("")

    def _current(self) -> WordStats | None:
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return None
        key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        return self.stats.get(key)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._pending_delete = None
        s = self.stats.get(event.row_key.value) if event.row_key else None
        if s is None:
            return
        entry = self.app.dictionary.find_lemma(s.word.lemma, s.word.pos)
        self.query_one("#detail", Static).update(render_card(entry, max_glosses=3) if entry else "")

    def action_refresh(self) -> None:
        self.refresh_table()

    def action_practice(self) -> None:
        if s := self._current():
            self.post_message(PracticeWords({s.word.id}))

    def action_delete(self) -> None:
        s = self._current()
        if s is None:
            return
        key = str(s.word.id)
        if self._pending_delete != key:
            self._pending_delete = key
            self.app.notify(f"Press «d» again to delete «{s.word.lemma}» with its history.")
            return
        self._pending_delete = None
        self.app.store.remove_word(s.word.id)
        self.app.notify(f"«{s.word.lemma}» deleted.")
        self.refresh_table()
