"""Credential form validation uses no network or real secrets."""

from urllib.parse import urlencode

import pytest

from nettracker.web.router_credentials import CredentialFormError, parse_credentials


def _body(**overrides: str) -> bytes:
    fields = {"csrf": "test-token", "username": "admin", "password": "synthetic-secret", "confirm": "yes"}
    fields.update(overrides)
    return urlencode(fields).encode()


def test_parse_preserves_password_and_masks_representation() -> None:
    token, credentials = parse_credentials(_body(password=" synthetic+secret "))
    assert token == "test-token"
    assert credentials.username == "admin"
    assert credentials.password.get_secret_value() == " synthetic+secret "
    assert "synthetic+secret" not in repr(credentials)


def test_empty_username_is_supported() -> None:
    _, credentials = parse_credentials(_body(username=""))
    assert credentials.username == ""


@pytest.mark.parametrize("fields", [{"confirm": "no"}, {"password": ""}, {"csrf": ""}, {"username": "x" * 129}, {"password": "x" * 257}, {"password": "secret\nvalue"}])
def test_invalid_values_are_rejected(fields: dict[str, str]) -> None:
    with pytest.raises(CredentialFormError):
        parse_credentials(_body(**fields))


@pytest.mark.parametrize("body", [b"x" * 4097, b"\xff", b"broken", _body() + b"&password=other", _body() + b"&extra=value"])
def test_invalid_encoding_size_or_fields_are_rejected(body: bytes) -> None:
    with pytest.raises(CredentialFormError):
        parse_credentials(body)


def test_errors_do_not_echo_password() -> None:
    with pytest.raises(CredentialFormError) as caught:
        parse_credentials(_body(password="synthetic-secret\n"))
    assert "synthetic-secret" not in str(caught.value)
