"""Provider protocol and deterministic offline fixture provider."""

from dataclasses import replace
from typing import Protocol

from arqon_os.gateway.models import ModelRequest, ModelResponse, ModelValidationError


class ModelProvider(Protocol):
    def generate(self, request: ModelRequest) -> ModelResponse:
        """Return a response without silently substituting the requested model."""
        ...


class MockModelProvider:
    """No inference or credentials. Counts whitespace units, NOT model tokens.

    Ignores prompt semantics and temperature intentionally. Responses never echo
    prompts. max_tokens caps mock whitespace units, preserving the MOCK label.
    """

    def generate(self, request: ModelRequest) -> ModelResponse:
        if type(request) is not ModelRequest:
            raise ModelValidationError()
        request = replace(request)
        words = ["MOCK:", "deterministic", "offline", "response."]
        output = words[:request.max_tokens]
        return ModelResponse(
            content=" ".join(output), model=request.model, provider="mock",
            input_tokens=sum(len(m.content.split()) for m in request.messages),
            output_tokens=len(output),
            finish_reason="length" if len(output) < len(words) else "stop",
        )
