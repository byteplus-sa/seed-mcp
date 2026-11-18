"""Shared HTTP gateway base for BytePlus provider clients.

Both provider gateways (ModelArk for Seedream/Seedance and Seed Speech for Seed
Audio) share the same lifecycle, transport, timeout, and connection-error
normalization. Subclasses provide provider-specific headers, the provider name,
request-ID extraction, and HTTP error normalization.
"""

from __future__ import annotations

import asyncio
import math
import re
from abc import ABC, abstractmethod
from time import perf_counter
from typing import TYPE_CHECKING, Any, ClassVar

import httpx
from fastmcp.telemetry import get_tracer, record_span_error
from pydantic import BaseModel

from ark_mcp.domain.errors import NormalizedProviderError, ProviderError, ProviderName
from ark_mcp.execution import authorize_provider_request
from ark_mcp.observability.logger import error as log_error
from ark_mcp.observability.logger import info as log_info
from ark_mcp.observability.metrics import PROVIDER_DURATION, PROVIDER_REQUESTS
from ark_mcp.sqlite_io import drain_task

if TYPE_CHECKING:
    from collections.abc import Callable

_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)


def require_api_key(api_key: str) -> str:
    if (
        not isinstance(api_key, str)
        or not 1 <= len(api_key) <= 4096
        or any(not 33 <= ord(char) <= 126 for char in api_key)
    ):
        raise ValueError("API key must be 1-4096 printable ASCII characters without whitespace.")
    return api_key


def safe_provider_text(value: object, fallback: str = "") -> str:
    from ark_mcp.security.credentials import redact_request_secrets

    if not isinstance(value, (str, int)):
        return fallback
    text = redact_request_secrets(str(value))
    text = _URL_PATTERN.sub("[REDACTED_URL]", text)
    text = " ".join(text.split())
    if len(text) > 600:
        return f"{text[:597].rstrip()}..."
    return text or fallback


def retry_after_seconds(value: str | None) -> float | None:
    try:
        delay = float(value) if value is not None else None
    except ValueError:
        return None
    return delay if delay is not None and math.isfinite(delay) and delay >= 0 else None


class BlockingSdkCalls:
    """Keep SDK calls and close alive until their threads drain, even after cancellation."""

    def __init__(self) -> None:
        self._pending: set[asyncio.Task[Any]] = set()
        self._close_task: asyncio.Task[None] | None = None

    async def run[T](self, call: Callable[[], T], *, side_effect: bool) -> T:
        if self._close_task is not None:
            raise RuntimeError("SDK client is closed or closing.")
        if side_effect:
            await authorize_provider_request(side_effect=True)
        task = asyncio.create_task(asyncio.to_thread(call))
        self._pending.add(task)
        try:
            return await drain_task(task)
        finally:
            self._pending.discard(task)

    async def close(self, close: Callable[[], Any] | None, *, provider: ProviderName) -> None:
        async def finish() -> None:
            await asyncio.gather(*self._pending, return_exceptions=True)
            if close is not None:
                try:
                    await asyncio.to_thread(close)
                except Exception:
                    log_error("sdk_close_failed", provider=provider)

        if self._close_task is None:
            self._close_task = asyncio.create_task(finish())
        await drain_task(self._close_task)


