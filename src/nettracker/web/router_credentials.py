"""Validate explicit router credentials without persistence or network access."""

from dataclasses import dataclass
from urllib.parse import parse_qs

from pydantic import SecretStr

MAX_FORM_BYTES = 4096


class CredentialFormError(ValueError):
    """A credential form was rejected without exposing its contents."""


@dataclass(frozen=True)
class RouterCredentials:
    username: str
    password: SecretStr


def parse_credentials(body: bytes) -> tuple[str, RouterCredentials]:
    """Parse a bounded form; the caller must enforce authentication and CSRF.

    The returned CSRF value is untrusted until compared with the server token.
    No credentials are written to disk, logged or sent to a router here.
    """
    if len(body) > MAX_FORM_BYTES:
        raise CredentialFormError("Credential form too large")
    try:
        form = parse_qs(
            body.decode("utf-8"),
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=4,
            encoding="utf-8",
            errors="strict",
        )
    except (ValueError, UnicodeError):
        raise CredentialFormError("Invalid credential form") from None
    if set(form) != {"csrf", "username", "password", "confirm"}:
        raise CredentialFormError("Invalid credential fields")
    if any(len(values) != 1 for values in form.values()):
        raise CredentialFormError("Duplicate credential fields")
    if form["confirm"] != ["yes"]:
        raise CredentialFormError("Explicit confirmation required")
    csrf = form["csrf"][0]
    username = form["username"][0]
    password = form["password"][0]
    if not 1 <= len(csrf) <= 128 or not 1 <= len(password) <= 256:
        raise CredentialFormError("Invalid credential lengths")
    if len(username) > 128:
        raise CredentialFormError("Invalid credential lengths")
    if any(ord(char) < 32 or ord(char) == 127 for char in username + password):
        raise CredentialFormError("Invalid credential characters")
    return csrf, RouterCredentials(username=username, password=SecretStr(password))
