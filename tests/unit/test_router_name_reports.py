"""Snapshot conversion tests use synthetic adapter data, not router traffic."""

import pytest

from nettracker.routers.bbox_session import BboxHost, BboxSnapshot
from nettracker.routers.device_names import MAX_NAMES, RouterName
from nettracker.routers.livebox5 import LiveboxSnapshot
from nettracker.routers.name_reports import bbox_names, livebox_names

MAC = "02:ab:00:00:00:20"
IP = "192.168.1.20"


def test_livebox_conversion_preserves_duplicates_and_missing_names() -> None:
    snapshot = LiveboxSnapshot(
        "Livebox 5",
        None,
        (
            {"PhysAddress": MAC, "IPAddress": IP, "Name": "Salon"},
            {"PhysAddress": MAC, "IPAddress": IP},
        ),
    )
    assert livebox_names(snapshot) == (
        RouterName(MAC.upper(), IP, "Salon"),
        RouterName(MAC.upper(), IP, ""),
    )
    assert snapshot.devices[0]["PhysAddress"] == MAC


def test_bbox_conversion_preserves_duplicates_and_missing_names() -> None:
    snapshot = BboxSnapshot(
        "synthetic",
        None,
        (
            BboxHost(1, "Salon", IP, MAC, True, None),
            BboxHost(2, None, IP, MAC, False, None),
        ),
        True,
    )
    assert bbox_names(snapshot) == (
        RouterName(MAC.upper(), IP, "Salon"),
        RouterName(MAC.upper(), IP, ""),
    )


@pytest.mark.parametrize(
    "device",
    [
        {},
        {"PhysAddress": MAC},
        {"PhysAddress": MAC, "IPAddress": "invalid"},
        {"PhysAddress": "ff:ff:ff:ff:ff:ff", "IPAddress": IP},
    ],
)
def test_livebox_invalid_binding_rejects_batch(device: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        livebox_names(LiveboxSnapshot("Livebox 5", None, (device,)))


def test_bbox_missing_ip_rejects_batch() -> None:
    snapshot = BboxSnapshot("synthetic", None, (BboxHost(1, "Salon", None, MAC, True, None),), True)
    with pytest.raises(ValueError):
        bbox_names(snapshot)


def test_empty_snapshots() -> None:
    assert livebox_names(LiveboxSnapshot("Livebox 5", None, ())) == ()
    assert bbox_names(BboxSnapshot("synthetic", None, (), True)) == ()


def test_livebox_oversized_batch() -> None:
    device = {"PhysAddress": MAC, "IPAddress": IP, "Name": "Salon"}
    with pytest.raises(ValueError):
        livebox_names(LiveboxSnapshot("Livebox 5", None, (device,) * (MAX_NAMES + 1)))


def test_bbox_oversized_batch() -> None:
    host = BboxHost(1, "Salon", IP, MAC, True, None)
    with pytest.raises(ValueError):
        bbox_names(BboxSnapshot("synthetic", None, (host,) * (MAX_NAMES + 1), True))
