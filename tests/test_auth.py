import pytest

from app import auth


def test_password_roundtrip_and_wrong_password():
    h = auth.hash_password("correct horse battery")
    assert auth.verify_password(h, "correct horse battery")
    assert not auth.verify_password(h, "wrong horse battery")


def test_missing_user_never_verifies():
    assert not auth.verify_password(None, "anything at all, really")


def test_password_length_limits():
    with pytest.raises(ValueError):
        auth.hash_password("short")
    with pytest.raises(ValueError):
        auth.hash_password("x" * 201)
    assert not auth.verify_password(auth.hash_password("a" * 12), "a" * 5000)


def test_token_hash_is_stable_and_not_the_token():
    t = auth.new_token()
    assert auth.token_hash(t) == auth.token_hash(t) != t
    assert auth.new_token() != t


def test_throttle_blocks_after_limit_and_expires():
    now = [0.0]
    th = auth.LoginThrottle(limit=3, window=60, clock=lambda: now[0])
    for _ in range(3):
        assert not th.blocked("anna")
        th.fail("anna")
    assert th.blocked("anna") and not th.blocked("ben")
    now[0] = 61
    assert not th.blocked("anna")
    th.fail("anna"); th.reset("anna")
    assert not th.blocked("anna")
