"""Fixed policy evaluation only; an allowed decision does not execute anything.

Approval status is a trusted input: obtain it from ApprovalManager.get with the
exact run/tool binding. Never accept status or grants from model output.
This module does not authenticate callers or modify ArqonConfig.
"""

from dataclasses import dataclass

from arqon_os.tools.approvals import ApprovalStatus
from arqon_os.tools.registry import RiskLevel, ToolDefinition


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    reason_code: str
    requires_approval: bool


class PermissionEngine:
    def evaluate(
        self, tool: ToolDefinition,
        granted_permissions: frozenset[str] = frozenset(),
        approval_status: ApprovalStatus = ApprovalStatus.PENDING,
    ) -> PermissionDecision:
        """Fail closed; requires_approval describes the tool's risk policy.

        No declared permissions means no authorization contract, so deny. Empty
        grants and '*' never authorize tools. A denial is respected even for LOW.
        LOW may proceed with complete grants and a PENDING status; other risks
        additionally need APPROVED. There are no configurable policy overrides.
        """
        if not isinstance(tool, ToolDefinition) or not isinstance(tool.risk_level, RiskLevel):
            return PermissionDecision(False, "INVALID_TOOL", True)
        required = tool.risk_level is not RiskLevel.LOW
        if not isinstance(approval_status, ApprovalStatus):
            return PermissionDecision(False, "UNKNOWN_APPROVAL_STATE", required)
        if not isinstance(granted_permissions, (set, frozenset)) or any(
            not isinstance(p, str) or not p.strip() or p == "*" for p in granted_permissions
        ):
            return PermissionDecision(False, "INVALID_PERMISSION_GRANTS", required)
        if not tool.required_permissions:
            return PermissionDecision(False, "UNDECLARED_PERMISSIONS", required)
        if not tool.required_permissions.issubset(granted_permissions):
            return PermissionDecision(False, "MISSING_PERMISSIONS", required)
        if approval_status is ApprovalStatus.DENIED:
            return PermissionDecision(False, "APPROVAL_DENIED", required)
        if required and approval_status is not ApprovalStatus.APPROVED:
            return PermissionDecision(False, "APPROVAL_REQUIRED", True)
        return PermissionDecision(True, "ALLOWED", required)
