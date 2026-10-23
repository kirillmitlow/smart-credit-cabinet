"""Сценарии: ключ/время ожидания/отказ провайдера, без передачи приватного ответа наружу."""

import httpx
import pytest

from app.modules.integrations import scenarios

pytestmark = pytest.mark.unit


def transport(monkeypatch, handler):
    real_client = httpx.Client

    def client(**kwargs):
        return real_client(**kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "Client", client)


def test_create_forwards_key_and_json_without_altering_spec(monkeypatch):
    captured = []

    def handle(request):
        captured.append(request)
        return httpx.Response(
            201,
            json={
                "code": "custom",
                "status": "APPLIED",
                "private": "only returned to demo service",
            },
        )

    transport(monkeypatch, handle)
    spec = {"title": "Example", "company": {"form": "IP"}}
    result = scenarios.create_scenario(spec, idempotency_key="same-key")
    assert result["code"] == "custom"
    request = captured[0]
    assert request.url.path == "/api/v1/scenarios"
    assert request.headers["Idempotency-Key"] == "same-key"
    assert request.headers["X-Admin-Key"]
    assert request.extensions["timeout"]["read"] == 120
    assert b'"form":"IP"' in request.content


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (422, "VALIDATION_ERROR"),
        (409, "SCENARIO_EXISTS"),
        (409, "SCENARIO_INN_EXISTS"),
        (409, "IDEMPOTENCY_KEY_REUSED"),
    ],
)
def test_create_returns_only_allowlisted_public_rejection(monkeypatch, status, code):
    transport(
        monkeypatch,
        lambda request: httpx.Response(status, json={"code": code, "detail": "private-admin-key"}),
    )
    with pytest.raises(scenarios.ScenarioRejectedError) as error:
        scenarios.create_scenario({}, idempotency_key="key")
    assert error.value.status == status
    assert error.value.code == code
    assert "private-admin-key" not in str(error.value)


@pytest.mark.parametrize("body", [{"status": "PARTIAL"}, ["bad-schema"], {"status": "APPLIED"}])
def test_unconfirmed_create_is_not_success(monkeypatch, body):
    status = 502 if body == {"status": "APPLIED"} else 201
    transport(monkeypatch, lambda request: httpx.Response(status, json=body))
    with pytest.raises(scenarios.ScenariosUnavailableError):
        scenarios.create_scenario({}, idempotency_key="key")


def test_timeout_hides_request_details_and_does_not_repeat_post(monkeypatch):
    requests = []

    def handle(request):
        requests.append(request)
        raise httpx.ReadTimeout("private-admin-key", request=request)

    transport(monkeypatch, handle)
    with pytest.raises(scenarios.ScenariosUnavailableError) as error:
        scenarios.create_scenario({}, idempotency_key="key")
    assert len(requests) == 1
    assert "private-admin-key" not in str(error.value)
