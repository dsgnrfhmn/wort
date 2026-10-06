from datetime import datetime, timedelta

from wort.srs import SrsState, mastery, review

NOW = datetime(2026, 10, 3, 12, 0)


def test_sm2_intervals_grow_and_reset():
    s = review(SrsState(), "correct", NOW)
    assert s.interval == 1.0
    s = review(s, "correct", NOW)
    assert s.interval == 3.0
    s = review(s, "correct", NOW)
    assert s.interval > 3.0
    s = review(s, "wrong", NOW)
    assert (s.interval, s.reps, s.due) == (0.0, 0, NOW)


def test_mastery():
    assert mastery([], 0) == 0
    assert mastery(["correct"] * 10, 30) == 100
    assert mastery(["wrong", "correct", "correct"], 1) < mastery(["correct", "correct", "wrong"], 1)


def test_store_roundtrip(store):
    w = store.add_word("Haus", "noun", 1, now=NOW)
    assert store.has_word("Haus", "noun")
    assert store.add_word("Haus", "noun", 2, now=NOW).id == w.id  # no duplicates
    store.record(w.id, "article", "correct", "das", now=NOW)
    store.record(w.id, "forms", "wrong", "Hauser", now=NOW)
    st = store.stats(w)
    assert st.attempts == 2
    assert st.by_exercise == {"article": 1.0, "forms": 0.0}
    store.remove_word(w.id)
    assert store.words() == []


def test_session_prefers_due_and_weak_words(store):
    a = store.add_word("Haus", "noun", None, now=NOW)
    b = store.add_word("Hund", "noun", None, now=NOW)
    c = store.add_word("Katze", "noun", None, now=NOW)
    for _ in range(3):
        store.record(a.id, "translate", "correct", now=NOW)
    store.record(b.id, "translate", "wrong", now=NOW)
    order = [w.lemma for w in store.session_words(now=NOW + timedelta(hours=1))]
    assert order[-1] == "Haus"  # learned and not due yet
    assert set(order[:2]) == {"Hund", "Katze"}
