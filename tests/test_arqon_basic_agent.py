"""Offline lifecycle and persistence checks for the bounded agent."""

from dataclasses import FrozenInstanceError
from pathlib import Path
import os
import subprocess
import sys

import pytest

from arqon_os.agents import BasicAgent, InvalidAgentTaskError
from arqon_os.core.results import RunStatus
from arqon_os.gateway.gateway import ModelGateway, ModelTimeoutError
from arqon_os.gateway.models import ModelMessage, ModelRequest, ModelValidationError
from arqon_os.gateway.provider import MockModelProvider
from arqon_os.runtime.engine import AgentRuntime
from arqon_os.runtime.storage import SQLiteRunStore, RunStorageError


class RecordingProvider(MockModelProvider):
    def generate(self, request):
        self.request = request
        return super().generate(request)


class BrokenProvider:
    def generate(self, request):
        raise RuntimeError("credential=DO_NOT_EXPOSE")


def gateway_for(provider=None):
    gateway = ModelGateway()
    gateway.register_provider("mock", provider or MockModelProvider())
    return gateway


def test_success_and_bounded_request():
    runtime = AgentRuntime()
    provider = RecordingProvider()
    result = BasicAgent(runtime, gateway_for(provider)).run("Hello")
    assert result.status is RunStatus.COMPLETED
    assert result.response == "MOCK: deterministic offline response."
    assert (result.provider, result.model, result.error_code) == ("mock", "mock-model", None)
    assert runtime.get_run(result.run_id).status is result.status
    assert [m.role for m in provider.request.messages] == ["system", "user"]
    assert provider.request.messages[1].content == "Hello"
    assert provider.request.max_tokens == 512
    assert provider.request.temperature == 0.0
    with pytest.raises(FrozenInstanceError):
        result.response = "changed"


@pytest.mark.parametrize("task", ["", " \n\t", "x" * 4001, None, 123])
def test_invalid_task_creates_no_run(task, monkeypatch):
    runtime = AgentRuntime()
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid input created a run")
    monkeypatch.setattr(runtime, "create_run", forbidden)
    with pytest.raises(InvalidAgentTaskError):
        BasicAgent(runtime, gateway_for()).run(task)


def test_maximum_task_and_no_history():
    provider = RecordingProvider()
    agent = BasicAgent(AgentRuntime(), gateway_for(provider))
    first = agent.run("x" * 4000)
    second = agent.run("next")
    assert first.run_id != second.run_id
    assert len(provider.request.messages) == 2
    assert provider.request.messages[1].content == "next"


@pytest.mark.parametrize("fails", [False, True])
def test_lifecycle_and_safe_failure(fails):
    events = []
    class Runtime(AgentRuntime):
        def create_run(self, name):
            run = super().create_run(name)
            events.append(run.status)
            return run
        def _transition(self, *args, **kwargs):
            run = super()._transition(*args, **kwargs)
            events.append(run.status)
            return run
    runtime = Runtime()
    provider = BrokenProvider() if fails else MockModelProvider()
    result = BasicAgent(runtime, gateway_for(provider)).run("hello")
    terminal = RunStatus.FAILED if fails else RunStatus.COMPLETED
    assert events == [RunStatus.PENDING, RunStatus.RUNNING, terminal]
    assert result.status is terminal
    if fails:
        assert result.error_code == "AGENT_MODEL_FAILED"
        assert result.response == ""
        assert "DO_NOT_EXPOSE" not in repr(result)
        assert runtime.get_run(result.run_id).error_code == result.error_code


@pytest.mark.parametrize("fails", [False, True])
def test_persistence_and_restart(tmp_path, fails):
    path = tmp_path / "runs.db"
    store = SQLiteRunStore(path)
    store.initialize()
    class Provider(MockModelProvider):
        def generate(self, request):
            assert store.list_runs()[0].status is RunStatus.RUNNING
            if fails:
                raise RuntimeError("private")
            return super().generate(request)
    result = BasicAgent(AgentRuntime(store), gateway_for(Provider())).run("hello")
    assert result.status is (RunStatus.FAILED if fails else RunStatus.COMPLETED)
    reopened = SQLiteRunStore(path)
    reopened.initialize()
    restarted = AgentRuntime(reopened)
    saved = restarted.get_run(result.run_id)
    assert saved.run_id == result.run_id
    assert saved.status is result.status
    assert saved.error_code == result.error_code
    assert saved.started_at is not None and saved.finished_at is not None
    assert len(store.list_runs()) == 1


