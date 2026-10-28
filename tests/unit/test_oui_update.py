"""IEEE updates use synthetic bytes and HTTPX MockTransport; no real requests."""

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from nettracker.discovery import oui_update as updater
from nettracker.discovery.oui_registry import load_local_registry

CSV = b"Registry,Assignment,Organization Name\nMA-L,001A2B,Example Devices Inc.\n"


class Chunks(httpx.SyncByteStream):
    def __iter__(self) -> Iterator[bytes]:
        yield CSV[:10]
        yield CSV[10:]


def test_download_uses_only_fixed_get_without_device_data() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert str(request.url) == updater.SOURCE_URL
        assert request.method == "GET"
        assert request.content == b""
        assert request.headers["accept-encoding"] == "identity"
        assert "authorization" not in request.headers
        assert "cookie" not in request.headers
        return httpx.Response(200, content=CSV)

    assert updater.download_registry(transport=httpx.MockTransport(handle)) == CSV
    assert len(seen) == 1


@pytest.mark.parametrize("status", [301, 302, 403, 500])
def test_redirects_and_errors_are_refused(status: int) -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, headers={"Location": "https://invalid.example"})

    with pytest.raises(updater.RegistryUpdateError, match="HTTP"):
        updater.download_registry(transport=httpx.MockTransport(handle))
    assert len(seen) == 1


def test_network_timeout_is_wrapped() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    with pytest.raises(updater.RegistryUpdateError, match="HTTPS"):
        updater.download_registry(transport=httpx.MockTransport(handle))


def test_compressed_response_is_refused() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, headers={"Content-Encoding": "br"}, stream=Chunks())
    )
    with pytest.raises(updater.RegistryUpdateError, match="compressed"):
        updater.download_registry(transport=transport)


@pytest.mark.parametrize("length", ["bad", "-1", "999999999"])
def test_invalid_or_oversized_content_length_is_refused(length: str) -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, headers={"Content-Length": length}, stream=Chunks())
    )
    with pytest.raises(updater.RegistryUpdateError):
        updater.download_registry(transport=transport)


def test_stream_size_is_bounded_without_content_length(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(updater, "MAX_REGISTRY_BYTES", 12)
    transport = httpx.MockTransport(lambda _: httpx.Response(200, stream=Chunks()))
    with pytest.raises(updater.RegistryUpdateError, match="size limit"):
        updater.download_registry(transport=transport)


def test_incomplete_response_is_refused() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, headers={"Content-Length": "1000"}, stream=Chunks())
    )
    with pytest.raises(updater.RegistryUpdateError, match="incomplete"):
        updater.download_registry(transport=transport)


def test_transfer_budget_is_checked_between_chunks() -> None:
    ticks = iter([0.0, 0.0, 31.0])
    transport = httpx.MockTransport(lambda _: httpx.Response(200, stream=Chunks()))
    with pytest.raises(updater.RegistryUpdateError, match="time budget"):
        updater.download_registry(transport=transport, clock=lambda: next(ticks))


@pytest.mark.parametrize("bom", [False, True])
def test_valid_install_is_readable_by_autoload(tmp_path: Path, bom: bool) -> None:
    destination = tmp_path / "data/oui/oui.csv"
    data = (b"\xef\xbb\xbf" if bom else b"") + CSV
    assert updater.install_registry(data, destination) == 1
    assert destination.read_bytes() == data
    assert load_local_registry(destination) == {"001A2B": "Example Devices Inc."}
    assert not list(destination.parent.glob(".oui-*.tmp"))


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"<html>error</html>",
        b"\xff",
        b"Registry,Assignment,Organization Name\n",
        b"Registry,Assignment,Organization Name\nMA-L,001A2B,Private\n",
        CSV + b"MA-L,001A2C,Unexpected,Extra\n",
        CSV + b'MA-L,001A2C,"unterminated\n',
    ],
)
def test_invalid_csv_preserves_previous_file(tmp_path: Path, payload: bytes) -> None:
    destination = tmp_path / "oui.csv"
    destination.write_bytes(CSV)
    with pytest.raises(updater.RegistryUpdateError):
        updater.install_registry(payload, destination)
    assert destination.read_bytes() == CSV
    assert not list(tmp_path.glob(".oui-*.tmp"))


def test_oversized_install_preserves_previous_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "oui.csv"
    destination.write_bytes(CSV)
    monkeypatch.setattr(updater, "MAX_REGISTRY_BYTES", 8)
    with pytest.raises(updater.RegistryUpdateError, match="size limit"):
        updater.install_registry(b"x" * 9, destination)
    assert destination.read_bytes() == CSV


def test_non_csv_destination_is_refused(tmp_path: Path) -> None:
    destination = tmp_path / "database.db"
    destination.write_bytes(b"unchanged")
    with pytest.raises(updater.RegistryUpdateError, match=".csv"):
        updater.install_registry(CSV, destination)
    assert destination.read_bytes() == b"unchanged"


def test_directory_destination_is_refused(tmp_path: Path) -> None:
    destination = tmp_path / "directory.csv"
    destination.mkdir()
    with pytest.raises(updater.RegistryUpdateError, match="directory"):
        updater.install_registry(CSV, destination)


def test_replace_failure_preserves_previous_file_and_cleans_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "oui.csv"
    destination.write_bytes(CSV)

    def fail_replace(self: Path, target: Path) -> Path:
        raise PermissionError("synthetic sharing violation")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(updater.RegistryUpdateError, match="preserved"):
        updater.install_registry(CSV.replace(b"Example", b"Updated"), destination)
    assert destination.read_bytes() == CSV
    assert not list(tmp_path.glob(".oui-*.tmp"))


def test_preview_never_downloads_or_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(updater, "download_registry", lambda: pytest.fail("network attempted"))
    destination = tmp_path / "missing/oui.csv"
    assert updater.main(["--output", str(destination)]) == 0
    assert not destination.parent.exists()


def test_apply_uses_mocked_download(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(updater, "download_registry", lambda: CSV)
    destination = tmp_path / "oui.csv"
    assert updater.main(["--apply", "--output", str(destination)]) == 0
    assert destination.read_bytes() == CSV


def test_apply_error_preserves_previous_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "oui.csv"
    destination.write_bytes(CSV)

    def fail_download() -> bytes:
        raise updater.RegistryUpdateError("synthetic download failure")

    monkeypatch.setattr(updater, "download_registry", fail_download)
    assert updater.main(["--apply", "--output", str(destination)]) == 1
    assert destination.read_bytes() == CSV
