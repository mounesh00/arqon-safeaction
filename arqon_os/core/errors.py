"""Errors with stable codes and conservative public serialization."""

from typing import ClassVar


class ArqonError(Exception):
    """Keep caller details local; serialize only a fixed, safe public message.

    Custom messages may contain sensitive context and are available through str()
    for local handling only. Never send str(error), args, causes or tracebacks to
    public logs or clients. to_dict() deliberately excludes all caller input.
    """

    code: ClassVar[str] = "ARQON_ERROR"
    public_message: ClassVar[str] = "An Arqon operation failed."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(self.public_message if message is None else message)

    def to_dict(self) -> dict[str, str]:
        """Return only the error type's code and fixed public message."""
        return {"code": type(self).code, "message": type(self).public_message}


class ConfigurationError(ArqonError):
    code = "CONFIGURATION_ERROR"
    public_message = "The Arqon configuration is invalid."


class PermissionDeniedError(ArqonError):
    code = "PERMISSION_DENIED"
    public_message = "Permission was denied."


class ApprovalRequiredError(PermissionDeniedError):
    code = "APPROVAL_REQUIRED"
    public_message = "Explicit approval is required."


class ToolExecutionError(ArqonError):
    code = "TOOL_EXECUTION_ERROR"
    public_message = "Tool execution failed."


class WorkflowError(ArqonError):
    code = "WORKFLOW_ERROR"
    public_message = "The workflow failed."
