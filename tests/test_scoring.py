from datetime import datetime, timedelta

import pytest

from app import scoring as s

NOW = datetime(2026, 10, 21, 12, 0)


def test_new_word_has_no_score():
    assert s.word_score(s.WordState()) is None
    assert s.level(None) == "new"


def test_first_correct_answer_sets_skill_to_one():
    st = s.apply_verdict(s.WordState(), "usage", "correct")
    assert (st.usage, st.translation, st.streak) == (1, None, 1)
    assert s.word_score(st) == 1


def test_first_wrong_answer_stays_at_zero_not_negative():
    st = s.apply_verdict(s.WordState(), "form", "wrong")
    assert st.form == 0 and s.word_score(st) == 0


def test_almost_changes_nothing_but_keeps_streak():
    st = s.WordState(form=5, streak=2)
    after = s.apply_verdict(st, "form", "almost")
    assert after.form == 5 and after.streak == 2


def test_clamped_at_ten():
    st = s.WordState(translation=10)
    assert s.apply_verdict(st, "translation", "correct").translation == 10


def test_word_score_is_rounded_mean_of_answered_skills():
    assert s.word_score(s.WordState(translation=4, form=3)) == 4  # mean 3.5 rounds to 4
    assert s.word_score(s.WordState(translation=2, form=2, usage=3)) == 2


def test_score_delta_matches_displayed_change():
    before = s.WordState(translation=4, form=2)  # 3
    after = s.apply_verdict(before, "form", "wrong")  # 4,1 -> 2.5 -> 2
    assert s.score_delta(before, after) == -1


def test_first_answer_on_a_new_word_counts_from_zero():
    new = s.WordState()
    assert s.score_delta(new, s.apply_verdict(new, "usage", "correct")) == 1
    assert s.score_delta(new, s.apply_verdict(new, "usage", "wrong")) == 0


def test_streak_resets_on_wrong():
    st = s.apply_verdict(s.WordState(form=3, streak=3), "form", "wrong")
    assert st.streak == 0


def test_next_due_doubles_and_caps():
    assert s.next_due(s.WordState(streak=1), "correct", NOW) == NOW + timedelta(days=1)
    assert s.next_due(s.WordState(streak=3), "correct", NOW) == NOW + timedelta(days=4)
    assert s.next_due(s.WordState(streak=20), "correct", NOW) == NOW + timedelta(days=32)
    assert s.next_due(s.WordState(streak=0), "wrong", NOW) == NOW


@pytest.mark.parametrize("score,expected", [(0, "weak"), (3, "weak"), (4, "medium"), (6, "medium"), (7, "strong"), (10, "strong")])
def test_level_buckets(score, expected):
    assert s.level(score) == expected


def test_unknown_skill_or_verdict_fails_loud():
    with pytest.raises(ValueError):
        s.apply_verdict(s.WordState(), "grammar", "correct")
    with pytest.raises(ValueError):
        s.apply_verdict(s.WordState(), "form", "perfect")


@pytest.mark.parametrize("old,new", [("wrong", "correct"), ("correct", "wrong"), ("almost", "correct"), ("correct", "almost")])
def test_revision_equals_grading_the_new_verdict_from_the_same_start(old, new):
    start = s.WordState(translation=3, form=5, usage=2, streak=2)
    graded_old = s.apply_verdict(start, "form", old)
    revised = s.revise_verdict(start, "form", new)
    assert revised == s.apply_verdict(start, "form", new)
    assert graded_old != revised or old == new
