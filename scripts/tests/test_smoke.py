"""T-515 / TS-001: execute the real Bash script against a small HTTP stand.

The stand asserts request bodies, session cookies and call ordering. Real compose
validation is separate; these tests cover failure paths without issuing real loans.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/smoke.sh"
BASH = shutil.which("bash")
assert BASH is not None, "Bash is required to test smoke.sh"
COMPANY = "00000000-0000-4000-8000-000000000001"
USER = "00000000-0000-4000-8000-000000000002"
APPLICATION = "00000000-0000-4000-8000-000000000003"
OFFER = "00000000-0000-4000-8000-000000000004"
CONTRACT = "00000000-0000-4000-8000-000000000005"
MOCK_ENVS = {
    "SMOKE_REGISTRY_URL": "registry",
    "SMOKE_TAX_URL": "tax",
    "SMOKE_BKI_URL": "bki",
    "SMOKE_BANK_CORE_URL": "bank-core",
    "SMOKE_SCENARIOS_URL": "scenarios",
}


class Stand:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.unready: str | None = None
        self.outcome = "APPROVED"
        self.submitted = False
        self.signed = False
        self.reset_busy = 0
        self.fail_submit = False
        self.submit_count = 0
        self.reset_count = 0
        self.bad_json = False
        self.server: ThreadingHTTPServer

    def reply(self, method: str, path: str, body: Any, cookie: str) -> tuple[int, Any]:
        self.calls.append((method, path))
        if path == "/healthz":
            return 200, "ok\n"
        if path == self.unready:
            return 503, {"status": "not_ready"}
        if path.endswith("/health/ready"):
            return 200, "<html>upstream error</html>" if self.bad_json else {"status": "ok"}
        if path == "/api/health/deps":
            return 200, {"worker": {"stale": False}}
        path = path.removeprefix("/api")
        if path == "/demo/personas/sokolova/reset":
            self.reset_count += 1
            if self.reset_busy:
                self.reset_busy -= 1
                return 409, {"code": "DEMO_RESET_IN_PROGRESS"}
            return 200, {"status": "DONE"}
        if path.startswith("/auth/roles/"):
            assert path == "/auth/roles/001234567887"
            return 200, {"company": {"id": COMPANY}, "people": [{"userId": USER}]}
        if path == "/auth/request-code":
            assert body == {"userId": USER, "companyId": COMPANY}
            return 200, {"requestId": "login-challenge", "demoCode": "123456"}
        if path == "/auth/verify-code":
            assert body == {"requestId": "login-challenge", "code": "123456"}
            return 200, {"activeCompanyId": COMPANY}
        assert "scc_session=test-session" in cookie, "session cookie lost"
        if path == "/wizard/recommendations":
            assert body["answers"]["amountRub"] == 500000
            return 200, {"applicationId": APPLICATION}
        if path == f"/applications/{APPLICATION}":
            status = "DISBURSED" if self.signed else self.outcome if self.submitted else "DRAFT"
            return 200, {"status": status, "version": 7}
        if path.endswith("/draft"):
            assert body == {
                "version": 7,
                "productCode": "EXPRESS",
                "amountRub": 500000,
                "termMonths": 12,
            }
            return 200, {}
        if path.endswith("/consents/sign"):
            assert body == {
                "requestId": "consent-challenge",
                "code": "234567",
                "items": [{"kind": "BKI_COMPANY", "subjectInn": "001234567887"}],
            }
            return 200, {}
        if path.endswith("/consents"):
            items = [{"kind": "BKI_COMPANY", "subjectInn": "001234567887"}]
            if method == "POST":
                assert body == {"items": items, "acceptPepRules": True}
                return 200, {"requestId": "consent-challenge", "demoCode": "234567", "items": items}
            return 200, {
                "allSigned": True,
                "items": [
                    {**items[0], "canSign": True, "status": "PENDING"},
                    {
                        "kind": "PD",
                        "subjectInn": "001234567887",
                        "canSign": True,
                        "status": "SIGNED",
                    },
                    {
                        "kind": "OTHER",
                        "subjectInn": "001000000000",
                        "canSign": False,
                        "status": "PENDING",
                    },
                ],
            }
        if path.endswith("/submit"):
            self.submit_count += 1
            self.submitted = True
            return (503, {"code": "TEST_UNAVAILABLE"}) if self.fail_submit else (200, {})
        if path.endswith("/offer"):
            return 200, {
                "id": OFFER,
                "variants": [
                    {"id": "wrong-choice", "recommended": False},
                    {"id": "recommended-choice", "recommended": True},
                ],
            }
        if path == f"/offers/{OFFER}/accept":
            assert body == {"variantId": "recommended-choice"}
            return 200, {"contract": {"id": CONTRACT}}
        if path == f"/contracts/{CONTRACT}/sign/request":
            assert body == {"agree": True, "acceptPepRules": True}
            return 200, {"requestId": "contract-challenge", "demoCode": "345678"}
        if path == f"/contracts/{CONTRACT}/sign":
            assert body == {"requestId": "contract-challenge", "code": "345678"}
            self.signed = True
            return 200, {}
        raise AssertionError(f"Unexpected route: {method} {path}")

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        url = f"http://127.0.0.1:{self.server.server_port}"
        env = {**os.environ, **{key: f"{url}/{role}" for key, role in MOCK_ENVS.items()}}
        env.pop("SMOKE_DEMO_CODE", None)
        return subprocess.run(  # noqa: S603 - fixed script and arguments supplied by tests only
            [BASH, str(SCRIPT), "--timeout", "2", *args, url],
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )


@pytest.fixture
def stand() -> Iterator[Stand]:
    state = Stand()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: Any) -> None:
            pass

        def handle_request(self) -> None:
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            body = json.loads(raw) if raw else None
            try:
                code, data = state.reply(
                    self.command, self.path, body, self.headers.get("Cookie", "")
                )
            except AssertionError as exc:
                code, data = 500, {"testFailure": str(exc)}
            self.send_response(code)
            if self.path == "/api/auth/verify-code":
                self.send_header("Set-Cookie", "scc_session=test-session; HttpOnly; Path=/")
            self.end_headers()
            self.wfile.write((data if isinstance(data, str) else json.dumps(data)).encode())

        do_GET = do_POST = do_PATCH = do_PUT = handle_request

    state.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=state.server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        state.server.shutdown()
        state.server.server_close()
        thread.join()


def test_ts001_full_smoke_keeps_cookie_and_signs_recommended_offer(stand: Stand) -> None:
    result = stand.run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "APPROVED -> signed -> DISBURSED" in result.stdout
    assert stand.signed
    assert stand.submit_count == 1
    assert stand.reset_count == 1
    assert "123456" not in result.stdout + result.stderr
    assert "test-session" not in result.stdout + result.stderr


def test_quick_checks_all_services_without_writes(stand: Stand) -> None:
    result = stand.run("--quick")
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(stand.calls) == 8
    assert all(method == "GET" for method, _path in stand.calls)
    assert "no data changed" in result.stdout


def test_private_mock_ports_can_be_skipped(stand: Stand) -> None:
    result = stand.run("--quick", "--no-mock-ports")
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(stand.calls) == 3


@pytest.mark.parametrize(
    ("path", "name"),
    [("/tax/health/ready", "mock-tax"), ("/api/health/deps", "worker")],
)
def test_unready_service_fails_with_name_and_no_reset(stand: Stand, path: str, name: str) -> None:
    stand.unready = path
    result = stand.run()
    assert result.returncode == 1
    assert f"{name} not ready" in result.stderr
    assert stand.reset_count == 0


def test_html_with_http_200_is_not_readiness(stand: Stand) -> None:
    stand.bad_json = True
    result = stand.run("--quick")
    assert result.returncode == 1
    assert "api not ready" in result.stderr


def test_reset_retries_only_busy(stand: Stand) -> None:
    stand.reset_busy = 1
    result = stand.run("--timeout", "5")
    assert result.returncode == 0, result.stdout + result.stderr
    assert stand.reset_count == 2


def test_unexpected_decision_fails_before_accepting(stand: Stand) -> None:
    stand.outcome = "MANUAL_REVIEW"
    result = stand.run()
    assert result.returncode == 1
    assert "Expected APPROVED; got MANUAL_REVIEW" in result.stderr
    assert not stand.signed


def test_uncertain_submit_is_not_retried(stand: Stand) -> None:
    stand.fail_submit = True
    result = stand.run()
    assert result.returncode == 1
    assert "HTTP 503 (TEST_UNAVAILABLE)" in result.stderr
    assert stand.submit_count == 1
    assert not stand.signed


@pytest.mark.parametrize(
    ("payload", "key", "expected"),
    [
        (' { "items": [{"id": "wrong"}, {"id": "right"}] } ', "items.1.id", "right"),
        ('{"note":"brace } and comma , and \\"quote\\"", "status":"ok"}', "status", "ok"),
        ('{"title":"Демо\\nтекст","worker":{"stale":false}}', "worker.stale", "false"),
        ('{"items":[{"kind":"BKI"}]}', "items", '[{"kind":"BKI"}]'),
        ('{"version":12}', "version", "12"),
    ],
)
def test_json_reader_handles_nested_values(payload: str, key: str, expected: str) -> None:
    result = subprocess.run(  # noqa: S603 - fixed Bash code; JSON input is passed via environment
        [
            BASH,
            "-eu",
            "-c",
            'source "$1"; json_read "$PAYLOAD" "$KEY"; printf "%s" "$JSON_TEXT"',
            "json-test",
            str(ROOT / "scripts/lib/smoke-json.sh"),
        ],
        env={**os.environ, "PAYLOAD": payload, "KEY": key},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == expected


@pytest.mark.parametrize("payload", ['{"id":1,}', '{"id":1,"id":2}', '{"id":1}junk', "<html>"])
def test_json_reader_rejects_ambiguous_or_malformed_json(payload: str) -> None:
    result = subprocess.run(  # noqa: S603 - fixed Bash code; JSON input is passed via environment
        [
            BASH,
            "-c",
            'source "$1"; json_read "$PAYLOAD" id',
            "json-test",
            str(ROOT / "scripts/lib/smoke-json.sh"),
        ],
        env={**os.environ, "PAYLOAD": payload},
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1
