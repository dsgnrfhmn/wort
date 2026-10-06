"""The full-screen app: Translate | Practice | Overview."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, TabbedContent, TabPane

from wort.dictionary.lookup import Dictionary
from wort.store import Store
from wort.tui.overview_screen import OverviewPane, PracticeWords
from wort.tui.practice_screen import PracticePane
from wort.tui.translate_screen import TranslatePane, WordAdded


class WortApp(App):
    TITLE = "wort"
    SUB_TITLE = "Deutsch"
    CSS = """
    TabPane { padding: 0 1; }
    #query { margin-bottom: 1; }
    .section { color: $text-muted; text-style: bold; margin-top: 1; }
    .result { height: auto; margin-bottom: 1; }
    .result Button { margin-left: 1; }
    .muted { color: $text-muted; }
    #practice-controls { height: auto; margin-bottom: 1; }
    #practice-controls Select { width: 24; margin-right: 1; }
    #progress { height: auto; margin-bottom: 1; }
    #prompt, #choices, #feedback { height: auto; margin-bottom: 1; }
    #answer { margin-bottom: 1; }
    #summary { height: auto; margin-bottom: 1; }
    #words { height: 1fr; min-height: 6; }
    #detail { height: auto; max-height: 50%; margin-top: 1; }
    """
    BINDINGS = [
        Binding("f1", "show_tab('translate')", "Translate"),
        Binding("f2", "show_tab('practice')", "Practice"),
        Binding("f3", "show_tab('overview')", "Overview"),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self, dictionary: Dictionary, store: Store) -> None:
        super().__init__()
        self.dictionary = dictionary
        self.store = store

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="translate"):
            with TabPane("Translate", id="translate"):
                yield TranslatePane()
            with TabPane("Practice", id="practice"):
                yield PracticePane()
            with TabPane("Overview", id="overview"):
                yield OverviewPane()
        yield Footer()

    def action_show_tab(self, tab: str) -> None:
        # Drop focus first: a focused widget in the old pane would pull the tab back.
        self.screen.set_focus(None)
        self.query_one(TabbedContent).active = tab

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if event.pane.id != event.tabbed_content.active:
            return  # stale event; focusing its pane would switch the tab back
        if event.pane.id == "overview":
            for pane in self.query(OverviewPane):
                pane.refresh_table()
        practice = self.query(PracticePane).first(None)
        if event.pane.id == "practice" and practice and practice.awaiting_answer:
            focus = "#answer"
        else:
            focus = {"translate": "#query", "practice": "#start", "overview": "#words"}[event.pane.id]
        # Focus once the switcher has shown the pane (a hidden widget can't take focus).
        self.call_after_refresh(lambda: [w.focus() for w in self.query(focus)])

    def on_word_added(self, event: WordAdded) -> None:
        self.notify(f"«{event.entry.lemma}» added to your list.")

    def on_practice_words(self, event: PracticeWords) -> None:
        self.action_show_tab("practice")
        self.query_one(PracticePane).start(word_ids=event.word_ids)
