"""Offline schedule validation and non-destructive override preparation."""

import pytest

from nettracker.routers.control import AccessControlError
from nettracker.routers.livebox5_access import override_parameters, parse_schedule

MAC = "02:00:00:00:00:01"


def reply(override: str = "", value: str = "Enable") -> dict[str, object]:
    return {
        "status": True,
        "data": {"scheduleInfo": {"enable": True, "override": override, "value": value}},
    }


@pytest.mark.parametrize(
    ("override", "value", "blocked"),
    [("", "Enable", False), ("", "Disable", True), ("Disable", "Disable", True)],
)
def test_parse_reports_effective_rule(override: str, value: str, blocked: bool) -> None:
    assert parse_schedule(reply(override, value)).blocked is blocked


@pytest.mark.parametrize("payload", [None, [], {}, {"status": False}, {"status": True}])
def test_missing_or_refused_state_is_unknown(payload: object) -> None:
    with pytest.raises(AccessControlError):
        parse_schedule(payload)


@pytest.mark.parametrize(
    ("override", "value"),
    [("Disable", "Enable"), ("Enable", "Disable"), ("unknown", "Enable"), ("", "unknown")],
)
def test_ambiguous_state_is_refused(override: str, value: str) -> None:
    with pytest.raises(AccessControlError):
        parse_schedule(reply(override, value))


def test_release_restores_schedule_instead_of_forcing_access() -> None:
    payload = reply("Disable", "Disable")
    state = parse_schedule(payload)
    parameters = override_parameters(
        MAC, state, blocked=False, protected_macs=frozenset(), confirmed=True
    )
    assert parameters == {"type": "ToD", "ID": MAC, "override": ""}
    assert payload == reply("Disable", "Disable")


def test_block_prepares_only_targeted_override() -> None:
    parameters = override_parameters(
        MAC, parse_schedule(reply()), blocked=True, protected_macs=frozenset(), confirmed=True
    )
    assert parameters == {"type": "ToD", "ID": MAC, "override": "Disable"}


def test_unconfirmed_or_protected_target_is_refused() -> None:
    state = parse_schedule(reply())
    with pytest.raises(AccessControlError):
        override_parameters(MAC, state, blocked=True, protected_macs=frozenset())
    with pytest.raises(AccessControlError):
        override_parameters(
            MAC, state, blocked=True, protected_macs=frozenset({MAC}), confirmed=True
        )


def test_release_does_not_replace_existing_parental_restriction() -> None:
    with pytest.raises(AccessControlError):
        override_parameters(
            MAC,
            parse_schedule(reply("", "Disable")),
            blocked=False,
            protected_macs=frozenset(),
            confirmed=True,
        )
