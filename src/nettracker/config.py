"""Configuration loading and validation.

The configuration lives in a TOML file. A few values (API token, database path, log level)
can be overridden with environment variables, optionally read from a ``.env`` file.
"""

import os
import tomllib
from collections.abc import Mapping
from ipaddress import IPv4Network, ip_address
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

from nettracker.errors import ConfigError

RFC1918_NETWORKS = (
    IPv4Network("10.0.0.0/8"),
    IPv4Network("172.16.0.0/12"),
    IPv4Network("192.168.0.0/16"),
)
MIN_PREFIX_LENGTH = 16
DEFAULT_CONFIG_NAME = "config.toml"
CONFIG_ENV_VAR = "NETTRACKER_CONFIG"
ENV_OVERRIDES: dict[str, tuple[str, ...]] = {
    "NETTRACKER_API_TOKEN": ("api", "token"),
    "NETTRACKER_DATABASE_PATH": ("database_path",),
    "NETTRACKER_LOG_LEVEL": ("log_level",),
}


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ScanSettings(_Model):
    """Discovery settings. Passive mode (system ARP table) is the default."""

    mode: Literal["passive", "active"] = "passive"
    interval_seconds: int = Field(default=60, ge=10, le=86_400)


class AlertSettings(_Model):
    """Alert settings. Dry-run is the default: nothing is sent until it is turned off."""

    dry_run: bool = True


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


class ApiSettings(_Model):
    """Dashboard and API settings. Listens on loopback unless a token is configured."""

    host: str = "127.0.0.1"
    port: int = Field(default=8080, ge=1, le=65_535)
    token: SecretStr | None = None

    @model_validator(mode="after")
    def require_token_when_exposed(self) -> Self:
        has_token = self.token is not None and bool(self.token.get_secret_value())
        if not _is_loopback(self.host) and not has_token:
            raise ValueError("api.token is required when api.host is not a loopback address")
        return self


class Settings(_Model):
    """Validated application settings."""

    allowed_subnets: list[IPv4Network] = Field(min_length=1)
    database_path: Path = Path("nettracker.db")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    scan: ScanSettings = Field(default_factory=ScanSettings)
    alerts: AlertSettings = Field(default_factory=AlertSettings)
    api: ApiSettings = Field(default_factory=ApiSettings)

    @field_validator("log_level", mode="before")
    @classmethod
    def normalise_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("allowed_subnets")
    @classmethod
    def check_subnets(cls, value: list[IPv4Network]) -> list[IPv4Network]:
        for network in value:
            if not any(network.subnet_of(private) for private in RFC1918_NETWORKS):
                raise ValueError(
                    f"{network} is not a private RFC 1918 range "
                    "(10.0.0.0/8, 172.16.0.0/12 or 192.168.0.0/16)"
                )
            if network.prefixlen < MIN_PREFIX_LENGTH:
                raise ValueError(
                    f"{network} is too large: use a prefix of /{MIN_PREFIX_LENGTH} or longer"
                )
        return value


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse simple ``KEY=VALUE`` lines. Comments and blank lines are ignored."""
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _apply_env(data: dict[str, Any], env: Mapping[str, str]) -> None:
    for name, path in ENV_OVERRIDES.items():
        value = env.get(name, "")
        if not value:
            continue
        target = data
        for part in path[:-1]:
            child = target.setdefault(part, {})
            if not isinstance(child, dict):
                raise ConfigError(f"'{part}' must be a table in the config file")
            target = child
        target[path[-1]] = value


def _format_errors(path: Path, exc: ValidationError) -> str:
    lines = [f"invalid configuration in {path}:"]
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "<root>"
        message = error["msg"].removeprefix("Value error, ")
        lines.append(f"  - {location}: {message}")
    return "\n".join(lines)


def load_settings(
    path: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    dotenv_path: Path | None = None,
) -> Settings:
    """Load and validate the configuration.

    Precedence for overridable values: real environment, then ``.env`` file, then TOML file.
    """
    env: dict[str, str] = {}
    if dotenv_path is not None and dotenv_path.is_file():
        try:
            env.update(parse_dotenv(dotenv_path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError) as exc:
            raise ConfigError(f"cannot read {dotenv_path}: {exc}") from exc
    env.update(os.environ if environ is None else environ)

    if path is not None:
        config_path = path
    elif env.get(CONFIG_ENV_VAR):
        config_path = Path(env[CONFIG_ENV_VAR])
    else:
        config_path = Path(DEFAULT_CONFIG_NAME)

    try:
        raw = config_path.read_bytes()
    except FileNotFoundError as exc:
        raise ConfigError(
            f"config file not found: {config_path} (copy config.example.toml to config.toml)"
        ) from exc
    except OSError as exc:
        raise ConfigError(f"cannot read {config_path}: {exc}") from exc

    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"invalid TOML in {config_path}: {exc}") from exc

    _apply_env(data, env)
    try:
        return Settings.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(_format_errors(config_path, exc)) from exc
