"""Pure snapshot transitions: validation always precedes replacement."""

from dataclasses import replace
from datetime import UTC, datetime

from arqon_os.core.errors import ArqonError
from arqon_os.core.results import RunStatus
from arqon_os.runtime.models import AgentRun


class InvalidTransitionError(ArqonError):
    code = "INVALID_RUN_TRANSITION"
    public_message = "The requested run transition is invalid."


_ALLOWED = {
    RunStatus.PENDING: frozenset({RunStatus.RUNNING, RunStatus.CANCELLED}),
    RunStatus.RUNNING: frozenset({
        RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED,
    }),
}


def transition(
    run: AgentRun, status: RunStatus, *, error_code: str | None = None
) -> AgentRun:
    """Return a new snapshot; invalid operations leave the input untouched.

    Only failure carries an error code. Terminal states have no outgoing edges.
    Cancellation from PENDING leaves started_at unset.
    """
    if (
        not isinstance(status, RunStatus)
        or status not in _ALLOWED.get(run.status, ())
    ):
        raise InvalidTransitionError()
    if status is RunStatus.FAILED:
        if not isinstance(error_code, str) or not error_code.strip():
            raise InvalidTransitionError("Failure requires a nonempty error code.")
    elif error_code is not None:
        raise InvalidTransitionError("Only failure may carry an error code.")
    if run.status is RunStatus.RUNNING and run.started_at is None:
        raise InvalidTransitionError("The run has no start timestamp.")

    now = datetime.now(UTC)
    return replace(
        run,
        status=status,
        started_at=now if status is RunStatus.RUNNING else run.started_at,
        finished_at=None if status is RunStatus.RUNNING else now,
        error_code=error_code,
    )
