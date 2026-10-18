"""Offline tests for metadata, fixed permission policy and bound approvals."""

import os
import subprocess
import sys
from dataclasses import FrozenInstanceError, replace
from datetime import UTC
from pathlib import Path
from uuid import UUID

import pytest

from arqon_os.tools.approvals import (
    ActorKind, ApprovalBindingError, ApprovalError, ApprovalManager, ApprovalRecord,
    ApprovalStatus, HumanDecisionRequiredError, UnknownApprovalError,
)
from arqon_os.tools.permissions import PermissionEngine
from arqon_os.tools.registry import (
    DuplicateToolError, RiskLevel, ToolDefinition, ToolRegistry, ToolValidationError,
    UnknownToolError,
)


def tool(risk: RiskLevel = RiskLevel.LOW) -> ToolDefinition:
    return ToolDefinition("inspect", "Inspect fixture", "test", risk, frozenset({"read"}))


@pytest.mark.parametrize("field,value", [
    ("name", ""), ("name", " "), ("description", ""), ("description", None),
    ("category", ""), ("risk_level", "low"), ("risk_level", "unknown"),
    ("required_permissions", "read"), ("required_permissions", {""}),
    ("required_permissions", {"*"}), ("required_permissions", {1}),
])
def test_tool_validation(field: str, value: object) -> None:
    with pytest.raises(ToolValidationError):
        replace(tool(), **{field: value})


def test_registry_and_immutable_metadata() -> None:
    permissions = {"read"}
    original = ToolDefinition("inspect", "Inspect fixture", "test", RiskLevel.LOW, permissions)
    registry = ToolRegistry()
    registry.register(original)
    permissions.add("write")
    assert original.required_permissions == frozenset({"read"})
    with pytest.raises(FrozenInstanceError):
        setattr(original, "risk_level", RiskLevel.CRITICAL)
    object.__setattr__(original, "description", "changed")
    assert registry.get("inspect").description == "Inspect fixture"
    fetched = registry.get("inspect")
    object.__setattr__(fetched, "description", "changed again")
    listing = registry.list_tools()
    listing.clear()
    assert registry.get("inspect").description == "Inspect fixture"
    with pytest.raises(DuplicateToolError) as exc:
        registry.register(tool())
    assert exc.value.code == "DUPLICATE_TOOL"
    with pytest.raises(UnknownToolError) as exc:
        registry.get("unknown")
    assert exc.value.code == "UNKNOWN_TOOL"


def test_deny_by_default() -> None:
    decision = PermissionEngine().evaluate(tool())
    assert not decision.allowed
    assert decision.reason_code == "MISSING_PERMISSIONS"
    assert not decision.requires_approval
    with pytest.raises(FrozenInstanceError):
        setattr(decision, "allowed", True)


@pytest.mark.parametrize("risk", list(RiskLevel))
@pytest.mark.parametrize("status", list(ApprovalStatus))
def test_missing_permissions_always_deny(risk: RiskLevel, status: ApprovalStatus) -> None:
    decision = PermissionEngine().evaluate(tool(risk), frozenset({"unrelated"}), status)
    assert not decision.allowed
    assert decision.reason_code == "MISSING_PERMISSIONS"


@pytest.mark.parametrize("risk", list(RiskLevel))
@pytest.mark.parametrize("status", list(ApprovalStatus))
def test_risk_policy(risk: RiskLevel, status: ApprovalStatus) -> None:
    decision = PermissionEngine().evaluate(tool(risk), frozenset({"read"}), status)
    allowed = status is not ApprovalStatus.DENIED and (
        risk is RiskLevel.LOW or status is ApprovalStatus.APPROVED
    )
    assert decision.allowed is allowed
    assert decision.requires_approval is (risk is not RiskLevel.LOW)
    expected = "ALLOWED" if allowed else (
        "APPROVAL_DENIED" if status is ApprovalStatus.DENIED else "APPROVAL_REQUIRED"
    )
    assert decision.reason_code == expected


@pytest.mark.parametrize("status", [None, "approved", "unknown", True])
def test_unknown_approval_states(status: object) -> None:
    for risk in RiskLevel:
        decision = PermissionEngine().evaluate(tool(risk), frozenset({"read"}), status)
        assert not decision.allowed
        assert decision.reason_code == "UNKNOWN_APPROVAL_STATE"


@pytest.mark.parametrize("grants", [frozenset(), frozenset({"*"}), "read", None])
def test_empty_and_invalid_grants(grants: object) -> None:
    assert not PermissionEngine().evaluate(tool(), grants, ApprovalStatus.APPROVED).allowed


