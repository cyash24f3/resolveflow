import json

import httpx
import pytest

from resolveflow.agent.providers import Provider
from resolveflow.domain.common import DomainError
from resolveflow.settings import get_settings
from resolveflow.storage.models import Run


@pytest.fixture(autouse=True)
def no_provider_pacing_in_protocol_tests(monkeypatch):
    monkeypatch.setattr(get_settings(), "provider_min_interval_seconds", 0)


@pytest.mark.parametrize("kind", ["malformed", "oversized", "parallel", "timeout", "forbidden"])
def test_provider_invalid_output_is_bounded(monkeypatch, kind):
    settings = get_settings()
    monkeypatch.setattr(settings, "provider_enabled", True)
    monkeypatch.setattr(settings, "provider_max_retries", 0)
    real_client = httpx.Client

    def handler(request):
        if kind == "timeout":
            raise httpx.ReadTimeout("private provider data must not leak")
        if kind == "forbidden":
            return httpx.Response(401, text="secret upstream body")
        if kind == "oversized":
            return httpx.Response(200, content=b"x" * 100001)
        if kind == "malformed":
            return httpx.Response(200, json={"choices": [{"message": {"content": "not JSON"}}]})
        tool = {
            "id": "call1",
            "function": {"name": "get_order", "arguments": json.dumps({"order_id": "ORD-1001"})},
        }
        return httpx.Response(200, json={"choices": [{"message": {"tool_calls": [tool, tool]}}]})

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(DomainError) as exc:
        Provider().next(Run(request="damaged", customer_id="C-100", facts={}, clock=None), {})
    assert exc.value.code in {"invalid_model_output", "provider_unavailable"}
    assert "secret" not in exc.value.message and "private" not in exc.value.message


def test_provider_sends_contracts_and_observations(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "provider_enabled", True)
    real_client = httpx.Client
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "test-model-alias",
                "usage": {"total_tokens": 123},
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "upstream-call",
                                    "function": {
                                        "name": "get_order",
                                        "arguments": '{"order_id":"ORD-1001"}',
                                    },
                                }
                            ]
                        }
                    }
                ],
            },
        )

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(handler))
    )
    result = Provider().next(Run(request="damaged", customer_id="C-100", facts={}, clock=None), {})
    assert result["name"] == "get_order" and result["arguments"]["order_id"] == "ORD-1001"
    assert result["metadata"]["usage"]["total_tokens"] == 123
    assert {t["function"]["name"] for t in requests[0]["tools"]} == {
        "finish_investigation",
        "get_order",
        "get_tracking",
        "search_policy",
        "check_resolution_eligibility",
        "create_case",
        "propose_resolution",
        "request_clarification",
    }
    assert "execute_refund" not in str(requests[0])


@pytest.mark.parametrize("message", [[], "not an object", 5])
def test_provider_rejects_wrong_message_types(monkeypatch, message):
    cfg = get_settings()
    monkeypatch.setattr(cfg, "provider_enabled", True)
    monkeypatch.setattr(cfg, "provider_min_interval_seconds", 0)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"choices": [{"message": message}]})
            )
        ),
    )
    with pytest.raises(DomainError) as exc:
        Provider().next(Run(request="status", customer_id="C-100", facts={}, clock=None), {})
    assert exc.value.code == "invalid_model_output"


def test_free_daily_quota_routes_to_explicit_model(monkeypatch):
    from resolveflow.agent import providers

    cfg = get_settings()
    monkeypatch.setattr(cfg, "provider_enabled", True)
    monkeypatch.setattr(cfg, "provider_model", "preferred-free")
    monkeypatch.setattr(cfg, "provider_fallback_models", ["other-free"])
    monkeypatch.setattr(cfg, "provider_min_interval_seconds", 0)
    monkeypatch.setattr(providers, "_model_cooldowns", {})
    requests = []
    real_client = httpx.Client

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if body["model"] == "preferred-free":
            return httpx.Response(
                429,
                json=[
                    {
                        "error": {
                            "details": [
                                {
                                    "violations": [
                                        {
                                            "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                ],
            )
        return httpx.Response(
            200,
            json={
                "model": "other-free",
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "call",
                                    "function": {
                                        "name": "get_order",
                                        "arguments": '{"order_id":"ORD-1001"}',
                                    },
                                }
                            ]
                        }
                    }
                ],
            },
        )

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(handler))
    )
    result = Provider().next(Run(request="status", customer_id="C-100", facts={}, clock=None), {})
    assert [r["model"] for r in requests] == ["preferred-free", "other-free"]
    assert result["metadata"]["model"] == "other-free"
    assert result["metadata"]["free_model_fallback"] is True


def test_each_explicit_fallback_gets_an_attempt_even_without_retries(monkeypatch):
    from resolveflow.agent import providers

    cfg = get_settings()
    monkeypatch.setattr(cfg, "provider_enabled", True)
    monkeypatch.setattr(cfg, "provider_model", "first-free")
    monkeypatch.setattr(cfg, "provider_fallback_models", ["second-free", "third-free"])
    monkeypatch.setattr(cfg, "provider_max_retries", 0)
    monkeypatch.setattr(cfg, "provider_min_interval_seconds", 0)
    monkeypatch.setattr(providers, "_model_cooldowns", {})
    real_client = httpx.Client
    seen = []

    def handler(request):
        model = json.loads(request.content)["model"]
        seen.append(model)
        if model != "third-free":
            return httpx.Response(
                429, json=[{"error": {"details": [{"violations": [{"quotaId": "PerDay"}]}]}}]
            )
        return httpx.Response(
            200,
            json={
                "model": model,
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "call",
                                    "function": {
                                        "name": "get_order",
                                        "arguments": '{"order_id":"ORD-1001"}',
                                    },
                                }
                            ]
                        }
                    }
                ],
            },
        )

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(handler))
    )
    result = Provider().next(
        Run(request="status", customer_id="C-100", facts={}, clock=None),
        {"provider_model": "unconfigured-model"},
    )
    assert result["metadata"]["model"] == "third-free"
    assert seen == ["first-free", "second-free", "third-free"]