@pytest.mark.parametrize("fails", [False, True])
def test_storage_failure_never_returns_unsaved_result(tmp_path, monkeypatch, fails):
    store = SQLiteRunStore(tmp_path / "runs.db")
    store.initialize()
    save = store.save_run
    def fail_terminal(run, **kwargs):
        if run.status in (RunStatus.COMPLETED, RunStatus.FAILED):
            raise RunStorageError()
        save(run, **kwargs)
    monkeypatch.setattr(store, "save_run", fail_terminal)
    provider = BrokenProvider() if fails else MockModelProvider()
    with pytest.raises(RunStorageError):
        BasicAgent(AgentRuntime(store), gateway_for(provider)).run("hello")
    assert store.list_runs()[0].status is RunStatus.RUNNING


def test_unknown_provider_returns_safe_failure():
    result = BasicAgent(AgentRuntime(), ModelGateway()).run("hello")
    assert result.status is RunStatus.FAILED
    assert result.error_code == "AGENT_MODEL_FAILED"


@pytest.mark.parametrize("timeout", [0, -1, True, None, "30", float("nan"), float("inf"), -float("inf")])
def test_invalid_timeout_configuration(timeout):
    with pytest.raises(ModelValidationError):
        ModelRequest((ModelMessage("user", "hello"),), "mock-model", timeout_seconds=timeout)
    with pytest.raises(ModelValidationError):
        BasicAgent(AgentRuntime(), gateway_for(), timeout_seconds=timeout)


@pytest.mark.parametrize("timeout", [0.25, 30, 60.0])
def test_timeout_forwarded_without_changing_mock(timeout):
    provider = RecordingProvider()
    result = BasicAgent(AgentRuntime(), gateway_for(provider), timeout_seconds=timeout).run("hello")
    assert provider.request.timeout_seconds == timeout
    assert result.response == "MOCK: deterministic offline response."


def test_default_timeout():
    provider = RecordingProvider()
    BasicAgent(AgentRuntime(), gateway_for(provider)).run("hello")
    assert provider.request.timeout_seconds == 30.0
    assert ModelRequest((ModelMessage("user", "hello"),), "mock-model").timeout_seconds == 30.0


@pytest.mark.parametrize("error_type", [TimeoutError, ModelTimeoutError])
def test_timeout_propagation_and_persistence(tmp_path, error_type):
    class TimedOut:
        def generate(self, request):
            raise error_type("private provider details")
    gateway = gateway_for(TimedOut())
    request = ModelRequest((ModelMessage("user", "hello"),), "mock-model")
    with pytest.raises(ModelTimeoutError) as exc:
        gateway.generate("mock", request)
    assert exc.value.code == "MODEL_TIMEOUT"
    assert "private" not in str(exc.value)
    assert "private" not in str(exc.value.to_dict())
    store = SQLiteRunStore(tmp_path / "timeout.db")
    store.initialize()
    result = BasicAgent(AgentRuntime(store), gateway).run("hello")
    assert result.status is RunStatus.FAILED
    assert result.error_code == "MODEL_TIMEOUT"
    assert result.response == ""
    reopened = SQLiteRunStore(tmp_path / "timeout.db")
    reopened.initialize()
    saved = AgentRuntime(reopened).get_run(result.run_id)
    assert saved.status is RunStatus.FAILED
    assert saved.error_code == "MODEL_TIMEOUT"
    assert saved.finished_at is not None


def test_offline_demo_and_side_effect_boundaries(tmp_path):
    # A fresh interpreter checks imports as well as execution. Only temporary
    # SQLite files may be written; tool modules, network and child execution fail.
    root = Path(__file__).resolve().parents[1]
    script = r'''
import os, sys, pathlib, runpy
root = pathlib.Path(sys.argv[1]).resolve()
temporary = pathlib.Path(sys.argv[2]).resolve()
sys.path.insert(0, str(root))
def audit(event, args):
    if event.startswith(("socket.", "subprocess.", "os.exec", "os.spawn", "os.fork")) or event == "os.system":
        raise AssertionError(event)
    if event == "import" and str(args[0]).startswith(("architect_vapt", "arqon_os.tools", "arqon_os.capabilities")):
        raise AssertionError("tool import")
    if event in ("open", "os.mkdir", "sqlite3.connect"):
        path = args[0]
        writing = event != "open" or (isinstance(args[1], str) and any(c in args[1] for c in "wax+")) or bool((args[2] or 0) & (os.O_WRONLY | os.O_RDWR | os.O_CREAT))
        if writing and isinstance(path, (str, bytes, os.PathLike)):
            from urllib.parse import unquote
            value = os.fsdecode(path)
            if value.startswith("file:"):
                value = unquote(value[5:].split("?", 1)[0])
            assert pathlib.Path(value).resolve().is_relative_to(temporary), value
sys.addaudithook(audit)
runpy.run_module("examples.basic_agent_demo", run_name="__main__")
'''
    env = dict(os.environ, TMPDIR=str(tmp_path), PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, str(root), str(tmp_path)],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=True,
    )
    assert "Status: completed" in result.stdout
    assert "MOCK: deterministic offline response." in result.stdout
    assert list(tmp_path.iterdir()) == []
