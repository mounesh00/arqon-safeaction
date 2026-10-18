"""Single-threaded lifecycle management with optional explicit persistence."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from arqon_os.core.errors import ArqonError
from arqon_os.core.results import RunStatus
from arqon_os.runtime.models import AgentRun
from arqon_os.runtime.state_machine import transition

if TYPE_CHECKING:
    from arqon_os.runtime.storage import SQLiteRunStore


class RunNotFoundError(ArqonError):
    code = "RUN_NOT_FOUND"
    public_message = "The requested run was not found."


class AgentRuntime:
    """Manage run state only. Public methods return detached frozen snapshots."""

    def __init__(self, store: SQLiteRunStore | None = None) -> None:
        # The caller initializes storage; construction never touches a database.
        self._store = store
        self._runs: dict[str, AgentRun] = {}

    def create_run(self, task_name: str) -> AgentRun:
        run = AgentRun(task_name=task_name)
        if self._store is not None:
            self._store.save_run(run)
        else:
            self._runs[run.run_id] = run
        return replace(run)

    def get_run(self, run_id: str) -> AgentRun:
        if not isinstance(run_id, str):
            raise RunNotFoundError()
        if self._store is not None:
            run = self._store.get_run(run_id)
            if run is None:
                raise RunNotFoundError()
            return run
        if not isinstance(run_id, str) or run_id not in self._runs:
            raise RunNotFoundError()
        return replace(self._runs[run_id])

    def start_run(self, run_id: str) -> AgentRun:
        return self._transition(run_id, RunStatus.RUNNING)

    def complete_run(self, run_id: str) -> AgentRun:
        return self._transition(run_id, RunStatus.COMPLETED)

    def fail_run(self, run_id: str, error_code: str) -> AgentRun:
        return self._transition(run_id, RunStatus.FAILED, error_code=error_code)

    def cancel_run(self, run_id: str) -> AgentRun:
        return self._transition(run_id, RunStatus.CANCELLED)

    def _transition(
        self, run_id: str, status: RunStatus, *, error_code: str | None = None
    ) -> AgentRun:
        previous = self.get_run(run_id)
        updated = transition(previous, status, error_code=error_code)
        if self._store is not None:
            self._store.save_run(updated, expected=previous)
        else:
            self._runs[run_id] = updated
        return replace(updated)
