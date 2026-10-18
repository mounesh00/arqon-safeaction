"""Validated operation snapshots, independent of any runtime implementation."""

from dataclasses import dataclass, field
from enum import Enum


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class OperationResult:
    """A snapshot whose status fields cannot be changed after validation.

    success is true if and only if status is COMPLETED. FAILED requires a
    nonempty error_code; CANCELLED permits an optional nonempty error_code.
    PENDING, RUNNING and COMPLETED must not carry error codes. For unfinished
    runs success=False means "not completed successfully", not necessarily failed.
    data remains mutable, with a fresh default dictionary for every instance.
    Supplied dictionaries are retained; callers own their contents and safety.
    """

    success: bool
    status: RunStatus
    message: str
    data: dict[str, object] = field(default_factory=dict)
    error_code: str | None = None

    def __post_init__(self) -> None:
        if type(self.success) is not bool or not isinstance(self.status, RunStatus):
            raise ValueError("success must be a bool and status must be a RunStatus.")
        if not isinstance(self.message, str) or not isinstance(self.data, dict):
            raise ValueError("message must be a string and data must be a dictionary.")
        if self.success != (self.status is RunStatus.COMPLETED):
            raise ValueError("Only COMPLETED results are successful.")
        if self.error_code is not None and (
            not isinstance(self.error_code, str) or not self.error_code.strip()
        ):
            raise ValueError("error_code must be a nonempty string or None.")
        if self.status is RunStatus.FAILED and self.error_code is None:
            raise ValueError("FAILED results require an error_code.")
        if self.status not in (RunStatus.FAILED, RunStatus.CANCELLED) and self.error_code is not None:
            raise ValueError("Only FAILED or CANCELLED results may carry an error_code.")