def test_undeclared_permissions_are_not_a_wildcard() -> None:
    definition = replace(tool(), required_permissions=frozenset())
    for grants in (frozenset(), frozenset({"read"})):
        decision = PermissionEngine().evaluate(definition, grants, ApprovalStatus.APPROVED)
        assert not decision.allowed
        assert decision.reason_code == "UNDECLARED_PERMISSIONS"


def decide(manager: ApprovalManager, record: ApprovalRecord, status: ApprovalStatus) -> ApprovalRecord:
    return manager.decide(
        record.approval_id, run_id=record.run_id, tool_name=record.tool_name,
        status=status, decided_by="operator", actor_kind=ActorKind.HUMAN,
        human_confirmed=True,
    )


def test_request_creation_and_constructor_protection() -> None:
    manager = ApprovalManager()
    request = manager.request("run-1", "inspect")
    assert request.status is ApprovalStatus.PENDING
    assert UUID(request.approval_id).version == 4
    assert request.approval_id != manager.request("run-1", "inspect").approval_id
    assert request.requested_at.tzinfo is UTC
    assert request.decided_at is request.decided_by is None
    with pytest.raises(TypeError):
        ApprovalRecord("run-1", "inspect", status=ApprovalStatus.APPROVED)
    with pytest.raises((TypeError, ValueError)):
        replace(request, status=ApprovalStatus.APPROVED)
    with pytest.raises(FrozenInstanceError):
        setattr(request, "status", ApprovalStatus.APPROVED)
    object.__setattr__(request, "status", ApprovalStatus.APPROVED)
    assert manager.get(request.approval_id, run_id="run-1", tool_name="inspect").status is ApprovalStatus.PENDING


@pytest.mark.parametrize("status", [ApprovalStatus.APPROVED, ApprovalStatus.DENIED])
def test_human_decision_and_no_redecision(status: ApprovalStatus) -> None:
    manager = ApprovalManager(frozenset({"operator"}))
    pending = manager.request("run-1", "inspect")
    decided = decide(manager, pending, status)
    assert decided.status is status
    assert decided.decided_by == "operator"
    assert decided.decided_at.tzinfo is UTC
    assert decided.decided_at >= pending.requested_at
    assert pending.status is ApprovalStatus.PENDING
    for next_status in ApprovalStatus:
        with pytest.raises(ApprovalError):
            decide(manager, decided, next_status)
        assert manager.get(decided.approval_id, run_id="run-1", tool_name="inspect") == decided


@pytest.mark.parametrize("run_id,tool_name", [("other-run", "inspect"), ("run-1", "other-tool")])
def test_binding(run_id: str, tool_name: str) -> None:
    manager = ApprovalManager(frozenset({"operator"}))
    request = manager.request("run-1", "inspect")
    for status in (ApprovalStatus.PENDING, ApprovalStatus.APPROVED):
        with pytest.raises(ApprovalBindingError):
            manager.get(request.approval_id, run_id=run_id, tool_name=tool_name)
        with pytest.raises(ApprovalBindingError):
            manager.decide(
                request.approval_id, run_id=run_id, tool_name=tool_name,
                status=ApprovalStatus.APPROVED, decided_by="operator",
                actor_kind=ActorKind.HUMAN, human_confirmed=True,
            )
        if status is ApprovalStatus.PENDING:
            request = decide(manager, request, ApprovalStatus.APPROVED)


@pytest.mark.parametrize("actor,confirmed,identity", [
    (ActorKind.MODEL, True, "operator"),
    ("human", True, "operator"),
    (None, True, "operator"),
    (ActorKind.HUMAN, False, "operator"),
    (ActorKind.HUMAN, 1, "operator"),
    (ActorKind.HUMAN, True, "unconfigured-model"),
])
def test_nonhuman_or_unconfirmed_decisions_rejected(actor, confirmed, identity) -> None:
    manager = ApprovalManager(frozenset({"operator"}))
    request = manager.request("run-1", "inspect")
    with pytest.raises(HumanDecisionRequiredError):
        manager.decide(
            request.approval_id, run_id="run-1", tool_name="inspect",
            status=ApprovalStatus.APPROVED, decided_by=identity,
            actor_kind=actor, human_confirmed=confirmed,
        )
    assert manager.get(request.approval_id, run_id="run-1", tool_name="inspect") == request


def test_no_default_approvers_and_unknown_record() -> None:
    manager = ApprovalManager()
    request = manager.request("run-1", "inspect")
    with pytest.raises(HumanDecisionRequiredError):
        decide(manager, request, ApprovalStatus.APPROVED)
    with pytest.raises(UnknownApprovalError) as exc:
        manager.get("missing", run_id="run-1", tool_name="inspect")
    assert exc.value.code == "UNKNOWN_APPROVAL"


