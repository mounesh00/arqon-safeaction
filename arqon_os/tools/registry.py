"""Explicit metadata registry with no executable tool handles."""

from dataclasses import dataclass, replace
from enum import Enum

from arqon_os.core.errors import ArqonError


class ToolValidationError(ArqonError):
    code = "INVALID_TOOL"
    public_message = "Tool metadata is invalid."


class DuplicateToolError(ArqonError):
    code = "DUPLICATE_TOOL"
    public_message = "The tool is already registered."


class UnknownToolError(ArqonError):
    code = "UNKNOWN_TOOL"
    public_message = "The tool is not registered."


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    category: str
    risk_level: RiskLevel
    required_permissions: frozenset[str]

    def __post_init__(self) -> None:
        for value in (self.name, self.description, self.category):
            if not isinstance(value, str) or not value.strip():
                raise ToolValidationError()
        if not isinstance(self.risk_level, RiskLevel):
            raise ToolValidationError()
        if not isinstance(self.required_permissions, (set, frozenset)) or any(
            not isinstance(p, str) or not p.strip() or p == "*"
            for p in self.required_permissions
        ):
            raise ToolValidationError()
        object.__setattr__(self, "required_permissions", frozenset(self.required_permissions))


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        if not isinstance(tool, ToolDefinition):
            raise ToolValidationError()
        snapshot = replace(tool)
        if snapshot.name in self._tools:
            raise DuplicateToolError()
        self._tools[snapshot.name] = snapshot

    def get(self, name: str) -> ToolDefinition:
        if not isinstance(name, str) or name not in self._tools:
            raise UnknownToolError()
        return replace(self._tools[name])

    def list_tools(self) -> list[ToolDefinition]:
        return [replace(self._tools[name]) for name in sorted(self._tools)]
