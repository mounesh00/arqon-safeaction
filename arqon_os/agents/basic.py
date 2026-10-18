"""One model request per run; only runtime lifecycle metadata is persisted."""

from dataclasses import dataclass

from arqon_os.core.errors import ArqonError
from arqon_os.core.results import RunStatus
from arqon_os.gateway.gateway import ModelGateway, ModelTimeoutError
from arqon_os.gateway.models import ModelMessage, ModelRequest
from arqon_os.runtime.engine import AgentRuntime


class InvalidAgentTaskError(ArqonError):
    code = "INVALID_AGENT_TASK"
    public_message = "A task must contain between 1 and 4000 characters of text."


@dataclass(frozen=True)
class AgentResult:
    run_id: str
    status: RunStatus
    response: str
    provider: str
    model: str
    error_code: str | None = None


class BasicAgent:
    """Use explicitly injected runtime/gateway; never select providers implicitly.

    Persistence failures propagate rather than returning an unsaved result.
    Model failures return a fixed public error without provider exception details.
    """

    def __init__(
        self, runtime: AgentRuntime, gateway: ModelGateway,
        provider_name: str = "mock", model: str = "mock-model",
        *, timeout_seconds: float = 30.0,
    ) -> None:
        # Validate model configuration before any run can be created.
        ModelRequest(messages=(ModelMessage("system", "Validate configuration."),), model=model,
                     timeout_seconds=timeout_seconds)
        if not isinstance(provider_name, str) or not provider_name.strip():
            raise ValueError("A provider name is required.")
        self._runtime = runtime
        self._gateway = gateway
        self._provider_name = provider_name
        self._model = model
        self._timeout_seconds = timeout_seconds

    def run(self, task: str) -> AgentResult:
        if not isinstance(task, str) or not task.strip() or len(task) > 4000:
            raise InvalidAgentTaskError()
        request = ModelRequest(
            messages=(
                ModelMessage("system", "Answer the user task concisely. No tools are available."),
                ModelMessage("user", task),
            ),
            model=self._model, max_tokens=512, temperature=0.0,
            timeout_seconds=self._timeout_seconds,
        )
        # Avoid storing user prompt contents in runtime lifecycle metadata.
        run = self._runtime.create_run("basic_agent")
        self._runtime.start_run(run.run_id)
        try:
            response = self._gateway.generate(self._provider_name, request)
        except Exception as exc:
            code = "MODEL_TIMEOUT" if isinstance(exc, ModelTimeoutError) else "AGENT_MODEL_FAILED"
            failed = self._runtime.fail_run(run.run_id, code)
            return AgentResult(
                failed.run_id, failed.status, "", self._provider_name,
                self._model, failed.error_code,
            )
        completed = self._runtime.complete_run(run.run_id)
        return AgentResult(
            completed.run_id, completed.status, response.content,
            response.provider, response.model,
        )
