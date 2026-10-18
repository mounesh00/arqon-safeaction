"""Focused, offline tests of the standard-library core contracts."""

import json
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from arqon_os.core.config import ArqonConfig
from arqon_os.core.errors import (
    ApprovalRequiredError,
    ArqonError,
    ConfigurationError,
    PermissionDeniedError,
    ToolExecutionError,
    WorkflowError,
)
from arqon_os.core.results import OperationResult, RunStatus


def test_safe_defaults_and_no_environment_loading(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARQON_ENVIRONMENT", "production")
    monkeypatch.setenv("ARQON_REQUIRE_APPROVAL", "false")
    monkeypatch.setenv("ARQON_NETWORK_ENABLED", "true")
    config = ArqonConfig()
    assert config.app_name == "Arqon OS"
    assert config.version == "0.1.0"
    assert config.environment == "development"
    assert config.database_path == Path(".arqon-os/arqon.db")
    assert config.require_approval is True
    assert config.network_enabled is False


def test_immutable_configuration() -> None:
    config = ArqonConfig()
    with pytest.raises(FrozenInstanceError):
        setattr(config, "require_approval", False)


@pytest.mark.parametrize("environment", ["development", "testing", "staging", "production"])
def test_explicit_configuration(environment: str, tmp_path: Path) -> None:
    path = tmp_path / "custom.db"
    config = ArqonConfig(environment=environment, database_path=path, network_enabled=True)
    assert config.environment == environment
    assert config.database_path == path
    assert config.network_enabled is True
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("environment", ["", "unknown", "PRODUCTION", None, []])
def test_invalid_environment(environment: object) -> None:
    with pytest.raises(ConfigurationError):
        ArqonConfig(environment=environment)  # type: ignore[arg-type]


@pytest.mark.parametrize("approval", [False, None, 0, 1, "true"])
def test_approval_cannot_be_disabled_or_coerced(approval: object) -> None:
    with pytest.raises(ConfigurationError):
        ArqonConfig(require_approval=approval)  # type: ignore[arg-type]


@pytest.mark.parametrize("kwargs", [
    {"network_enabled": "false"}, {"database_path": "file.db"}, {"app_name": ""}, {"version": ""},
])
def test_invalid_configuration_types(kwargs: dict[str, object]) -> None:
    with pytest.raises(ConfigurationError):
        ArqonConfig(**kwargs)  # type: ignore[arg-type]


def test_independent_result_data() -> None:
    first = OperationResult(True, RunStatus.COMPLETED, "done")
    second = OperationResult(True, RunStatus.COMPLETED, "done")
    first.data["value"] = 42
    assert second.data == {}
    with pytest.raises(FrozenInstanceError):
        setattr(first, "status", RunStatus.FAILED)


@pytest.mark.parametrize("status", list(RunStatus))
@pytest.mark.parametrize("success", [False, True])
@pytest.mark.parametrize("code", [None, "TEST_ERROR"])
def test_result_invariants(status: RunStatus, success: bool, code: str | None) -> None:
    valid = success == (status is RunStatus.COMPLETED)
    valid = valid and (
        (status is RunStatus.FAILED and code is not None)
        or status is RunStatus.CANCELLED
        or (status in (RunStatus.PENDING, RunStatus.RUNNING, RunStatus.COMPLETED) and code is None)
    )
    if valid:
        result = OperationResult(success, status, "message", error_code=code)
        assert result.status is status
        assert result.error_code == code
    else:
        with pytest.raises(ValueError):
            OperationResult(success, status, "message", error_code=code)


@pytest.mark.parametrize("code", ["", "  ", 1])
def test_invalid_error_code(code: object) -> None:
    with pytest.raises(ValueError):
        OperationResult(False, RunStatus.FAILED, "failed", error_code=code)  # type: ignore[arg-type]


@pytest.mark.parametrize("kwargs", [
    {"success": 1}, {"status": "completed"}, {"message": None}, {"data": []},
])
def test_invalid_result_types(kwargs: dict[str, object]) -> None:
    values: dict[str, object] = {"success": True, "status": RunStatus.COMPLETED, "message": "done"}
    values.update(kwargs)
    with pytest.raises(ValueError):
        OperationResult(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("error_type,code", [
    (ArqonError, "ARQON_ERROR"),
    (ConfigurationError, "CONFIGURATION_ERROR"),
    (PermissionDeniedError, "PERMISSION_DENIED"),
    (ApprovalRequiredError, "APPROVAL_REQUIRED"),
    (ToolExecutionError, "TOOL_EXECUTION_ERROR"),
    (WorkflowError, "WORKFLOW_ERROR"),
])
def test_safe_error_serialization(error_type: type[ArqonError], code: str) -> None:
    secret = "password=secret-token https://user:pass@example.invalid"
    error = error_type(secret)
    error.__cause__ = RuntimeError("private traceback context")
    assert str(error) == secret
    assert error.code == code
    payload = error.to_dict()
    assert payload == {"code": code, "message": error_type.public_message}
    assert json.loads(json.dumps(payload)) == payload
    assert secret not in json.dumps(payload)
    assert "private" not in json.dumps(payload)
    payload["message"] = "changed"
    assert error.to_dict()["message"] == error_type.public_message
    assert str(error_type()) == error_type.public_message
    assert isinstance(error, ArqonError)


def test_imports_create_no_files(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # An audit hook rejects write attempts anywhere, not just in the temporary cwd.
    script = """
import os
import sys
def guard(event, args):
    if event == "open":
        mode, flags = args[1], args[2]
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
            isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)
        ):
            raise AssertionError("Unexpected file write")
    if event in {"os.mkdir", "os.remove", "os.rename", "os.rmdir", "socket.connect", "socket.getaddrinfo"}:
        raise AssertionError("Unexpected side effect")
sys.addaudithook(guard)
import arqon_os.core
import arqon_os.core.config
import arqon_os.core.results
import arqon_os.core.errors
arqon_os.core.config.ArqonConfig()
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []
