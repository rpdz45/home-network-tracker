"""Offline tests for bounded one-time Fing previews."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest

from nettracker.db.identifications import IdentificationError
from nettracker.discovery.fing import FingInventory
from nettracker.web.fing_preview import FingPreviewStore


def inventory() -> FingInventory:
    return FingInventory("test-network", datetime(2026, 1, 1, tzinfo=UTC), (), 0)


def test_preview_is_consumed_once() -> None:
    store = FingPreviewStore()
    original = inventory()
    token = store.replace(original)
    assert store.consume(token) is original
    with pytest.raises(IdentificationError):
        store.consume(token)


def test_replacing_preview_invalidates_old_token() -> None:
    store = FingPreviewStore()
    old_token = store.replace(inventory())
    current = inventory()
    new_token = store.replace(current)
    with pytest.raises(IdentificationError):
        store.consume(old_token)
    assert store.consume(new_token) is current


@pytest.mark.parametrize("bad_token", ["", "wrong", "a" * 65, "é" * 64])
def test_invalid_token_does_not_consume_preview(bad_token: str) -> None:
    store = FingPreviewStore()
    original = inventory()
    token = store.replace(original)
    with pytest.raises(IdentificationError):
        store.consume(bad_token)
    assert store.consume(token) is original


@pytest.mark.parametrize("elapsed", [600.001, -1.0])
def test_expired_or_backwards_clock_discards_preview(elapsed: float) -> None:
    now = [1000.0]
    store = FingPreviewStore(clock=lambda: now[0])
    token = store.replace(inventory())
    now[0] += elapsed
    with pytest.raises(IdentificationError):
        store.consume(token)
    now[0] = 1000.0
    with pytest.raises(IdentificationError):
        store.consume(token)


def test_exact_ten_minute_boundary_is_accepted() -> None:
    now = [1000.0]
    store = FingPreviewStore(clock=lambda: now[0])
    original = inventory()
    token = store.replace(original)
    now[0] += 600.0
    assert store.consume(token) is original


def test_clear_discards_preview() -> None:
    store = FingPreviewStore()
    token = store.replace(inventory())
    store.clear()
    with pytest.raises(IdentificationError):
        store.consume(token)


def test_concurrent_consumers_cannot_replay_preview() -> None:
    store = FingPreviewStore()
    token = store.replace(inventory())

    def attempt() -> bool:
        try:
            store.consume(token)
        except IdentificationError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert sorted(results) == [False, True]
