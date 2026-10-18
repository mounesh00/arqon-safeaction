"""Explicit synchronous dispatch. Registered providers are trusted code.

No provider discovery, retries, fallback, environment reads or logging. This
foundation does not sandbox arbitrary providers or enforce synchronous timeouts.
"""

from dataclasses import replace

from arqon_os.core.errors import ArqonError
from arqon_os.gateway.models import ModelRequest, ModelResponse, ModelValidationError
from arqon_os.gateway.provider import ModelProvider


class ProviderRegistrationError(ArqonError):
    code = "INVALID_MODEL_PROVIDER"
    public_message = "The provider registration is invalid."


class DuplicateProviderError(ArqonError):
    code = "DUPLICATE_MODEL_PROVIDER"
    public_message = "The model provider is already registered."


class UnknownProviderError(ArqonError):
    code = "UNKNOWN_MODEL_PROVIDER"
    public_message = "The model provider is not registered."


class ProviderExecutionError(ArqonError):
    code = "MODEL_PROVIDER_FAILED"
    public_message = "The model provider failed."


class ModelTimeoutError(ProviderExecutionError):
    code = "MODEL_TIMEOUT"
    public_message = "Model generation timed out."


class InvalidProviderResponseError(ArqonError):
    code = "INVALID_PROVIDER_RESPONSE"
    public_message = "The provider returned an invalid or substituted response."


class ModelGateway:
    def __init__(self) -> None:
        self._providers: dict[str, ModelProvider] = {}

    def register_provider(self, name: str, provider: ModelProvider) -> None:
        if type(name) is not str or not name.strip() or not callable(getattr(provider, "generate", None)):
            raise ProviderRegistrationError()
        if name in self._providers:
            raise DuplicateProviderError()
        self._providers[name] = provider

    def generate(self, provider_name: str, request: ModelRequest) -> ModelResponse:
        if type(provider_name) is not str or provider_name not in self._providers:
            raise UnknownProviderError()
        if type(request) is not ModelRequest:
            raise ModelValidationError()
        checked = replace(request)
        expected_model, limit = checked.model, checked.max_tokens
        try:
            response = self._providers[provider_name].generate(checked)
        except (TimeoutError, ModelTimeoutError):
            raise ModelTimeoutError() from None
        except Exception:
            raise ProviderExecutionError() from None
        try:
            if type(response) is not ModelResponse:
                raise ModelValidationError()
            response = replace(response)
        except ModelValidationError:
            raise InvalidProviderResponseError() from None
        # Registration names are routing aliases; response.provider identifies the implementation.
        if response.model != expected_model or response.output_tokens > limit:
            raise InvalidProviderResponseError()
        return response
