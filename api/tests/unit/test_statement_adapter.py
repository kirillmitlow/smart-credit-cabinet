"""T-373: the binary mock contract, bounded original, no secrets in failures."""

from collections.abc import Iterator

import httpx
import pytest

from app.modules.integrations import scenarios
from tests.unit.test_scenarios_create_adapter import transport

pytestmark = pytest.mark.unit


def test_statement_uses_only_scenario_code_and_server_admin_key(monkeypatch):
    seen = []
    original = b"1CClientBankExchange\r\n\xcf\xf0\xe8\xec\xe5\xf0"

    def handle(request):
        seen.append(request)
        return httpx.Response(200, content=original)

    transport(monkeypatch, handle)
    assert scenarios.bank_statement("garipov", max_bytes=1024) == original
    assert len(seen) == 1
    assert seen[0].url.path == "/api/v1/scenarios/garipov/documents/bank-statement"
    assert dict(seen[0].url.params) == {"months": "12"}
    assert seen[0].headers["X-Admin-Key"]
    assert seen[0].extensions["timeout"]["read"] == 5


@pytest.mark.parametrize("status", [403, 404, 422, 500, 503])
def test_unavailable_generator_never_returns_error_body_as_file(monkeypatch, status):
    transport(monkeypatch, lambda _: httpx.Response(status, content=b"private-admin-key"))
    with pytest.raises(scenarios.ScenariosUnavailableError) as error:
        scenarios.bank_statement("garipov", max_bytes=1024)
    assert "private-admin-key" not in str(error.value)


def test_timeout_is_safe_and_not_automatically_retried(monkeypatch):
    seen = []

    def handle(request):
        seen.append(request)
        raise httpx.ReadTimeout("private-admin-key", request=request)

    transport(monkeypatch, handle)
    with pytest.raises(scenarios.ScenariosUnavailableError) as error:
        scenarios.bank_statement("garipov", max_bytes=1024)
    assert len(seen) == 1
    assert "private-admin-key" not in str(error.value)


def test_oversize_stream_stops_and_closes_without_reading_to_end(monkeypatch):
    class Chunks(httpx.SyncByteStream):
        count = 0
        closed = False

        def __iter__(self) -> Iterator[bytes]:
            for _ in range(100):
                self.count += 1
                yield b"x" * (64 * 1024)

        def close(self) -> None:
            self.closed = True

    stream = Chunks()
    transport(monkeypatch, lambda _: httpx.Response(200, stream=stream))
    with pytest.raises(scenarios.ScenariosUnavailableError):
        scenarios.bank_statement("garipov", max_bytes=64 * 1024)
    assert stream.count == 2
    assert stream.closed
