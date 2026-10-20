"""Allowlist validation uses invented MAC addresses and no network access."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from nettracker.cli import main
from nettracker.config import Settings, load_settings
from nettracker.discovery.known import normalize_known_devices
from nettracker.errors import ConfigError


def test_default_is_empty_and_normalized_values_are_immutable() -> None:
    assert Settings.model_validate({"allowed_subnets": ["192.168.1.0/24"]}).known_devices == ()
    settings = Settings.model_validate(
        {"allowed_subnets": ["192.168.1.0/24"], "known_devices": [" 02-AA-BB-CC-DD-EE "]}
    )
    assert settings.known_devices == ("02:aa:bb:cc:dd:ee",)
    with pytest.raises(ValidationError):
        settings.known_devices = ()


@pytest.mark.parametrize(
    "entries",
    [
        ["invalid"],
        ["00:00:00:00:00:00"],
        ["ff:ff:ff:ff:ff:ff"],
        ["01:11:22:33:44:55"],
        ["33:33:00:00:00:01"],
        ["00:11:22:33:44:55", "00-11-22-33-44-55"],
        ["02:aa:bb:cc:dd:ee", "02-AA-BB-CC-DD-EE"],
        ["192.168.1.2"],
        ["device.local"],
    ],
)
def test_invalid_and_duplicate_addresses_are_rejected(entries: list[str]) -> None:
    with pytest.raises(ValueError):
        normalize_known_devices(entries)
    with pytest.raises(ValidationError, match="known_devices"):
        Settings.model_validate({"allowed_subnets": ["192.168.1.0/24"], "known_devices": entries})


def test_scalar_is_not_an_allowlist() -> None:
    with pytest.raises(ValueError, match="collection"):
        normalize_known_devices("00:11:22:33:44:55")
    with pytest.raises(ValidationError, match="known_devices"):
        Settings.model_validate(
            {"allowed_subnets": ["192.168.1.0/24"], "known_devices": "00:11:22:33:44:55"}
        )


def test_toml_loads_root_allowlist_and_reports_only_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        'allowed_subnets = ["192.168.1.0/24"]\nknown_devices = ["02-AA-BB-CC-DD-EE"]\n',
        encoding="utf-8",
    )
    assert load_settings(config, environ={}).known_devices == ("02:aa:bb:cc:dd:ee",)
    assert main(["check-config", "--config", str(config)]) == 0
    output = capsys.readouterr().out
    assert "known_devices: 1 configured" in output
    assert "02:aa" not in output.lower()
    assert "02-aa" not in output.lower()


def test_invalid_config_never_creates_database(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    database = tmp_path / "absent.db"
    config.write_text(
        'allowed_subnets = ["192.168.1.0/24"]\nknown_devices = ["invalid"]\n'
        f'database_path = "{database.as_posix()}"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="known_devices"):
        load_settings(config, environ={})
    assert main(["scan-once", "--config", str(config)]) == 1
    assert not database.exists()
