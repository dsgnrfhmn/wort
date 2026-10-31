"""Practice tab: a session of mixed exercises over your words, with scoring."""

from __future__ import annotations

from collections import Counter

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Input, Select, Static

from wort.exercises import LABELS, TYPES, Exercise, Result, build_session
from wort.render.card import MUTED, render_card
from wort.store import Word

VERDICT_STYLE = {"correct": ("✔ Correct", "bold"), "almost": ("≈ Almost", "bold italic"), "wrong": ("✘ Wrong", "bold italic reverse")}


class PracticePane(Vertical):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.session: list[tuple[Word, Exercise]] = []
        self.index = 0
        self.results: list[tuple[Word, Exercise, Result]] = []
        self.awaiting_answer = False
        self.checking = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="practice-controls"):
            yield Select(
                [("All exercises", "all")] + [(t.label, kind) for kind, t in TYPES.items()],
                value="all", allow_blank=False, id="kind",
            )
            yield Select([(f"{n} words", n) for n in (5, 10, 20)], value=10, allow_blank=False, id="size")
            yield Button("Start session", id="start")
        yield Static("", id="progress")
        with VerticalScroll(id="practice-body"):
            yield Static("Press «Start session». Words due for review and the weakest words come first.", id="prompt")
            yield Static("", id="choices")
            yield Input(placeholder="Answer, Enter — check", id="answer", disabled=True)
            yield Static("", id="feedback")
            yield Static("", id="card")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start":
            event.stop()
            self.start()

    def start(self, word_ids: set[int] | None = None) -> None:
        kind = self.query_one("#kind", Select).value
        size = self.query_one("#size", Select).value
        self.session = build_session(
            self.app.store, self.app.dictionary, limit=int(size),
            kinds=None if kind == "all" else {kind}, word_ids=word_ids,
        )
        self.index = 0
        self.results = []
        if not self.session:
            if kind == "sentence" and self.app.store.words():
                self._set_idle("No sentence exercises available: these words have no suitable dictionary forms. Try another exercise type.")
            else:
                self._set_idle("No words to practice. Add words in the «Translate» tab.")
            return
        self._show_current()

    def _set_idle(self, message: str) -> None:
        self.awaiting_answer = False
        self.query_one("#progress", Static).update("")
        self.query_one("#prompt", Static).update(message)
        for wid in ("#choices", "#feedback", "#card"):
            self.query_one(wid, Static).update("")
        answer = self.query_one("#answer", Input)
        answer.value = ""
        answer.disabled = True

    def _show_current(self) -> None:
        word, ex = self.session[self.index]
        self.query_one("#progress", Static).update(
            Text.assemble((f"{self.index + 1}/{len(self.session)}", "bold"), "  ·  ", (LABELS[ex.kind], "bold"),
                          "  ·  ", (f"✔ {sum(r.verdict == 'correct' for *_, r in self.results)}", "bold"))
        )
        prompt = Text(ex.prompt, style="bold")
        if ex.hint:
            prompt.append(f"\n({ex.hint})", style=MUTED)
        self.query_one("#prompt", Static).update(prompt)
        choices = "   ".join(f"[{i}] {c}" for i, c in enumerate(ex.choices or [], 1))
        self.query_one("#choices", Static).update(choices)
        self.query_one("#feedback", Static).update("")
        self.query_one("#card", Static).update("")
        answer = self.query_one("#answer", Input)
        answer.disabled = False
        answer.value = ""
        answer.placeholder = "Option number or text, Enter — check" if ex.choices else "Answer, Enter — check"
        answer.focus()
        self.awaiting_answer = True

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "answer" or self.checking:
            return
        event.stop()
        if self.awaiting_answer:
            if not event.value.strip():
                return
            _, ex = self.session[self.index]
            if ex.slow:
                self.checking = True
                self.query_one("#feedback", Static).update(Text("Checking…", style=MUTED))
                self._check_in_thread(ex, event.value)
            else:
                self._apply_result(ex, event.value, ex.check(event.value))
        else:
            self.index += 1
            if self.index < len(self.session):
                self._show_current()
            else:
                self._show_summary()

    @work(thread=True, exclusive=True)
    def _check_in_thread(self, ex: Exercise, answer: str) -> None:
        result = ex.check(answer)
        self.app.call_from_thread(self._apply_result, ex, answer, result)

    def _apply_result(self, ex: Exercise, answer: str, result: Result) -> None:
        self.checking = False
        word, _ = self.session[self.index]
        self.app.store.record(word.id, ex.kind, result.verdict, answer)
        self.results.append((word, ex, result))
        label, style = VERDICT_STYLE[result.verdict]
        text = Text(label, style=style)
        if result.verdict != "correct" or result.feedback:
            text.append(f"   Answer: {result.expected}", style="bold")
        if result.feedback:
            text.append("\n" + result.feedback)
        text.append("\nEnter — next", style=MUTED)
        self.query_one("#feedback", Static).update(text)
        self.query_one("#card", Static).update(render_card(ex.entry, max_glosses=3))
        answer_input = self.query_one("#answer", Input)
        answer_input.value = ""
        answer_input.placeholder = "Enter — next"
        self.awaiting_answer = False

    def _show_summary(self) -> None:
        counts = Counter(r.verdict for *_, r in self.results)
        total = len(self.results)
        score = round(100 * (counts["correct"] + 0.5 * counts["almost"]) / total) if total else 0
        summary = Text(f"Session finished: {score}%\n", style="bold")
        summary.append(f"✔ {counts['correct']}   ≈ {counts['almost']}   ✘ {counts['wrong']}\n\n", style="bold")
        for word, ex, result in self.results:
            _, style = VERDICT_STYLE[result.verdict]
            mastery = self.app.store.stats(word).mastery
            summary.append("● ", style=style)
            summary.append(f"{word.lemma:<20}", style="bold")
            summary.append(f"{LABELS[ex.kind]:<10} mastery {mastery}%\n", style=MUTED)
        self._set_idle("")
        self.query_one("#prompt", Static).update(summary)
        self.query_one("#start", Button).focus()
