"""Immutable run snapshots; no tasks are executed by these models."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from arqon_os.core.errors import ArqonError
from arqon_os.core.results import RunStatus


class InvalidRunError(ArqonError):
    code = "INVALID_RUN"
    public_message = "The run parameters are invalid."


@dataclass(frozen=True)
class AgentRun:
    """A run snapshot. Runtime-created identifiers are UUID4 strings."""

    task_name: str
    run_id: str = field(default_factory=lambda: str(uuid4()))
    status: RunStatus = RunStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.task_name, str) or not self.task_name.strip():
            raise InvalidRunError("task_name must be a nonempty string.")