@pytest.mark.parametrize("status", [ApprovalStatus.PENDING, "approved", None])
def test_invalid_decision_is_atomic(status) -> None:
    manager = ApprovalManager(frozenset({"operator"}))
    request = manager.request("run-1", "inspect")
    with pytest.raises(ApprovalError):
        decide(manager, request, status)
    assert manager.get(request.approval_id, run_id="run-1", tool_name="inspect") == request


@pytest.mark.parametrize("run_id,tool_name", [("", "inspect"), ("run", " "), (None, "inspect")])
def test_invalid_request(run_id, tool_name) -> None:
    with pytest.raises(ApprovalError):
        ApprovalManager().request(run_id, tool_name)


def test_bound_status_policy_integration() -> None:
    manager = ApprovalManager(frozenset({"operator"}))
    request = manager.request("run-1", "inspect")
    definition = tool(RiskLevel.HIGH)
    assert not PermissionEngine().evaluate(definition, {"read"}, request.status).allowed
    decided = decide(manager, request, ApprovalStatus.APPROVED)
    bound = manager.get(decided.approval_id, run_id="run-1", tool_name=definition.name)
    assert PermissionEngine().evaluate(definition, {"read"}, bound.status).allowed
    object.__setattr__(decided, "status", ApprovalStatus.DENIED)
    assert manager.get(bound.approval_id, run_id="run-1", tool_name="inspect") == bound


def test_no_execution_or_external_effects(tmp_path: Path) -> None:
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
        "os.mkdir", "os.remove", "os.rename", "os.rmdir", "os.system", "os.fork",
        "os.posix_spawn", "os.exec", "sqlite3.connect",
    }:
        raise AssertionError("Unexpected external effect")
sys.addaudithook(guard)
from arqon_os.tools.registry import ToolRegistry, ToolDefinition, RiskLevel
from arqon_os.tools.permissions import PermissionEngine
from arqon_os.tools.approvals import ApprovalManager, ApprovalStatus, ActorKind
registry = ToolRegistry()
registry.register(ToolDefinition("fake", "metadata only", "test", RiskLevel.HIGH, frozenset({"read"})))
tool = registry.get("fake")
registry.list_tools()
manager = ApprovalManager(frozenset({"operator"}))
request = manager.request("run", "fake")
assert not PermissionEngine().evaluate(tool).allowed
record = manager.decide(
    request.approval_id, run_id="run", tool_name="fake", status=ApprovalStatus.APPROVED,
    decided_by="operator", actor_kind=ActorKind.HUMAN, human_confirmed=True,
)
assert PermissionEngine().evaluate(tool, frozenset({"read"}), record.status).allowed
assert not hasattr(registry, "execute")
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []


# Context binding and consumption tests; all clocks/data are local fixtures.
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

from arqon_os.tools import approvals as approval_module
from arqon_os.tools.approvals import (
    ApprovalContext, ApprovalConsumedError, ApprovalContextUnboundError,
    ApprovalExpiredError, InvalidApprovalContextError,
)


def bound_context(arguments=None, target="https://example.invalid/", run="run-1", name="inspect"):
    return ApprovalContext(run, name, target, {} if arguments is None else arguments)


def bound_approved(manager, ctx):
    pending = manager.request(ctx.run_id, ctx.tool_name, context=ctx)
    return decide(manager, pending, ApprovalStatus.APPROVED)


def test_context_order_types_and_deep_snapshot():
    args = {"z": [True, None, 1, 1.0, "1"], "a": {"y": 2, "x": 1}}
    ctx = bound_context(args)
    same = bound_context({"a": {"x": 1, "y": 2}, "z": [True, None, 1, 1.0, "1"]})
    assert ctx == same
    assert len(ctx.context_digest) == 64
    assert ctx.canonical_arguments == '{"a":{"x":1,"y":2},"z":[true,null,1,1.0,"1"]}'
    args["z"].append("changed")
    assert ctx == same
    variants = [bound_context({"value": value}).context_digest for value in (True, 1, 1.0, "1")]
    assert len(set(variants)) == 4
    with pytest.raises(FrozenInstanceError):
        setattr(ctx, "context_digest", "forged")


@pytest.mark.parametrize("arguments", [
    {"x": float("nan")}, {"x": float("inf")}, {"x": float("-inf")},
    {"x": (1, 2)}, {"x": {1, 2}}, {"x": object()}, {1: "value"},
    '{"x":1,"x":2}', {"password": "secret"}, {"nested": {"api_key": "secret"}},
])
def test_invalid_context_values(arguments):
    with pytest.raises(InvalidApprovalContextError):
        bound_context(arguments)


