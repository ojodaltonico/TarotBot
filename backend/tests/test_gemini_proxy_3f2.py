import os
import sys
from types import ModuleType, SimpleNamespace

import pytest

from app.ai.gemini_provider import GeminiProvider
from app.core.config import Settings


class MockClient:
    def __init__(self):
        self.models = self


def install_sdk(monkeypatch):
    captured = {}

    def factory(*, api_key, http_options=None):
        captured["api_key"] = api_key
        captured["http_options"] = http_options
        return MockClient()

    google = ModuleType("google")
    google.genai = SimpleNamespace(Client=factory)
    monkeypatch.setitem(sys.modules, "google", google)
    return captured


@pytest.mark.parametrize("trust_env_proxy", [True, False])
def test_proxy_policy_is_scoped_to_google_genai_httpx_client(monkeypatch, trust_env_proxy):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:8080")
    monkeypatch.setenv("ALL_PROXY", "http://proxy.invalid:8080")
    captured = install_sdk(monkeypatch)

    GeminiProvider(api_key="test-key", model="test-model", trust_env_proxy=trust_env_proxy)

    assert captured["http_options"] == {"client_args": {"trust_env": trust_env_proxy}}
    assert os.environ["HTTP_PROXY"] == "http://proxy.invalid:8080"
    assert os.environ["HTTPS_PROXY"] == "http://proxy.invalid:8080"
    assert os.environ["ALL_PROXY"] == "http://proxy.invalid:8080"


@pytest.mark.parametrize("trust_env_proxy", [True, False])
def test_proxy_policy_needs_no_proxy_variables(monkeypatch, trust_env_proxy):
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("ALL_PROXY", raising=False)
    captured = install_sdk(monkeypatch)

    GeminiProvider(api_key="test-key", model="test-model", trust_env_proxy=trust_env_proxy)

    assert captured["http_options"]["client_args"]["trust_env"] is trust_env_proxy


def test_direct_connection_is_the_safe_default():
    assert Settings().ai_trust_env_proxy is False
