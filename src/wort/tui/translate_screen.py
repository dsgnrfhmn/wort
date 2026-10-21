"""Translate tab: look up a word (DE or EN), see compact cards, add to your list."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Input, Label, Static

from wort import sentence
from wort.dictionary.lookup import Entry
from wort.render.card import render_card


MAX_PHRASE_WORDS = 30  # same limits as the CLI session
MIN_SENTENCE_WORDS = 3


class WordAdded(Message):
    def __init__(self, entry: Entry) -> None:
        super().__init__()
        self.entry = entry


class ResultCard(Vertical):
    def __init__(self, entry: Entry, in_list: bool) -> None:
        super().__init__(classes="result")
        self.entry = entry
        self.in_list = in_list

    def compose(self) -> ComposeResult:
        yield Static(render_card(self.entry))
        yield Button(
            "✓ In your list" if self.in_list else "+ Add to your list",
            variant="default",
            disabled=self.in_list,
            classes="add",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.app.store.add_word(self.entry.lemma, self.entry.pos, self.entry.id)
        event.button.label = "✓ In your list"
        event.button.disabled = True
        self.post_message(WordAdded(self.entry))


class TranslatePane(Vertical):
    def compose(self) -> ComposeResult:
        yield Input(placeholder="Word in German or English, Enter — search", id="query")
        yield VerticalScroll(id="results")

    def on_mount(self) -> None:
        self.query_one("#query", Input).focus()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "query":
            return
        await self.search(event.value)

    async def search(self, query: str) -> None:
        results = self.query_one("#results", VerticalScroll)
        await results.remove_children()
        query = " ".join(query.split())
        german, english = self.app.dictionary.lookup(query)
        widgets = []
        if not (german or english) and " " in query:  # a phrase or sentence: whole translation, then one card per word
            german, _ = self.app.dictionary.lookup_words(query, MAX_PHRASE_WORDS)
            if german:
                if len(query.split()) >= MIN_SENTENCE_WORDS:
                    widgets.append(Label(sentence.describe(self.app.dictionary, query)))
                widgets.append(Label("One result per word", classes="muted"))
        if not german and not english:
            widgets.append(Label("Nothing found.", classes="muted"))
        for title, entries in (("In German", german), ("From English", english)):
            if entries:
                widgets.append(Label(title, classes="section"))
                for entry in entries:
                    widgets.append(ResultCard(entry, self.app.store.has_word(entry.lemma, entry.pos)))
        await results.mount_all(widgets)
        results.scroll_home(animate=False)