@pytest.mark.parametrize("target", [
    "https://user:password@example.invalid/", "https://example.invalid/?token=secret",
    "https://example.invalid/#secret", "not-a-url",
])
def test_context_rejects_sensitive_targets(target):
    with pytest.raises(InvalidApprovalContextError):
        bound_context(target=target)


def test_context_cycles_and_tamper_rejected():
    args = {}
    args["self"] = args
    with pytest.raises(InvalidApprovalContextError):
        bound_context(args)
    ctx = bound_context()
    object.__setattr__(ctx, "context_digest", "0" * 64)
    with pytest.raises(InvalidApprovalContextError):
        ApprovalManager().request("run-1", "inspect", context=ctx)


@pytest.mark.parametrize("changed", [
    {"arguments": {"changed": True}}, {"target": "https://other.invalid/"},
    {"run": "other-run"}, {"name": "other-tool"},
])
def test_changed_context_never_consumes(changed):
    manager = ApprovalManager(frozenset({"operator"}))
    ctx = bound_context()
    record = bound_approved(manager, ctx)
    with pytest.raises(ApprovalBindingError):
        manager.consume(record.approval_id, context=bound_context(**changed))
    assert manager.get(record.approval_id, run_id=ctx.run_id, tool_name=ctx.tool_name) == record
    assert manager.consume(record.approval_id, context=ctx).consumed_at is not None


def test_expiry_boundary_and_no_extension(monkeypatch):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(approval_module, "_now", lambda: now)
    manager = ApprovalManager(frozenset({"operator"}))
    ctx = bound_context()
    record = bound_approved(manager, ctx)
    assert record.expires_at == record.requested_at + timedelta(minutes=10)
    monkeypatch.setattr(approval_module, "_now", lambda: record.expires_at)
    with pytest.raises(ApprovalExpiredError):
        manager.consume(record.approval_id, context=ctx)
    assert manager.get(record.approval_id, run_id="run-1", tool_name="inspect") == record


def test_cannot_decide_after_expiry(monkeypatch):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(approval_module, "_now", lambda: now)
    manager = ApprovalManager(frozenset({"operator"}))
    pending = manager.request("run-1", "inspect", context=bound_context())
    monkeypatch.setattr(approval_module, "_now", lambda: pending.expires_at)
    with pytest.raises(ApprovalExpiredError):
        decide(manager, pending, ApprovalStatus.APPROVED)
    assert manager.get(pending.approval_id, run_id="run-1", tool_name="inspect") == pending


@pytest.mark.parametrize("expiry", [
    datetime(2026, 1, 1), datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1))),
    datetime(2025, 1, 1, tzinfo=UTC), "tomorrow",
])
def test_invalid_expiry(expiry, monkeypatch):
    monkeypatch.setattr(approval_module, "_now", lambda: datetime(2026, 1, 1, tzinfo=UTC))
    with pytest.raises(ApprovalError):
        ApprovalManager().request("run-1", "inspect", context=bound_context(), expires_at=expiry)


def test_success_and_replay():
    manager = ApprovalManager(frozenset({"operator"}))
    ctx = bound_context()
    record = bound_approved(manager, ctx)
    consumed = manager.consume(record.approval_id, context=ctx)
    assert consumed.consumed_at.tzinfo is UTC
    assert consumed.expires_at == record.expires_at
    assert record.consumed_at is None
    with pytest.raises(ApprovalConsumedError):
        manager.consume(record.approval_id, context=ctx)


def test_concurrent_consumption_exactly_one_wins():
    manager = ApprovalManager(frozenset({"operator"}))
    ctx = bound_context()
    record = bound_approved(manager, ctx)
    barrier = Barrier(2)
    def attempt():
        barrier.wait(timeout=5)
        try:
            manager.consume(record.approval_id, context=ctx)
            return "consumed"
        except ApprovalConsumedError:
            return "rejected"
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt) for _ in range(2)]
        assert sorted(f.result(timeout=10) for f in futures) == ["consumed", "rejected"]


@pytest.mark.parametrize("status", [ApprovalStatus.PENDING, ApprovalStatus.DENIED])
def test_unapproved_cannot_consume(status):
    manager = ApprovalManager(frozenset({"operator"}))
    ctx = bound_context()
    record = manager.request("run-1", "inspect", context=ctx)
    if status is ApprovalStatus.DENIED:
        record = decide(manager, record, status)
    with pytest.raises(ApprovalError):
        manager.consume(record.approval_id, context=ctx)
    assert manager.get(record.approval_id, run_id="run-1", tool_name="inspect") == record
