"""Tests for configuration loading and validation."""

from pathlib import Path

import pytest

from nettracker.config import Settings, load_settings, parse_dotenv
from nettracker.errors import ConfigError

VALID = 'allowed_subnets = ["192.168.1.0/24"]\n'


def write(tmp_path: Path, text: str, name: str = "config.toml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def load(path: Path, environ: dict[str, str] | None = None) -> Settings:
    return load_settings(path, environ=environ or {})


def test_minimal_config_uses_safe_defaults(tmp_path: Path) -> None:
    settings = load(write(tmp_path, VALID))
    assert [str(network) for network in settings.allowed_subnets] == ["192.168.1.0/24"]
    assert settings.scan.mode == "passive"
    assert settings.alerts.dry_run is True
    assert settings.api.host == "127.0.0.1"
    assert settings.api.token is None
    assert settings.log_level == "INFO"


def test_full_config_values(tmp_path: Path) -> None:
    text = VALID + (
        'database_path = "data.db"\n'
        'log_level = "debug"\n'
        "[scan]\n"
        'mode = "active"\n'
        "interval_seconds = 30\n"
        "[alerts]\n"
        "dry_run = false\n"
        "[api]\n"
        "port = 9000\n"
    )
    settings = load(write(tmp_path, text))
    assert settings.database_path == Path("data.db")
    assert settings.log_level == "DEBUG"
    assert settings.scan.mode == "active"
    assert settings.scan.interval_seconds == 30
    assert settings.alerts.dry_run is False
    assert settings.api.port == 9000


@pytest.mark.parametrize(
    "subnet",
    ["8.8.8.0/24", "192.168.1.5/24", "10.0.0.0/8", "172.32.0.0/16", "not-a-cidr", "fd00::/64"],
)
def test_invalid_subnets_are_refused(tmp_path: Path, subnet: str) -> None:
    with pytest.raises(ConfigError, match="allowed_subnets"):
        load(write(tmp_path, f'allowed_subnets = ["{subnet}"]\n'))


def test_allowed_subnets_is_required(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="allowed_subnets"):
        load(write(tmp_path, 'log_level = "INFO"\n'))


def test_empty_allowed_subnets_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="allowed_subnets"):
        load(write(tmp_path, "allowed_subnets = []\n"))


def test_missing_file_gives_a_helpful_message(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load(tmp_path / "absent.toml")


def test_invalid_toml_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="invalid TOML"):
        load(write(tmp_path, "allowed_subnets = ["))


def test_unknown_keys_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="typo"):
        load(write(tmp_path, VALID + "typo = 1\n"))


def test_scan_interval_has_a_lower_bound(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="interval_seconds"):
        load(write(tmp_path, VALID + "[scan]\ninterval_seconds = 1\n"))


def test_exposed_api_requires_a_token(tmp_path: Path) -> None:
    path = write(tmp_path, VALID + '[api]\nhost = "0.0.0.0"\n')
    with pytest.raises(ConfigError, match=r"api\.token"):
        load(path)


def test_exposed_api_accepts_a_token_from_the_environment(tmp_path: Path) -> None:
    path = write(tmp_path, VALID + '[api]\nhost = "0.0.0.0"\n')
    settings = load(path, {"NETTRACKER_API_TOKEN": "abc123"})
    assert settings.api.token is not None
    assert settings.api.token.get_secret_value() == "abc123"
    assert "abc123" not in repr(settings)


def test_environment_overrides_and_ignores_empty_values(tmp_path: Path) -> None:
    path = write(tmp_path, VALID + 'log_level = "ERROR"\n')
    environ = {
        "NETTRACKER_DATABASE_PATH": "from-env.db",
        "NETTRACKER_LOG_LEVEL": "",
        "NETTRACKER_API_TOKEN": "",
    }
    settings = load(path, environ)
    assert settings.database_path == Path("from-env.db")
    assert settings.log_level == "ERROR"
    assert settings.api.token is None


def test_dotenv_file_is_read_and_real_environment_wins(tmp_path: Path) -> None:
    config = write(tmp_path, VALID)
    dotenv = write(
        tmp_path,
        "# comment\nNETTRACKER_LOG_LEVEL=WARNING\nNETTRACKER_DATABASE_PATH='dotenv.db'\n",
        ".env",
    )
    settings = load_settings(config, environ={"NETTRACKER_LOG_LEVEL": "DEBUG"}, dotenv_path=dotenv)
    assert settings.log_level == "DEBUG"
    assert settings.database_path == Path("dotenv.db")


def test_config_path_can_come_from_the_environment(tmp_path: Path) -> None:
    config = write(tmp_path, VALID, "elsewhere.toml")
    settings = load_settings(environ={"NETTRACKER_CONFIG": str(config)})
    assert len(settings.allowed_subnets) == 1


def test_parse_dotenv_handles_quotes_blank_lines_and_comments() -> None:
    text = "\n# note\nA=1\nB = \"two\"\nnot a pair\nC='3'\nD=\n"
    assert parse_dotenv(text) == {"A": "1", "B": "two", "C": "3", "D": ""}
