"""In-memory, run/tool-bound human decisions.

This is a trusted local application boundary, not authentication or a sandbox.
Only trusted operator code may configure human_deciders or submit HUMAN events.
Model output must never be translated into a human decision or identity.
"""

import hashlib
import hmac
import json
import math
import re
from copy import copy
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from threading import RLock
from urllib.parse import urlsplit
from uuid import uuid4

from arqon_os.core.errors import ArqonError


class ApprovalError(ArqonError):
    code = "INVALID_APPROVAL"
    public_message = "The approval request or transition is invalid."


class UnknownApprovalError(ApprovalError):
    code = "UNKNOWN_APPROVAL"
    public_message = "The approval request was not found."


class ApprovalBindingError(ApprovalError):
    code = "APPROVAL_BINDING_MISMATCH"
    public_message = "The approval does not match this run and tool."


class HumanDecisionRequiredError(ApprovalError):
    code = "HUMAN_DECISION_REQUIRED"
    public_message = "An explicit decision by a configured human operator is required."


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class ActorKind(str, Enum):
    HUMAN = "human"
    MODEL = "model"



class InvalidApprovalContextError(ApprovalError):
    code = "INVALID_APPROVAL_CONTEXT"
    public_message = "The approval context is invalid."


class ApprovalContextUnboundError(ApprovalError):
    code = "APPROVAL_CONTEXT_UNBOUND"
    public_message = "The approval has no bound request context."


class ApprovalExpiredError(ApprovalError):
    code = "APPROVAL_EXPIRED"
    public_message = "The approval has expired."


class ApprovalConsumedError(ApprovalError):
    code = "APPROVAL_CONSUMED"
    public_message = "The approval has already been consumed."


def _json_value(value: object, depth: int = 0) -> None:
    if depth > 32:
        raise InvalidApprovalContextError()
    if value is None or type(value) in (bool, int, str):
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for item in value:
            _json_value(item, depth + 1)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str or re.search(
                r"password|secret|token|credential|authorization|cookie|api.?key", key, re.IGNORECASE,
            ):
                raise InvalidApprovalContextError()
            _json_value(item, depth + 1)
        return
    raise InvalidApprovalContextError()


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


@dataclass(frozen=True, init=False)
class ApprovalContext:
    """Immutable JSON snapshot of NONSECRET inputs.

    SHA-256 is a deterministic context fingerprint, not an authorization signature
    or proof of human identity. Accepts dictionaries only, never serialized JSON
    (duplicate JSON keys cannot enter this API). Preserves JSON value types.
    Adapters normalize targets and allowlist nonsecret arguments. Credential URLs,
    query strings and sensitive argument keys are rejected conservatively;
    arbitrary secrets in free text cannot be detected reliably.
    """

    run_id: str
    tool_name: str
    canonical_target: str = field(repr=False)
    canonical_arguments: str = field(repr=False)
    context_digest: str

    def __init__(self, run_id: str, tool_name: str, canonical_target: str,
                 canonical_arguments: dict[str, object]) -> None:
        if any(type(v) is not str or not v.strip() for v in (run_id, tool_name, canonical_target)):
            raise InvalidApprovalContextError()
        try:
            target = urlsplit(canonical_target)
            # Exact local clock capability identifier; never a network target.
            local_clock = (canonical_target == "urn:arqon:system.get_time"
                           and tool_name == "system.get_time" and canonical_arguments == {})
            local_checklist = (
                canonical_target == "urn:arqon:safeaction.save_travel_checklist"
                and tool_name == "safeaction.save_travel_checklist"
                and type(canonical_arguments) is dict
                and set(canonical_arguments) == {"proposal_id", "title", "items"}
                and canonical_arguments["proposal_id"] == run_id
                and type(canonical_arguments["title"]) is str
                and type(canonical_arguments["items"]) is list
                and all(type(item) is str for item in canonical_arguments["items"])
            )
            if not (local_clock or local_checklist) and (target.scheme not in ("http", "https") or not target.hostname
                or target.username is not None or target.password is not None
                or "?" in canonical_target or "#" in canonical_target):
                raise InvalidApprovalContextError()
            if type(canonical_arguments) is not dict:
                raise InvalidApprovalContextError()
            _json_value(canonical_arguments)
            arguments = _json(canonical_arguments)
            payload = _json({"run_id": run_id, "tool_name": tool_name,
                             "canonical_target": canonical_target,
                             "canonical_arguments": canonical_arguments})
        except (ValueError, TypeError, RecursionError):
            raise InvalidApprovalContextError() from None
        for key, value in (
            ("run_id", run_id), ("tool_name", tool_name),
            ("canonical_target", canonical_target), ("canonical_arguments", arguments),
            ("context_digest", hashlib.sha256(payload.encode("utf-8")).hexdigest()),
        ):
            object.__setattr__(self, key, value)


def _validated_context(context: ApprovalContext) -> ApprovalContext:
    if type(context) is not ApprovalContext:
        raise InvalidApprovalContextError()
    try:
        rebuilt = ApprovalContext(context.run_id, context.tool_name, context.canonical_target,
                                  json.loads(context.canonical_arguments))
        if context != rebuilt:
            raise InvalidApprovalContextError()
        return rebuilt
    except (ValueError, TypeError):
        raise InvalidApprovalContextError() from None


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise ApprovalError("Timestamps must be timezone-aware UTC.")
    return value.astimezone(UTC)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class ApprovalRecord:
    """Public construction creates only PENDING records.

    Decisions must go through ApprovalManager.decide. Decision fields are excluded
    from __init__, so constructors and dataclasses.replace cannot forge APPROVED.
    """

    run_id: str
    tool_name: str
    approval_id: str = field(default_factory=lambda: str(uuid4()), init=False)
    status: ApprovalStatus = field(default=ApprovalStatus.PENDING, init=False)
    requested_at: datetime = field(default_factory=lambda: datetime.now(UTC), init=False)
    expires_at: datetime = field(init=False)
    context_digest: str | None = field(default=None, init=False)
    consumed_at: datetime | None = field(default=None, init=False)
    decided_at: datetime | None = field(default=None, init=False)
    decided_by: str | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "expires_at", self.requested_at + timedelta(minutes=10))
        if any(not isinstance(v, str) or not v.strip() for v in (self.run_id, self.tool_name)):
            raise ApprovalError()


class ApprovalManager:
    """Trusted in-memory manager; legacy unbound approvals cannot be consumed.

    One lock protects access, decisions and consumption. No execution occurs.
    """

    def __init__(self, human_deciders: frozenset[str] = frozenset()) -> None:
        if not isinstance(human_deciders, (set, frozenset)) or any(
            not isinstance(v, str) or not v.strip() for v in human_deciders
        ):
            raise HumanDecisionRequiredError()
        self._human_deciders = frozenset(human_deciders)
        self._records: dict[str, ApprovalRecord] = {}
        self._lock = RLock()

    def request(
        self, run_id: str, tool_name: str, *, context: ApprovalContext | None = None,
        expires_at: datetime | None = None,
    ) -> ApprovalRecord:
        context = _validated_context(context) if context is not None else None
        if context is not None and (context.run_id, context.tool_name) != (run_id, tool_name):
            raise ApprovalBindingError()
        now = _utc(_now())
        expiry = now + timedelta(minutes=10) if expires_at is None else _utc(expires_at)
        if expiry <= now:
            raise ApprovalError("Expiry must be after request time.")
        record = ApprovalRecord(run_id, tool_name)
        object.__setattr__(record, "requested_at", now)
        object.__setattr__(record, "expires_at", expiry)
        object.__setattr__(record, "context_digest", context.context_digest if context else None)
        with self._lock:
            self._records[record.approval_id] = record
        return copy(record)

    def get(self, approval_id: str, *, run_id: str, tool_name: str) -> ApprovalRecord:
        """Read-only audit snapshot, including expired/consumed records."""
        with self._lock:
            if not isinstance(approval_id, str) or approval_id not in self._records:
                raise UnknownApprovalError()
            record = self._records[approval_id]
            if (record.run_id, record.tool_name) != (run_id, tool_name):
                raise ApprovalBindingError()
            return copy(record)

    def _check_time(self, record: ApprovalRecord, now: datetime) -> None:
        requested, expiry = _utc(record.requested_at), _utc(record.expires_at)
        if requested > now or expiry <= requested:
            raise ApprovalError("Invalid approval timestamps.")
        if record.decided_at is not None:
            decided = _utc(record.decided_at)
            if not requested <= decided < expiry or decided > now:
                raise ApprovalError("Invalid decision timestamp.")
        if now >= expiry:
            raise ApprovalExpiredError()

    def decide(
        self, approval_id: str, *, run_id: str, tool_name: str,
        status: ApprovalStatus, decided_by: str, actor_kind: ActorKind,
        human_confirmed: bool,
    ) -> ApprovalRecord:
        with self._lock:
            record = self.get(approval_id, run_id=run_id, tool_name=tool_name)
            if (
                actor_kind is not ActorKind.HUMAN or human_confirmed is not True
                or not isinstance(decided_by, str) or decided_by not in self._human_deciders
            ):
                raise HumanDecisionRequiredError()
            if record.status is not ApprovalStatus.PENDING or status not in (
                ApprovalStatus.APPROVED, ApprovalStatus.DENIED,
            ) or not isinstance(status, ApprovalStatus):
                raise ApprovalError()
            now = _utc(_now())
            self._check_time(record, now)
            object.__setattr__(record, "status", status)
            object.__setattr__(record, "decided_at", now)
            object.__setattr__(record, "decided_by", decided_by)
            self._records[approval_id] = record
            return copy(record)

    def consume(self, approval_id: str, *, context: ApprovalContext) -> ApprovalRecord:
        """Consume once atomically after validation; failures change nothing."""
        context = _validated_context(context)
        with self._lock:
            record = self.get(approval_id, run_id=context.run_id, tool_name=context.tool_name)
            if record.context_digest is None:
                raise ApprovalContextUnboundError()
            if not hmac.compare_digest(record.context_digest, context.context_digest):
                raise ApprovalBindingError()
            if record.status is not ApprovalStatus.APPROVED:
                raise ApprovalError("Approval must be approved.")
            if record.decided_by not in self._human_deciders or record.decided_at is None:
                raise HumanDecisionRequiredError()
            now = _utc(_now())
            self._check_time(record, now)
            if record.consumed_at is not None:
                raise ApprovalConsumedError()
            object.__setattr__(record, "consumed_at", now)
            self._records[approval_id] = record
            return copy(record)
