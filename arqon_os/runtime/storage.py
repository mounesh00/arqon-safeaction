"""Explicit SQLite storage for run snapshots; single-operator local use."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from arqon_os.core.errors import ArqonError
from arqon_os.core.results import RunStatus
from arqon_os.runtime.models import AgentRun
from arqon_os.runtime.state_machine import transition


class RunStorageError(ArqonError):
    code = "RUN_STORAGE_ERROR"
    public_message = "Run storage could not complete the operation."


class RunConflictError(RunStorageError):
    code = "RUN_STORAGE_CONFLICT"
    public_message = "The stored run conflicts with the requested update."


_COLUMNS = "run_id, task_name, status, created_at, started_at, finished_at, error_code"


def _timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise RunStorageError()
    return value.astimezone(UTC).isoformat()


def _decode(row: sqlite3.Row) -> AgentRun:
    def stamp(value: str | None) -> datetime | None:
        if value is None:
            return None
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() is None:
            raise ValueError("Naive timestamp")
        return parsed.astimezone(UTC)

    try:
        run = AgentRun(
            run_id=row["run_id"], task_name=row["task_name"],
            status=RunStatus(row["status"]), created_at=stamp(row["created_at"]),
            started_at=stamp(row["started_at"]), finished_at=stamp(row["finished_at"]),
            error_code=row["error_code"],
        )
        _values(run)
        return run
    except (ValueError, TypeError, ArqonError):
        raise RunStorageError() from None


def _values(run: AgentRun) -> tuple[object, ...]:
    """Reject malformed snapshots instead of writing unrecoverable records."""
    if (
        not isinstance(run.status, RunStatus)
        or not isinstance(run.run_id, str) or not run.run_id
        or not isinstance(run.task_name, str) or not run.task_name.strip()
        or run.created_at is None
    ):
        raise RunStorageError()
    times = tuple(_timestamp(t) for t in (run.created_at, run.started_at, run.finished_at))
    terminal = run.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED)
    if terminal != (run.finished_at is not None):
        raise RunStorageError()
    if run.status is RunStatus.PENDING and run.started_at is not None:
        raise RunStorageError()
    if run.status in (RunStatus.RUNNING, RunStatus.COMPLETED, RunStatus.FAILED) and run.started_at is None:
        raise RunStorageError()
    if run.status is RunStatus.FAILED:
        if not isinstance(run.error_code, str) or not run.error_code.strip():
            raise RunStorageError()
    elif run.error_code is not None:
        raise RunStorageError()
    return (run.run_id, run.task_name, run.status.value, *times, run.error_code)


class SQLiteRunStore:
    """Call initialize() explicitly before use, including on a reopened store.

    Construction does not touch disk. Version 1 is the only supported schema.
    Connections are short-lived; writes use BEGIN IMMEDIATE and rollback on error.
    """

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)
        self._initialized = False

    def initialize(self) -> None:
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connection(create=True) as conn:
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                if version == 0:
                    if conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                        raise RunStorageError()
                    conn.execute("""
                        CREATE TABLE runs (
                            run_id TEXT PRIMARY KEY NOT NULL,
                            task_name TEXT NOT NULL, status TEXT NOT NULL,
                            created_at TEXT NOT NULL, started_at TEXT,
                            finished_at TEXT, error_code TEXT
                        )
                    """)
                    conn.execute("PRAGMA user_version = 1")
                elif version != 1:
                    raise RunStorageError()
                conn.execute(f"SELECT {_COLUMNS} FROM runs LIMIT 0")
            self._initialized = True
        except OSError:
            raise RunStorageError() from None

    @contextmanager
    def _connection(self, *, create: bool = False, write: bool = False) -> Iterator[sqlite3.Connection]:
        if not create and not self._initialized:
            raise RunStorageError("Explicit initialization is required.")
        conn = None
        try:
            uri = self.database_path.absolute().as_uri() + ("?mode=rwc" if create else "?mode=rw")
            conn = sqlite3.connect(uri, uri=True, timeout=5)
            conn.row_factory = sqlite3.Row
            with conn:
                if create or write:
                    conn.execute("BEGIN IMMEDIATE")
                yield conn
        except (sqlite3.Error, OSError):
            raise RunStorageError() from None
        finally:
            if conn is not None:
                conn.close()

    def save_run(self, run: AgentRun, *, expected: AgentRun | None = None) -> None:
        """Insert or advance a run; identical saves are idempotent.

        An optional expected snapshot prevents stale runtime updates. Identity
        fields cannot change, nor can terminal states be overwritten.
        """
        values = _values(run)
        with self._connection(write=True) as conn:
            row = conn.execute(f"SELECT {_COLUMNS} FROM runs WHERE run_id = ?", (run.run_id,)).fetchone()
            old = _decode(row) if row else None
            if expected is not None and old != expected:
                raise RunConflictError()
            if old == run:
                return
            if old is None:
                if expected is not None:
                    raise RunConflictError()
                conn.execute(f"INSERT INTO runs ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)", values)
                return
            if (old.task_name, old.created_at) != (run.task_name, run.created_at):
                raise RunConflictError()
            try:
                transition(old, run.status, error_code=run.error_code)
            except ArqonError:
                raise RunConflictError() from None
            if old.started_at is not None and old.started_at != run.started_at:
                raise RunConflictError()
            conn.execute(
                "UPDATE runs SET status=?, started_at=?, finished_at=?, error_code=? WHERE run_id=?",
                (run.status.value, values[4], values[5], run.error_code, run.run_id),
            )

    def get_run(self, run_id: str) -> AgentRun | None:
        """Return None for an unknown ID; the runtime maps it to RUN_NOT_FOUND."""
        with self._connection() as conn:
            row = conn.execute(f"SELECT {_COLUMNS} FROM runs WHERE run_id=?", (run_id,)).fetchone()
            return _decode(row) if row else None

    def list_runs(self, status: RunStatus | None = None) -> list[AgentRun]:
        if status is not None and not isinstance(status, RunStatus):
            raise RunStorageError("status must be a RunStatus.")
        with self._connection() as conn:
            sql = f"SELECT {_COLUMNS} FROM runs"
            params: tuple[str, ...] = ()
            if status is not None:
                sql += " WHERE status=?"
                params = (status.value,)
            rows = conn.execute(sql + " ORDER BY created_at, run_id", params).fetchall()
            return [_decode(row) for row in rows]

    def recover_interrupted_runs(self) -> int:
        """Atomically fail all RUNNING runs; return the number recovered.

        Invoke only when no worker owns these runs. Never retry their operations.
        """
        with self._connection(write=True) as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM runs WHERE status=?", (RunStatus.RUNNING.value,)
            ).fetchall()
            for row in rows:
                recovered = transition(_decode(row), RunStatus.FAILED, error_code="RUN_INTERRUPTED")
                conn.execute(
                    "UPDATE runs SET status=?, finished_at=?, error_code=? WHERE run_id=?",
                    (recovered.status.value, _timestamp(recovered.finished_at),
                     recovered.error_code, recovered.run_id),
                )
            return len(rows)