class BaseHttpGateway(ABC):
    """Abstract base for authenticated BytePlus HTTP gateway clients."""

    PROVIDER: ClassVar[ProviderName]
    _api_key: str
    _base_url: str
    _timeout: float
    _connect_timeout: float
    _client: httpx.AsyncClient | None

    @abstractmethod
    def _headers(self) -> dict[str, str]:
        """Return the auth/content headers for a request."""

    @staticmethod
    def extract_request_id(response: httpx.Response) -> str | None:
        """Extract the provider request/diagnostic ID from a response.

        Default implementation returns ``None``. Providers that return a
        diagnostic ID in response headers (e.g. ModelArk's ``X-Request-Id``,
        Seed Speech's ``X-Tt-Logid``) override this. Providers that return
        the ID in the response body extract it from the parsed body in their
        service layer instead.
        """
        return None

    @classmethod
    @abstractmethod
    def normalize_error(cls, response: httpx.Response, operation: str) -> ProviderError:
        """Normalize an error HTTP response into a ``ProviderError``."""

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout, connect=self._connect_timeout),
                follow_redirects=False,
                trust_env=False,
            )
        return self._client

    @property
    def base_url(self) -> str:
        return self._base_url

    async def _request(
        self, method: str, path: str, *, side_effect: bool, **kwargs: Any
    ) -> httpx.Response:
        client = await self._ensure_client()
        url = f"{self._base_url}{path}"
        log_info(f"{self.PROVIDER}_request", method=method)
        headers = kwargs.pop("headers", None) or self._headers()
        operation = method.lower()
        started = perf_counter()
        with get_tracer().start_as_current_span(
            f"provider.{self.PROVIDER}.{operation}",
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            span.set_attribute("provider.name", self.PROVIDER)
            span.set_attribute("http.request.method", method)
            await authorize_provider_request(side_effect=side_effect)
            try:
                response = await client.request(method, url, headers=headers, **kwargs)
            except Exception as exc:
                record_span_error(span, RuntimeError("Provider request failed."))
                PROVIDER_REQUESTS.labels(
                    provider=self.PROVIDER,
                    operation=operation,
                    status="exception",
                ).inc()
                if isinstance(exc, httpx.TransportError):
                    raise type(exc)("Provider transport request failed.") from None
                raise httpx.TransportError("Provider request failed.") from None
            else:
                span.set_attribute("http.response.status_code", response.status_code)
                status = "error" if response.status_code >= 400 else "success"
                PROVIDER_REQUESTS.labels(
                    provider=self.PROVIDER,
                    operation=operation,
                    status=status,
                ).inc()
                return response
            finally:
                PROVIDER_DURATION.labels(
                    provider=self.PROVIDER,
                    operation=operation,
                ).observe(perf_counter() - started)

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def health_check(self, *, timeout_seconds: float = 2.0) -> bool:
        """Return True if the provider base URL responds within the timeout."""
        client = await self._ensure_client()
        try:
            await client.get(
                self._base_url,
                timeout=httpx.Timeout(timeout_seconds, connect=timeout_seconds),
            )
        except Exception:
            return False
        return True

    @classmethod
    def normalize_timeout(cls, operation: str, *, side_effect: bool = True) -> ProviderError:
        """Normalize an HTTP timeout.

        ``side_effect=True`` (the default) is for mutations such as create,
        generate, cancel, and delete: the provider may have acted, so the error
        is ambiguous and must not be retried blindly. ``side_effect=False`` is
        for read-only queries and completions that create no provider state:
        the error is retryable and not ambiguous.
        """
        if side_effect:
            message = (
                f"Request timed out during '{operation}'. "
                "The operation may have succeeded. "
                "Do not retry blindly; reconcile using the task ID or request ID."
            )
        else:
            message = (
                f"Request timed out during '{operation}'. "
                "No provider-side state was created, so it is safe to retry."
            )
        return ProviderError(
            NormalizedProviderError(
                provider=cls.PROVIDER,
                operation=operation,
                http_status=None,
                code="TIMEOUT",
                message=message,
                request_id=None,
                retryable=not side_effect,
                ambiguous_completion=side_effect,
            )
        )

    @classmethod
    def normalize_connection_error(cls, operation: str, exc: Exception) -> ProviderError:
        return ProviderError(
            NormalizedProviderError(
                provider=cls.PROVIDER,
                operation=operation,
                http_status=None,
                code="CONNECTION_ERROR",
                message=f"Failed to connect to {cls.PROVIDER}. No request was dispatched.",
                request_id=None,
                retryable=True,
                ambiguous_completion=False,
            )
        )

    @classmethod
    def normalize_transport_error(
        cls, operation: str, exc: Exception, *, side_effect: bool = True
    ) -> ProviderError:
        """Only connection/pool failures are demonstrably safe before dispatch."""
        if isinstance(exc, httpx.ConnectError):
            return cls.normalize_connection_error(operation, exc)
        if isinstance(exc, (httpx.ConnectTimeout, httpx.PoolTimeout)):
            return cls.normalize_timeout(operation, side_effect=False)
        if isinstance(exc, httpx.TimeoutException):
            return cls.normalize_timeout(operation, side_effect=side_effect)
        message = f"Transport error during '{operation}'."
        if side_effect:
            message += " The operation may have succeeded; do not retry blindly."
        return ProviderError(
            NormalizedProviderError(
                provider=cls.PROVIDER,
                operation=operation,
                http_status=None,
                code="TRANSPORT_ERROR",
                message=message,
                request_id=None,
                retryable=not side_effect,
                ambiguous_completion=side_effect,
            )
        )

    @classmethod
    def invalid_response(
        cls, operation: str, *, http_status: int, request_id: str | None, mutation: bool
    ) -> ProviderError:
        return ProviderError(
            NormalizedProviderError(
                provider=cls.PROVIDER,
                operation=operation,
                http_status=http_status,
                code="INVALID_RESPONSE",
                message="Provider returned a success response in an unexpected shape.",
                request_id=request_id,
                retryable=False,
                ambiguous_completion=mutation,
            )
        )

    @classmethod
    def parse_response[T: BaseModel](
        cls,
        response: httpx.Response,
        operation: str,
        model: type[T],
        *,
        side_effect: bool = True,
    ) -> T:
        try:
            return model.model_validate(response.json())
        except ValueError:
            raise cls.invalid_response(
                operation,
                http_status=response.status_code,
                request_id=cls.extract_request_id(response),
                mutation=side_effect,
            ) from None
