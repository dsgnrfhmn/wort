from textual.widgets import Button, DataTable, Input, Static, TabbedContent

from wort.tui.app import WortApp
from wort.tui.practice_screen import PracticePane
from wort.tui.translate_screen import ResultCard


async def _type(pilot, text: str) -> None:
    for ch in text:
        await pilot.press(ch if ch != " " else "space")


async def test_translate_add_practice_overview(dictionary, store):
    app = WortApp(dictionary, store)
    async with app.run_test(size=(110, 50)) as pilot:
        # Translate: search English, add the top result.
        await _type(pilot, "house")
        await pilot.press("enter")
        await pilot.pause()
        cards = app.query(ResultCard)
        assert [c.entry.lemma for c in cards] == ["Haus", "Gebäude"]
        await pilot.click(cards.first().query_one("Button"))
        await pilot.pause()
        assert store.has_word("Haus", "noun")

        # Practice: one session with the article exercise only.
        await pilot.press("f2")
        await pilot.pause()
        pane = app.query_one(PracticePane)
        pane.query_one("#kind").value = "article"
        await pilot.pause()
        pane.start()
        await pilot.pause()
        assert "Haus" in str(pane.query_one("#prompt", Static).render())
        answer = pane.query_one("#answer", Input)
        answer.value = "das"
        await pilot.press("enter")
        await pilot.pause()
        assert "Correct" in str(pane.query_one("#feedback", Static).render())
        await pilot.press("enter")
        await pilot.pause()
        assert "Session finished: 100%" in str(pane.query_one("#prompt", Static).render())

        # Overview shows the word with its progress.
        await pilot.press("f3")
        await pilot.pause()
        assert app.query_one(TabbedContent).active == "overview"
        table = app.query_one(DataTable)
        assert table.row_count == 1
        assert str(table.get_row_at(0)[0]) == "Haus"
        assert str(table.get_row_at(0)[3]) == "1"


async def test_overview_delete_needs_confirmation(dictionary, store):
    store.add_word("Hund", "noun", None)
    app = WortApp(dictionary, store)
    async with app.run_test(size=(110, 50)) as pilot:
        await pilot.press("f3")
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()
        assert store.has_word("Hund", "noun")
        await pilot.press("d")
        await pilot.pause()
        assert not store.has_word("Hund", "noun")


async def test_sentence_session_without_forms_shows_message_and_recovers(sentence_dictionary, store):
    for lemma, pos in [("Information", "noun"), ("regnen", "verb"), ("einzigartig", "adj")]:
        store.add_word(lemma, pos, None)
    app = WortApp(sentence_dictionary, store)
    async with app.run_test(size=(110, 50)) as pilot:
        await pilot.press("f2")
        await pilot.pause()
        pane = app.query_one(PracticePane)
        pane.query_one("#kind").value = "sentence"
        pane.query_one("#start", Button).active_effect_duration = 0
        await pilot.pause()
        await pilot.click("#start")
        await pilot.pause()
        prompt = str(pane.query_one("#prompt", Static).render())
        assert "No sentence exercises available" in prompt
        assert "forms" in prompt
        assert not pane.awaiting_answer
        assert pane.query_one("#answer", Input).disabled
        assert all(s.attempts == 0 for s in store.all_stats())

        store.add_word("Haus", "noun", None)
        await pilot.click("#start")
        await pilot.pause()
        assert [(word.lemma, ex.kind) for word, ex in pane.session] == [("Haus", "sentence")]
        assert pane.awaiting_answer
        assert not pane.query_one("#answer", Input).disabled
        assert "Haus" in str(pane.query_one("#prompt", Static).render())


async def test_sentence_session_without_words_keeps_add_words_message(dictionary, store):
    app = WortApp(dictionary, store)
    async with app.run_test(size=(110, 50)) as pilot:
        await pilot.press("f2")
        await pilot.pause()
        pane = app.query_one(PracticePane)
        pane.query_one("#kind").value = "sentence"
        await pilot.pause()
        await pilot.click("#start")
        await pilot.pause()
        assert "No words to practice" in str(pane.query_one("#prompt", Static).render())
        assert pane.query_one("#answer", Input).disabled
