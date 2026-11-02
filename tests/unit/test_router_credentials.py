"""Credential form validation uses no network or real secrets."""

import secrets
from urllib.parse import urlencode

import pytest

from nettracker.web.router_credentials import CredentialFormError, parse_credentials

CSRF_VALUE = secrets.token_hex(16)
SECRET_VALUE = secrets.token_urlsafe(24)


def _body(**overrides: str) -> bytes:
    fields = {
        "csrf": CSRF_VALUE,
        "username": "admin",
        "password": SECRET_VALUE,
        "confirm": "yes",
    }
    fields.update(overrides)
    return urlencode(fields).encode()


def test_parse_preserves_password_and_masks_representation() -> None:
    value = " " + SECRET_VALUE + "+ "
    token, credentials = parse_credentials(_body(password=value))
    assert token == CSRF_VALUE
    assert credentials.username == "admin"
    assert credentials.password.get_secret_value() == value
    assert SECRET_VALUE not in repr(credentials)


def test_empty_username_is_supported() -> None:
    _, credentials = parse_credentials(_body(username=""))
    assert credentials.username == ""


@pytest.mark.parametrize(
    "fields",
    [
        {"confirm": "no"},
        {"password": ""},
        {"csrf": ""},
        {"username": "x" * 129},
        {"password": "x" * 257},
        {"password": "secret\nvalue"},
    ],
)
def test_invalid_values_are_rejected(fields: dict[str, str]) -> None:
    with pytest.raises(CredentialFormError):
        parse_credentials(_body(**fields))


@pytest.mark.parametrize(
    "body",
    [
        b"x" * 4097,
        b"\xff",
        b"broken",
        _body() + b"&password=other",
        _body() + b"&extra=value",
    ],
)
def test_invalid_encoding_size_or_fields_are_rejected(body: bytes) -> None:
    with pytest.raises(CredentialFormError):
        parse_credentials(body)


def test_errors_do_not_echo_password() -> None:
    with pytest.raises(CredentialFormError) as caught:
        parse_credentials(_body(password=SECRET_VALUE + "\n"))
    assert SECRET_VALUE not in str(caught.value)
