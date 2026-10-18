"""Temporary-database tests for persistence, failure atomicity and recovery."""

import os
import sqlite3
import subprocess
import sys
from dataclasses import FrozenInstanceError, replace
from datetime import UTC
from pathlib import Path

import pytest

from arqon_os.core.errors import ArqonError
from arqon_os.core.results import RunStatus
from arqon_os.runtime import AgentRun, AgentRuntime
from arqon_os.runtime.engine import RunNotFoundError
from arqon_os.runtime.state_machine import transition
from arqon_os.runtime.storage import RunConflictError, RunStorageError, SQLiteRunStore


@pytest.fixture
def store(tmp_path: Path) -> SQLiteRunStore:
    result = SQLiteRunStore(tmp_path / "nested" / "runs.db")
    result.initialize()
    return result


def test_explicit_initialization(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "runs.db"
    store = SQLiteRunStore(path)
    assert not path.parent.exists()
    with pytest.raises(RunStorageError):
        store.save_run(AgentRun("example"))
    assert not path.parent.exists()
    store.initialize()
    store.initialize()
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    assert store.list_runs() == []


def test_roundtrip_and_detached_snapshots(store: SQLiteRunStore) -> None:
    original = AgentRun("quote ' ; DROP TABLE runs; --")
    store.save_run(original)
    running = transition(original, RunStatus.RUNNING)
    store.save_run(running)
    finished = transition(running, RunStatus.COMPLETED)
    store.save_run(finished)
    loaded = store.get_run(original.run_id)
    assert loaded == finished
    assert loaded is not finished
    for stamp in (loaded.created_at, loaded.started_at, loaded.finished_at):
        assert stamp.tzinfo is UTC
    with pytest.raises(FrozenInstanceError):
        setattr(loaded, "task_name", "changed")
    object.__setattr__(loaded, "task_name", "changed")
    assert store.get_run(original.run_id) == finished
    assert store.get_run("' OR 1=1 --") is None


def test_list_filter_and_duplicate_save(store: SQLiteRunStore) -> None:
    pending = AgentRun("pending")
    running = transition(AgentRun("running"), RunStatus.RUNNING)
    store.save_run(pending)
    store.save_run(pending)
    store.save_run(running)
    assert len(store.list_runs()) == 2
    assert store.list_runs(RunStatus.PENDING) == [pending]
    assert store.list_runs(RunStatus.RUNNING) == [running]
    assert store.list_runs(RunStatus.FAILED) == []


def test_runtime_restart_and_explicit_recovery(store: SQLiteRunStore) -> None:
    runtime = AgentRuntime(store)
    created = runtime.create_run("persist")
    running = runtime.start_run(created.run_id)
    reopened = SQLiteRunStore(store.database_path)
    reopened.initialize()
    restarted = AgentRuntime(reopened)
    assert restarted.get_run(created.run_id) == running
    completed = restarted.complete_run(created.run_id)
    assert runtime.get_run(created.run_id) == completed
    with pytest.raises(RunNotFoundError):
        restarted.get_run("missing")


def test_recovery_is_idempotent_and_preserves_other_runs(store: SQLiteRunStore) -> None:
    runtime = AgentRuntime(store)
    pending = runtime.create_run("pending")
    running = runtime.start_run(runtime.create_run("interrupted").run_id)
    completed = runtime.complete_run(runtime.start_run(runtime.create_run("done").run_id).run_id)
    failed = runtime.fail_run(runtime.start_run(runtime.create_run("failed").run_id).run_id, "ORIGINAL")
    cancelled = runtime.cancel_run(runtime.create_run("cancelled").run_id)
    assert store.recover_interrupted_runs() == 1
    recovered = runtime.get_run(running.run_id)
    assert recovered.status is RunStatus.FAILED
    assert recovered.error_code == "RUN_INTERRUPTED"
    assert recovered.created_at == running.created_at
    assert recovered.started_at == running.started_at
    assert recovered.finished_at.tzinfo is UTC
    assert recovered.finished_at >= recovered.started_at
    assert store.recover_interrupted_runs() == 0
    assert runtime.get_run(running.run_id) == recovered
    for unchanged in (pending, completed, failed, cancelled):
        assert runtime.get_run(unchanged.run_id) == unchanged
    assert len(store.list_runs()) == 5


def test_conflicts_reject_stale_or_replaced_records(store: SQLiteRunStore) -> None:
    run = transition(AgentRun("example"), RunStatus.RUNNING)
    store.save_run(run)
    completed = transition(run, RunStatus.COMPLETED)
    store.save_run(completed, expected=run)
    with pytest.raises(RunConflictError):
        store.save_run(transition(run, RunStatus.CANCELLED), expected=run)
    with pytest.raises(RunConflictError):
        store.save_run(replace(completed, task_name="other identity"))
    with pytest.raises(RunConflictError):
        store.save_run(run)
    assert store.get_run(run.run_id) == completed


def test_sql_failure_and_runtime_atomicity(store: SQLiteRunStore) -> None:
    runtime = AgentRuntime(store)
    before = runtime.create_run("example")
    with sqlite3.connect(store.database_path) as conn:
        conn.execute("""
            CREATE TRIGGER refuse_update BEFORE UPDATE ON runs
            BEGIN SELECT RAISE(ABORT, 'private SQL detail'); END
        """)
        conn.execute("""
            CREATE TRIGGER refuse_insert BEFORE INSERT ON runs
            BEGIN SELECT RAISE(ABORT, 'private SQL detail'); END
        """)
    for action in (lambda: runtime.start_run(before.run_id), lambda: runtime.create_run("new")):
        with pytest.raises(RunStorageError) as exc:
            action()
        assert isinstance(exc.value, ArqonError)
        assert exc.value.to_dict() == {
            "code": "RUN_STORAGE_ERROR",
            "message": "Run storage could not complete the operation.",
        }
        assert "private" not in str(exc.value)
        assert str(store.database_path) not in str(exc.value.to_dict())
        assert runtime.get_run(before.run_id) == before
        assert store.list_runs() == [before]
        assert runtime._runs == {}


def test_recovery_rolls_back_all_updates(store: SQLiteRunStore) -> None:
    for name in ("first", "second"):
        store.save_run(transition(AgentRun(name), RunStatus.RUNNING))
    before = store.list_runs()
    # Reject the second recovery update, after the first has run in the transaction.
    with sqlite3.connect(store.database_path) as conn:
        conn.execute("""
            CREATE TRIGGER fail_second BEFORE UPDATE ON runs
            WHEN (SELECT count(*) FROM runs WHERE status='failed') > 0
            BEGIN SELECT RAISE(ABORT, 'rollback fixture'); END
        """)
    with pytest.raises(RunStorageError):
        store.recover_interrupted_runs()
    assert store.list_runs() == before


def test_initialization_failure_and_unknown_schema(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    with pytest.raises(RunStorageError):
        SQLiteRunStore(blocker / "runs.db").initialize()
    path = tmp_path / "future.db"
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version = 2")
    with pytest.raises(RunStorageError):
        SQLiteRunStore(path).initialize()
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2


def test_missing_database_is_not_recreated(store: SQLiteRunStore) -> None:
    store.database_path.unlink()
    with pytest.raises(RunStorageError):
        store.list_runs()
    assert not store.database_path.exists()


def test_corrupt_record_is_not_silently_discarded(store: SQLiteRunStore) -> None:
    run = AgentRun("example")
    store.save_run(run)
    with sqlite3.connect(store.database_path) as conn:
        conn.execute("UPDATE runs SET created_at=? WHERE run_id=?", ("invalid", run.run_id))
    with pytest.raises(RunStorageError):
        store.list_runs()


def test_no_database_on_import_or_construction(tmp_path: Path) -> None:
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
    if event in {"os.mkdir", "sqlite3.connect"} or event.startswith("socket."):
        raise AssertionError("Unexpected external effect")
sys.addaudithook(guard)
from pathlib import Path
from arqon_os.runtime.storage import SQLiteRunStore
from arqon_os.runtime import AgentRuntime
store = SQLiteRunStore(Path("uncreated/runs.db"))
AgentRuntime(store)
runtime = AgentRuntime()
run = runtime.create_run("memory only")
runtime.start_run(run.run_id)
runtime.complete_run(run.run_id)
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []
