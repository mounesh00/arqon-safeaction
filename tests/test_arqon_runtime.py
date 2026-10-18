"""Focused coverage of lifecycle transitions and absence of external effects."""

import os
import subprocess
import sys
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from arqon_os.core.errors import ArqonError
from arqon_os.core.results import RunStatus
from arqon_os.runtime import AgentRun, AgentRuntime
from arqon_os.runtime.engine import RunNotFoundError
from arqon_os.runtime.models import InvalidRunError
from arqon_os.runtime.state_machine import InvalidTransitionError, transition


def make_run(runtime: AgentRuntime, status: RunStatus) -> AgentRun:
    run = runtime.create_run("example")
    if status is RunStatus.PENDING:
        return run
    runtime.start_run(run.run_id)
    if status is RunStatus.COMPLETED:
        runtime.complete_run(run.run_id)
    elif status is RunStatus.FAILED:
        runtime.fail_run(run.run_id, "TEST_FAILURE")
    elif status is RunStatus.CANCELLED:
        runtime.cancel_run(run.run_id)
    return runtime.get_run(run.run_id)


def test_create_and_unique_ids() -> None:
    runtime = AgentRuntime()
    before = datetime.now(UTC)
    runs = [runtime.create_run("example") for _ in range(20)]
    after = datetime.now(UTC)
    assert len({r.run_id for r in runs}) == 20
    for run in runs:
        assert UUID(run.run_id).version == 4
        assert run.task_name == "example"
        assert run.status is RunStatus.PENDING
        assert before <= run.created_at <= after
        assert run.created_at.tzinfo is UTC
        assert run.started_at is run.finished_at is run.error_code is None


@pytest.mark.parametrize("source", list(RunStatus))
@pytest.mark.parametrize("target", list(RunStatus))
def test_all_transition_pairs(source: RunStatus, target: RunStatus) -> None:
    runtime = AgentRuntime()
    before = make_run(runtime, source)
    allowed = {
        (RunStatus.PENDING, RunStatus.RUNNING),
        (RunStatus.PENDING, RunStatus.CANCELLED),
        (RunStatus.RUNNING, RunStatus.COMPLETED),
        (RunStatus.RUNNING, RunStatus.FAILED),
        (RunStatus.RUNNING, RunStatus.CANCELLED),
    }
    code = "TEST_FAILURE" if target is RunStatus.FAILED else None
    if (source, target) in allowed:
        after = transition(before, target, error_code=code)
        assert after.status is target
        assert after.run_id == before.run_id
        assert after.created_at == before.created_at
        assert after.error_code == code
    else:
        with pytest.raises(InvalidTransitionError) as exc:
            transition(before, target, error_code=code)
        assert isinstance(exc.value, ArqonError)
        assert exc.value.code == "INVALID_RUN_TRANSITION"
    assert runtime.get_run(before.run_id) == before


@pytest.mark.parametrize("terminal", [RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED])
def test_engine_terminal_protection(terminal: RunStatus) -> None:
    runtime = AgentRuntime()
    before = make_run(runtime, terminal)
    for action in (
        runtime.start_run, runtime.complete_run, runtime.cancel_run,
        lambda run_id: runtime.fail_run(run_id, "FAILURE"),
    ):
        with pytest.raises(InvalidTransitionError):
            action(before.run_id)
        assert runtime.get_run(before.run_id) == before


@pytest.mark.parametrize("terminal", [RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED])
def test_engine_timestamps(terminal: RunStatus) -> None:
    runtime = AgentRuntime()
    pending = runtime.create_run("example")
    running = runtime.start_run(pending.run_id)
    assert running.started_at is not None
    assert running.finished_at is None
    assert running.created_at <= running.started_at
    if terminal is RunStatus.COMPLETED:
        finished = runtime.complete_run(pending.run_id)
    elif terminal is RunStatus.FAILED:
        finished = runtime.fail_run(pending.run_id, "FAILURE")
    else:
        finished = runtime.cancel_run(pending.run_id)
    assert finished.status is terminal
    assert finished.started_at == running.started_at
    assert finished.finished_at is not None
    assert finished.started_at <= finished.finished_at <= datetime.now(UTC)
    for stamp in (finished.created_at, finished.started_at, finished.finished_at):
        assert stamp.tzinfo is UTC
    assert pending.status is RunStatus.PENDING
    assert running.status is RunStatus.RUNNING


def test_cancel_before_start_and_complete_before_start() -> None:
    runtime = AgentRuntime()
    run = runtime.create_run("example")
    with pytest.raises(InvalidTransitionError):
        runtime.complete_run(run.run_id)
    assert runtime.get_run(run.run_id) == run
    cancelled = runtime.cancel_run(run.run_id)
    assert cancelled.started_at is None
    assert cancelled.finished_at is not None
    assert cancelled.finished_at.tzinfo is UTC
    with pytest.raises(InvalidTransitionError):
        runtime.start_run(run.run_id)
    assert runtime.get_run(run.run_id) == cancelled


@pytest.mark.parametrize("code", [None, "", " \t", 1, False])
def test_failure_requires_code_and_is_atomic(code: object) -> None:
    runtime = AgentRuntime()
    before = make_run(runtime, RunStatus.RUNNING)
    with pytest.raises(InvalidTransitionError):
        runtime.fail_run(before.run_id, code)  # type: ignore[arg-type]
    assert runtime.get_run(before.run_id) == before


def test_reject_unexpected_code_and_untyped_status() -> None:
    runtime = AgentRuntime()
    before = runtime.create_run("example")
    with pytest.raises(InvalidTransitionError):
        transition(before, RunStatus.RUNNING, error_code="UNEXPECTED")
    with pytest.raises(InvalidTransitionError):
        transition(before, "running")  # type: ignore[arg-type]
    assert runtime.get_run(before.run_id) == before


@pytest.mark.parametrize("method", ["start_run", "complete_run", "fail_run", "cancel_run", "get_run"])
def test_unknown_run(method: str) -> None:
    runtime = AgentRuntime()
    args = ("missing", "FAILURE") if method == "fail_run" else ("missing",)
    with pytest.raises(RunNotFoundError) as exc:
        getattr(runtime, method)(*args)
    assert isinstance(exc.value, ArqonError)
    assert exc.value.to_dict()["code"] == "RUN_NOT_FOUND"


@pytest.mark.parametrize("name", ["", " ", "\t\n", None, 12])
def test_invalid_task_names(name: object) -> None:
    with pytest.raises(InvalidRunError):
        AgentRuntime().create_run(name)  # type: ignore[arg-type]


def test_returned_snapshots_are_detached() -> None:
    runtime = AgentRuntime()
    created = runtime.create_run("example")
    run_id = created.run_id
    with pytest.raises(FrozenInstanceError):
        setattr(created, "status", RunStatus.COMPLETED)
    # Even deliberate bypass of frozen dataclass assignment cannot affect storage.
    object.__setattr__(created, "task_name", "tampered")
    assert runtime.get_run(run_id).task_name == "example"
    started = runtime.start_run(run_id)
    object.__setattr__(started, "status", RunStatus.CANCELLED)
    fetched = runtime.get_run(run_id)
    assert fetched.status is RunStatus.RUNNING
    object.__setattr__(fetched, "error_code", "tampered")
    assert runtime.get_run(run_id).error_code is None


def test_runtime_has_no_external_effects(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    script = """
import os
import sys
def guard(event, args):
    if event == "open":
        mode, flags = args[1], args[2]
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
            isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)
        ):
            raise AssertionError("Unexpected write")
    if event.startswith(("socket.", "subprocess.")) or event in {
        "os.mkdir", "os.remove", "os.rename", "os.rmdir", "os.system",
        "os.fork", "os.forkpty", "os.posix_spawn", "os.exec",
    }:
        raise AssertionError("Unexpected external effect")
sys.addaudithook(guard)
import _thread
import threading
def deny(*args, **kwargs):
    raise AssertionError("Unexpected thread")
_thread.start_new_thread = deny
threading.Thread.start = deny
from arqon_os.runtime import AgentRuntime
runtime = AgentRuntime()
for terminal in ("complete_run", "fail_run", "cancel_run"):
    run = runtime.create_run("fixture")
    runtime.start_run(run.run_id)
    if terminal == "fail_run":
        runtime.fail_run(run.run_id, "FIXTURE")
    else:
        getattr(runtime, terminal)(run.run_id)
    runtime.get_run(run.run_id)
runtime.cancel_run(runtime.create_run("pending cancellation").run_id)
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []
