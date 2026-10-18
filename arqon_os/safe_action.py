"""Deterministic, operator-approved local checklist workflow; no MCP exposure."""

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
import hmac
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from arqon_os.core.errors import ArqonError
from arqon_os.runtime.storage import SQLiteRunStore
from arqon_os.tools.approvals import (
    ActorKind, ApprovalBindingError, ApprovalContext, ApprovalManager, ApprovalStatus,
    ApprovalExpiredError,
)
from arqon_os.tools.permissions import PermissionEngine
from arqon_os.tools.registry import RiskLevel, ToolDefinition


class SafeActionError(ArqonError):
    code = "SAFE_ACTION_FAILED"
    public_message = "The checklist operation could not be completed."


class SafeActionPermissionError(SafeActionError):
    code = "SAFE_ACTION_PERMISSION_DENIED"
    public_message = "Checklist save permission and human approval are required."


@dataclass(frozen=True)
class ChecklistProposal:
    proposal_id: str
    title: str
    items: tuple[str, ...]
    approval_status: ApprovalStatus = ApprovalStatus.PENDING


class SafeActionWorkflow:
    """Trusted local operator API. Configure ApprovalManager outside agent code.

    Call initialize explicitly. Pending proposals/approvals live in memory;
    saved checklists survive restart. No client-supplied approval flag is trusted.
    """

    def __init__(self, database_path: Path, approvals: ApprovalManager) -> None:
        self._path = Path(database_path)
        self._approvals = approvals
        self._proposals: dict[str, ChecklistProposal] = {}
        self._approval_ids: dict[str, str] = {}
        self._initialized = False
        self._tool = ToolDefinition(
            "safeaction.save_travel_checklist", "Save a reviewed local travel checklist.",
            "safeaction", RiskLevel.MEDIUM, frozenset({"checklist.save"}),
        )

    def initialize(self) -> None:
        # Reuse existing database initialization/version; no second agent store.
        SQLiteRunStore(self._path).initialize()
        with self._connection(initializing=True) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS safeaction_checklists (
                proposal_id TEXT PRIMARY KEY, title TEXT NOT NULL,
                items_json TEXT NOT NULL, context_digest TEXT NOT NULL,
                approval_id TEXT NOT NULL UNIQUE, saved_at TEXT NOT NULL)""")
        self._initialized = True

    @contextmanager
    def _connection(self, *, initializing: bool = False):
        if not self._initialized and not initializing:
            raise SafeActionError()
        conn = None
        try:
            conn = sqlite3.connect(self._path.absolute().as_uri() + "?mode=rw", uri=True)
            with conn:
                yield conn
        except (sqlite3.Error, OSError):
            raise SafeActionError() from None
        finally:
            if conn is not None:
                conn.close()

    def _context(self, proposal: ChecklistProposal) -> ApprovalContext:
        if (type(proposal) is not ChecklistProposal
                or self._proposals.get(proposal.proposal_id) != proposal):
            raise ApprovalBindingError()
        return ApprovalContext(proposal.proposal_id, self._tool.name,
            "urn:arqon:safeaction.save_travel_checklist",
            {"proposal_id": proposal.proposal_id, "title": proposal.title,
             "items": list(proposal.items)})

    def prepare(self) -> ChecklistProposal:
        proposal = ChecklistProposal(str(uuid4()), "Travel checklist", (
            "Check travel documents and booking details",
            "Pack clothing and toiletries",
            "Pack required medication",
            "Charge devices and pack chargers",
            "Confirm transport and accommodation",
        ))
        self._proposals[proposal.proposal_id] = proposal
        record = self._approvals.request(proposal.proposal_id, self._tool.name,
                                         context=self._context(proposal))
        self._approval_ids[proposal.proposal_id] = record.approval_id
        return replace(proposal)

    def approve(self, proposal: ChecklistProposal, *, decided_by: str,
                actor_kind: ActorKind, human_confirmed: bool) -> ChecklistProposal:
        self._context(proposal)
        self._approvals.decide(self._approval_ids[proposal.proposal_id],
            run_id=proposal.proposal_id, tool_name=self._tool.name,
            status=ApprovalStatus.APPROVED, decided_by=decided_by,
            actor_kind=actor_kind, human_confirmed=human_confirmed)
        approved = replace(proposal, approval_status=ApprovalStatus.APPROVED)
        self._proposals[proposal.proposal_id] = approved
        return replace(approved)

    def save(self, proposal: ChecklistProposal, *, grants: frozenset[str] = frozenset()) -> ChecklistProposal:
        context = self._context(proposal)
        approval_id = self._approval_ids[proposal.proposal_id]
        record = self._approvals.get(approval_id, run_id=proposal.proposal_id, tool_name=self._tool.name)
        if not PermissionEngine().evaluate(self._tool, grants, record.status).allowed:
            raise SafeActionPermissionError()
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            # Check expiry/replay and consume before any INSERT. A later database
            # failure burns the approval; never silently retry or restore it.
            self._approvals.consume(approval_id, context=context)
            conn.execute("INSERT INTO safeaction_checklists VALUES (?, ?, ?, ?, ?, ?)",
                (proposal.proposal_id, proposal.title, json.dumps(proposal.items),
                 context.context_digest, approval_id, datetime.now(UTC).isoformat()))
        return replace(proposal)

    def get(self, proposal_id: str) -> ChecklistProposal | None:
        with self._connection() as conn:
            row = conn.execute("SELECT proposal_id, title, items_json FROM safeaction_checklists WHERE proposal_id=?",
                               (proposal_id,)).fetchone()
        if row is None:
            return None
        return ChecklistProposal(row[0], row[1], tuple(json.loads(row[2])), ApprovalStatus.APPROVED)


class ProposalNotFoundError(SafeActionError):
    code = "PROPOSAL_NOT_FOUND"
    public_message = "The proposal was not found."


class ProposalConflictError(SafeActionError):
    code = "PROPOSAL_NOT_PENDING"
    public_message = "The proposal is no longer pending."


@dataclass(frozen=True)
class DurableProposal:
    proposal_id: str
    title: str
    items: tuple[str, ...]
    fingerprint: str
    created_at: datetime
    expires_at: datetime
    status: str


class PersistentSafeActionWorkflow(SafeActionWorkflow):
    """Shared proposal bridge. Only trusted authenticated operator code decides.

    The legacy prepare/approve/save workflow above is unchanged. Durable decisions
    reload SQLite and commit status plus checklist together, under a write lock.
    """

    def initialize(self) -> None:
        super().initialize()
        with self._connection() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS safeaction_proposals (
                proposal_id TEXT PRIMARY KEY, title TEXT NOT NULL,
                items_json TEXT NOT NULL, fingerprint TEXT NOT NULL,
                created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','expired')),
                decided_at TEXT, decided_by TEXT)""")

    def _durable_context(self, proposal_id, title, items) -> ApprovalContext:
        return ApprovalContext(proposal_id, self._tool.name,
            "urn:arqon:safeaction.save_travel_checklist",
            {"proposal_id": proposal_id, "title": title, "items": list(items)})

    def prepare(self) -> ChecklistProposal:
        proposal = super().prepare()
        context = self._durable_context(proposal.proposal_id, proposal.title, proposal.items)
        now = datetime.now(UTC)
        with self._connection() as conn:
            conn.execute("INSERT INTO safeaction_proposals VALUES (?, ?, ?, ?, ?, ?, 'pending', NULL, NULL)",
                (proposal.proposal_id, proposal.title, json.dumps(proposal.items), context.context_digest,
                 now.isoformat(), (now + timedelta(minutes=10)).isoformat()))
        return proposal

    def _load(self, conn, proposal_id: str) -> DurableProposal:
        row = conn.execute("SELECT proposal_id,title,items_json,fingerprint,created_at,expires_at,status "
                           "FROM safeaction_proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
        if row is None:
            raise ProposalNotFoundError()
        try:
            items = json.loads(row[2])
            if type(items) is not list or not items or any(type(item) is not str for item in items):
                raise ValueError()
            context = self._durable_context(row[0], row[1], items)
            created, expiry = datetime.fromisoformat(row[4]), datetime.fromisoformat(row[5])
            if (not hmac.compare_digest(context.context_digest, row[3])
                    or created.utcoffset() != timedelta(0) or expiry.utcoffset() != timedelta(0)
                    or not created < expiry <= created + timedelta(minutes=10)
                    or created > datetime.now(UTC)):
                raise ValueError()
            return DurableProposal(row[0], row[1], tuple(items), row[3], created, expiry, row[6])
        except (ValueError, TypeError, ArqonError):
            raise ApprovalBindingError() from None

    def _expire(self, conn, proposal: DurableProposal) -> DurableProposal:
        if proposal.status == "pending" and datetime.now(UTC) >= proposal.expires_at:
            conn.execute("UPDATE safeaction_proposals SET status='expired' WHERE proposal_id=? AND status='pending'",
                         (proposal.proposal_id,))
            return replace(proposal, status="expired")
        return proposal

    def get_proposal(self, proposal_id: str) -> DurableProposal:
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            return self._expire(conn, self._load(conn, proposal_id))

    def decide_proposal(self, proposal_id: str, *, fingerprint: str, approve: bool,
                        decided_by: str, actor_kind: ActorKind, human_confirmed: bool,
                        grants: frozenset[str] = frozenset()) -> DurableProposal:
        if type(approve) is not bool or type(fingerprint) is not str:
            raise ApprovalBindingError()
        review_tool = ToolDefinition("safeaction.review", "Review a local checklist.",
                                    "safeaction", RiskLevel.LOW, self._tool.required_permissions)
        if not PermissionEngine().evaluate(review_tool, grants).allowed:
            raise SafeActionPermissionError()
        expired = False
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            proposal = self._expire(conn, self._load(conn, proposal_id))
            if not hmac.compare_digest(proposal.fingerprint, fingerprint):
                raise ApprovalBindingError()
            if proposal.status == "expired":
                expired = True
            elif proposal.status != "pending":
                raise ProposalConflictError()
            else:
                context = self._durable_context(proposal.proposal_id, proposal.title, proposal.items)
                record = self._approvals.request(proposal_id, self._tool.name,
                    context=context, expires_at=proposal.expires_at)
                record = self._approvals.decide(record.approval_id, run_id=proposal_id,
                    tool_name=self._tool.name,
                    status=ApprovalStatus.APPROVED if approve else ApprovalStatus.DENIED,
                    decided_by=decided_by, actor_kind=actor_kind, human_confirmed=human_confirmed)
                if approve:
                    if not PermissionEngine().evaluate(self._tool, grants, record.status).allowed:
                        raise SafeActionPermissionError()
                    self._approvals.consume(record.approval_id, context=context)
                    conn.execute("INSERT INTO safeaction_checklists VALUES (?, ?, ?, ?, ?, ?)",
                        (proposal_id, proposal.title, json.dumps(proposal.items), context.context_digest,
                         record.approval_id, datetime.now(UTC).isoformat()))
                status = "approved" if approve else "rejected"
                conn.execute("UPDATE safeaction_proposals SET status=?,decided_at=?,decided_by=? "
                             "WHERE proposal_id=? AND status='pending'",
                             (status, datetime.now(UTC).isoformat(), decided_by, proposal_id))
                proposal = replace(proposal, status=status)
        if expired:
            raise ApprovalExpiredError()
        return proposal
