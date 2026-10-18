"""Offline model-contract and explicit-dispatch tests."""

import os
import subprocess
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from arqon_os.gateway.gateway import (
    DuplicateProviderError, InvalidProviderResponseError, ModelGateway,
    ProviderExecutionError, ProviderRegistrationError, UnknownProviderError,
)
from arqon_os.gateway.models import ModelMessage, ModelRequest, ModelResponse, ModelValidationError
from arqon_os.gateway.provider import MockModelProvider


def request(**changes):
    return replace(ModelRequest((ModelMessage("user", "hello world"),), "fixture-model"), **changes)


@pytest.mark.parametrize("changes", [
    {"messages": ()}, {"messages": "hello"}, {"messages": ({"role": "user"},)},
    {"model": ""}, {"model": " "}, {"model": None},
    {"max_tokens": 0}, {"max_tokens": -1}, {"max_tokens": True}, {"max_tokens": 1.5},
    {"temperature": -0.1}, {"temperature": 2.1}, {"temperature": float("nan")},
    {"temperature": float("inf")}, {"temperature": True}, {"temperature": "1"},
])
def test_invalid_request(changes):
    with pytest.raises(ModelValidationError):
        request(**changes)


@pytest.mark.parametrize("role", ["system", "user", "assistant", "tool"])
def test_valid_roles(role):
    assert ModelMessage(role, "text").role == role


@pytest.mark.parametrize("role", ["developer", "", None, 1])
def test_invalid_roles(role):
    with pytest.raises(ModelValidationError):
        ModelMessage(role, "text")


def test_message_immutability_and_defensive_copy():
    message = ModelMessage("user", "original")
    messages = [message]
    req = ModelRequest(messages, "fixture-model")
    messages.clear()
    object.__setattr__(message, "content", "changed")
    assert req.messages == (ModelMessage("user", "original"),)
    assert isinstance(req.messages, tuple)
    with pytest.raises(FrozenInstanceError):
        setattr(req.messages[0], "content", "changed")
    with pytest.raises(FrozenInstanceError):
        setattr(req, "model", "other")


def test_explicit_registration_duplicate_and_unknown():
    gateway = ModelGateway()
    with pytest.raises(UnknownProviderError) as exc:
        gateway.generate("mock", request())
    assert exc.value.code == "UNKNOWN_MODEL_PROVIDER"
    gateway.register_provider("mock", MockModelProvider())
    with pytest.raises(DuplicateProviderError):
        gateway.register_provider("mock", MockModelProvider())
    with pytest.raises(UnknownProviderError):
        gateway.generate("missing", request())
    assert gateway.generate("mock", request()).provider == "mock"


@pytest.mark.parametrize("name,provider", [("", MockModelProvider()), ("mock", object()), (None, MockModelProvider())])
def test_invalid_registration(name, provider):
    with pytest.raises(ProviderRegistrationError):
        ModelGateway().register_provider(name, provider)


@pytest.mark.parametrize("limit,temperature", [(1, 0), (3, 1), (4, 2), (100, 0.5)])
def test_deterministic_mock(limit, temperature):
    gateway = ModelGateway()
    gateway.register_provider("fixture", MockModelProvider())
    req = request(max_tokens=limit, temperature=temperature)
    first = gateway.generate("fixture", req)
    assert first == gateway.generate("fixture", req)
    assert first.content.startswith("MOCK:")
    assert first.model == req.model
    assert first.provider == "mock"
    assert first.input_tokens == 2
    assert first.output_tokens == min(limit, 4)
    assert first.finish_reason == ("length" if limit < 4 else "stop")
    assert "hello" not in first.content


@pytest.mark.parametrize("field,value", [
    ("input_tokens", -1), ("output_tokens", -1), ("input_tokens", True),
    ("output_tokens", 1.5), ("model", ""), ("provider", ""), ("finish_reason", ""),
    ("content", None),
])
def test_invalid_response(field, value):
    valid = ModelResponse("text", "fixture-model", "mock", 0, 1, "stop")
    with pytest.raises(ModelValidationError):
        replace(valid, **{field: value})


def test_zero_token_counts():
    assert ModelResponse("", "fixture-model", "mock", 0, 0, "stop").output_tokens == 0


@pytest.mark.parametrize("response", [
    {"content": "not typed"},
    ModelResponse("text", "substituted-model", "fake", 0, 1, "stop"),
    ModelResponse("text", "fixture-model", "fake", 0, 999, "stop"),
])
def test_bad_provider_response_rejected(response):
    class Fake:
        def generate(self, request):
            return response
    gateway = ModelGateway()
    gateway.register_provider("fake", Fake())
    with pytest.raises(InvalidProviderResponseError):
        gateway.generate("fake", request())


def test_provider_failure_no_retry_fallback_or_secret_exposure():
    calls = []
    class Failing:
        def generate(self, request):
            calls.append("failing")
            raise RuntimeError("API_KEY=private")
    class Other:
        def generate(self, request):
            calls.append("other")
            return MockModelProvider().generate(request)
    gateway = ModelGateway()
    gateway.register_provider("bad", Failing())
    gateway.register_provider("other", Other())
    with pytest.raises(ProviderExecutionError) as exc:
        gateway.generate("bad", request())
    assert calls == ["failing"]
    assert "private" not in str(exc.value.to_dict())
    assert "private" not in str(exc.value)


def test_import_and_mock_have_no_external_effects(tmp_path):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    script = """
import os
import sys
import socket
import subprocess
from collections.abc import Mapping
def deny(*args, **kwargs):
    raise AssertionError("Forbidden external access")
class NoEnvironment(Mapping):
    def __getitem__(self, key): deny()
    def __iter__(self): deny()
    def __len__(self): deny()
os.environ = NoEnvironment()
os.getenv = deny
socket.socket = deny
socket.getaddrinfo = deny
socket.create_connection = deny
subprocess.Popen = deny
def audit(event, args):
    if event == "open":
        mode, flags = args[1], args[2]
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
            isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)
        ):
            deny()
    if event.startswith(("socket.", "subprocess.")) or event in {
        "os.mkdir", "os.remove", "os.rename", "os.rmdir", "os.system",
        "os.fork", "os.posix_spawn", "os.exec", "sqlite3.connect",
    }:
        deny()
sys.addaudithook(audit)
from arqon_os.gateway.models import ModelMessage, ModelRequest
from arqon_os.gateway.provider import MockModelProvider
# Importing the dispatch module must not invoke a model.
original = MockModelProvider.generate
MockModelProvider.generate = deny
from arqon_os.gateway.gateway import ModelGateway
gateway = ModelGateway()
gateway.register_provider("mock", MockModelProvider())
MockModelProvider.generate = original
result = gateway.generate("mock", ModelRequest((ModelMessage("user", "hello"),), "fixture-model"))
assert result.content.startswith("MOCK:")
assert not any(name.startswith("architect_vapt") for name in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []
