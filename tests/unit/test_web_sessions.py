"""Deterministic, network-free tests for the standalone session store."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from nettracker.web.sessions import SessionCapacityError, SessionStore


def test_sessions_are_distinct_and_revocation_is_isolated() -> None:
    store = SessionStore()
    first, second = store.issue(), store.issue()
    assert first != second
    assert len(first) == 43
    assert store.resolve(first) == first
    store.revoke(first)
    store.revoke(first)
    assert store.resolve(first) is None
    assert store.resolve(second) == second


def test_absolute_expiry_and_capacity_recovery() -> None:
    now = [0.0]
    store = SessionStore(ttl=10, capacity=1, clock=lambda: now[0])
    token = store.issue()
    now[0] = 9
    assert store.resolve(token) == token
    with pytest.raises(SessionCapacityError):
        store.issue()
    now[0] = 10
    assert store.resolve(token) is None
    assert store.resolve(store.issue()) is not None


def test_issue_prunes_expired_sessions() -> None:
    now = [0.0]
    store = SessionStore(ttl=1, capacity=1, clock=lambda: now[0])
    old = store.issue()
    now[0] = 1
    new = store.issue()
    assert store.resolve(old) is None
    assert store.resolve(new) == new


@pytest.mark.parametrize("token", [None, "", "dashboard-token", "a" * 43, "a" * 10000])
def test_unknown_and_malformed_tokens(token: str | None) -> None:
    assert SessionStore().resolve(token) is None


@pytest.mark.parametrize("ttl", [0, -1, float("inf"), float("nan")])
def test_invalid_lifetime(ttl: float) -> None:
    with pytest.raises(ValueError):
        SessionStore(ttl=ttl)


@pytest.mark.parametrize("capacity", [0, -1, True, 1.5])
def test_invalid_capacity(capacity: int) -> None:
    with pytest.raises(ValueError):
        SessionStore(capacity=capacity)


def test_concurrent_capacity_is_enforced() -> None:
    store = SessionStore(capacity=4)

    def attempt(_: int) -> str | None:
        try:
            return store.issue()
        except SessionCapacityError:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        tokens = [token for token in pool.map(attempt, range(32)) if token is not None]
    assert len(tokens) == len(set(tokens)) == 4
