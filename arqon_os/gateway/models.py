"""Immutable provider-independent contracts; no credential fields."""

from dataclasses import dataclass, replace
from math import isfinite
from typing import Literal

from arqon_os.core.errors import ArqonError


class ModelValidationError(ArqonError):
    code = "INVALID_MODEL_CONTRACT"
    public_message = "The model request or response is invalid."


@dataclass(frozen=True)
class ModelMessage:
    role: Literal["system", "user", "assistant", "tool"]
    content: str

    def __post_init__(self) -> None:
        if self.role not in ("system", "user", "assistant", "tool") or type(self.content) is not str:
            raise ModelValidationError()


@dataclass(frozen=True)
class ModelRequest:
    """Generation limits, including a provider-enforced timeout in seconds.

    The future HTTP provider must enforce this at the network-client boundary
    and raise TimeoutError when exceeded. This contract cannot interrupt a
    synchronous provider that ignores the timeout; it is not a wall-clock guard.
    """
    messages: tuple[ModelMessage, ...]
    model: str
    max_tokens: int = 256
    temperature: float = 0.0
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if (
            not isinstance(self.messages, (tuple, list)) or not self.messages
            or any(type(m) is not ModelMessage for m in self.messages)
            or type(self.model) is not str or not self.model.strip()
            or type(self.max_tokens) is not int or self.max_tokens <= 0
            or type(self.temperature) not in (int, float)
            or not 0 <= self.temperature <= 2
            or type(self.timeout_seconds) not in (int, float)
            or self.timeout_seconds <= 0
            or (type(self.timeout_seconds) is float and not isfinite(self.timeout_seconds))
        ):
            raise ModelValidationError()
        object.__setattr__(self, "messages", tuple(replace(m) for m in self.messages))


@dataclass(frozen=True)
class ModelResponse:
    content: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    finish_reason: str

    def __post_init__(self) -> None:
        if (
            type(self.content) is not str
            or any(type(v) is not str or not v.strip() for v in (self.model, self.provider, self.finish_reason))
            or any(type(n) is not int or n < 0 for n in (self.input_tokens, self.output_tokens))
        ):
            raise ModelValidationError()
