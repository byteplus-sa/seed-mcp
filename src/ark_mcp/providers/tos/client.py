"""BytePlus TOS gateway — object upload and presigned URL generation.

Wraps the synchronous ``tos`` Python SDK (``TosClientV2``) behind
async-friendly methods using ``asyncio.to_thread``. The SDK handles
TOS4-HMAC-SHA256 request signing; this gateway adds error normalization
and structured logging.

TOS uses explicit startup credentials or an explicitly supplied IRSA provider,
never caller credentials or an ambient metadata credential chain.
"""

from __future__ import annotations

from typing import Any, cast

import tos
from tos.enum import HttpMethodType
from tos.exceptions import TosClientError, TosServerError
from tos.models2 import ContentLengthRange, PostSignatureCondition

from ark_mcp.config.env import get_settings
from ark_mcp.domain.errors import NormalizedProviderError, ProviderError, ProviderName
from ark_mcp.observability.logger import info as log_info
from ark_mcp.providers.base import BlockingSdkCalls
from ark_mcp.providers.tos.constants import (
    TEMPORARY_OBJECT_EXPIRES_DAYS,
    TEMPORARY_REFERENCE_TTL_SECONDS,
    TEMPORARY_UPLOAD_TTL_SECONDS,
)

PROVIDER: ProviderName = "tos"


class TosGateway:
    """BytePlus TOS gateway wrapping the ``tos`` SDK.

    The underlying ``TosClientV2`` is synchronous; every SDK call is dispatched
    via ``asyncio.to_thread`` so the event loop is never blocked.  SDK
    exceptions (``TosServerError`` / ``TosClientError``) are normalized to
    ``ProviderError`` so the retry policy and error-result helpers work
    uniformly across all providers.
    """

    def __init__(
        self,
        *,
        client: Any = None,
        bucket: str | None = None,
        presign_ttl: int | None = None,
        credentials_provider: Any = None,
    ) -> None:
        settings = get_settings()
        self._bucket = bucket if bucket is not None else settings.tos_bucket
        self._region = settings.tos_region
        self._endpoint = settings.tos_endpoint
        self._credentials_provider = credentials_provider
        if settings.tos_credential_mode == "irsa" and credentials_provider is None:
            raise ValueError("IRSA requires a lifespan-owned credential provider.")
        self._upload_origin = f"https://{self._bucket}.tos-{settings.tos_region}.bytepluses.com/"
        self._security_token = settings.tos_security_token
        self._presign_ttl = (
            presign_ttl if presign_ttl is not None else settings.tos_presign_ttl_seconds
        )
        self._client: Any = client or tos.TosClientV2(
            ak=settings.tos_access_key,
            sk=settings.tos_secret_key,
            endpoint=settings.tos_endpoint,
            region=settings.tos_region,
            security_token=settings.tos_security_token or None,
            **({"credentials_provider": credentials_provider} if credentials_provider else {}),
        )
        self._calls = BlockingSdkCalls()

    async def upload_bytes(self, *, key: str, data: bytes, mime_type: str) -> None:
        """Upload raw bytes to TOS via ``put_object``."""

        def _upload() -> None:
            output = self._client.put_object(
                bucket=self._bucket,
                key=key,
                content=data,
                content_type=mime_type,
            )
            request_id = getattr(output, "request_id", None)
            log_info("tos_upload", key=key, request_id=request_id, bytes=len(data))

        await self._dispatch(_upload, operation="upload")

    async def upload_file(self, *, key: str, file_path: str, mime_type: str) -> None:
        """Upload a local file to TOS via ``put_object_from_file``.

        Streams the file without loading it fully into memory.
        """

        def _upload() -> None:
            output = self._client.put_object_from_file(
                bucket=self._bucket,
                key=key,
                file_path=file_path,
                content_type=mime_type,
            )
            request_id = getattr(output, "request_id", None)
            log_info("tos_upload_file", key=key, file_path=file_path, request_id=request_id)

        await self._dispatch(_upload, operation="upload_file")

    async def presign_get(self, *, key: str, expires: int | None = None) -> str:
        """Generate a presigned HTTPS GET URL for an object."""
        ttl = expires or self._presign_ttl

        def _presign() -> str:
            return str(
                self._client.pre_signed_url(
                    HttpMethodType.Http_Method_Get,
                    bucket=self._bucket,
                    key=key,
                    expires=ttl,
                )
            )

        return cast("str", await self._dispatch(_presign, operation="presign"))

    async def prepare_upload(
        self, *, key: str, mime_type: str, size_bytes: int
    ) -> tuple[str, dict[str, str], str]:
        """Sign one restricted POST and GET; IRSA may first exchange a rotated OIDC token."""

        def _prepare() -> tuple[str, dict[str, str], str]:
            if self._credentials_provider is None:
                return _sign(self._client, self._security_token)
            credentials = self._credentials_provider.get_credentials()
            # Freeze one triplet for policy, form token and GET across credential rotation.
            client = tos.TosClientV2(
                ak=credentials.get_ak(),
                sk=credentials.get_sk(),
                security_token=credentials.get_security_token(),
                endpoint=self._endpoint,
                region=self._region,
            )
            try:
                return _sign(client, credentials.get_security_token())
            finally:
                client.close()

        def _sign(client: Any, security_token: str | None) -> tuple[str, dict[str, str], str]:
            fields = {
                "key": key,
                "Content-Type": mime_type,
                "x-tos-acl": "private",
                "x-tos-storage-class": "STANDARD",
                "x-tos-forbid-overwrite": "true",
                "x-tos-object-expires": str(TEMPORARY_OBJECT_EXPIRES_DAYS),
            }
            signature = client.pre_signed_post_signature(
                bucket=self._bucket,
                key=key,
                expires=TEMPORARY_UPLOAD_TTL_SECONDS,
                conditions=[
                    PostSignatureCondition(key=name, value=value)
                    for name, value in fields.items()
                    if name != "key"
                ],
                content_length_range=ContentLengthRange(size_bytes, size_bytes),
            )
            fields.update(
                {
                    "policy": signature.policy,
                    "x-tos-algorithm": signature.algorithm,
                    "x-tos-credential": signature.credential,
                    "x-tos-date": signature.date,
                    "x-tos-signature": signature.signature,
                }
            )
            if security_token:
                fields["x-tos-security-token"] = security_token
            reference = client.pre_signed_url(
                HttpMethodType.Http_Method_Get,
                bucket=self._bucket,
                key=key,
                expires=TEMPORARY_REFERENCE_TTL_SECONDS,
            )
            return self._upload_origin, fields, str(reference.signed_url)

        return cast(
            "tuple[str, dict[str, str], str]",
            await self._dispatch(_prepare, operation="prepare_upload"),
        )

    async def close(self) -> None:
        close = getattr(self._client, "close", None)
        try:
            await self._calls.close(close if callable(close) else None, provider=PROVIDER)
        finally:
            self._client = None

    async def _dispatch(self, func: Any, *, operation: str) -> Any:
        from ark_mcp.providers.tos.credentials import IrsaCredentialError

        try:
            return await self._calls.run(
                func, side_effect=operation not in {"presign", "prepare_upload"}
            )
        except IrsaCredentialError:
            raise ProviderError(
                NormalizedProviderError(
                    provider=PROVIDER,
                    operation=operation,
                    code="TOS_IRSA_CREDENTIALS_UNAVAILABLE",
                    message="Could not obtain valid TOS IRSA credentials.",
                    retryable=True,
                )
            ) from None
        except TosServerError as exc:
            raise _normalize_server_error(exc, operation) from None
        except TosClientError as exc:
            raise _normalize_client_error(exc, operation) from None
        except Exception as exc:
            raise _normalize_unknown_error(exc, operation) from None


def _normalize_server_error(exc: TosServerError, operation: str) -> ProviderError:
    status = getattr(exc, "status_code", None) or 0
    code = getattr(exc, "code", None) or "TOS_SERVER_ERROR"
    message = getattr(exc, "message", None) or str(exc)
    request_id = getattr(exc, "request_id", None)
    retryable = status >= 500 or status == 429
    return ProviderError(
        NormalizedProviderError(
            provider=PROVIDER,
            operation=operation,
            http_status=status or None,
            code=code,
            message=f"TOS {operation} failed: {message}",
            request_id=request_id,
            retryable=retryable,
        )
    )


def _normalize_client_error(exc: TosClientError, operation: str) -> ProviderError:
    message = getattr(exc, "message", None) or str(exc)
    return ProviderError(
        NormalizedProviderError(
            provider=PROVIDER,
            operation=operation,
            http_status=None,
            code="TOS_CLIENT_ERROR",
            message=f"TOS {operation} client error: {message}",
            request_id=None,
            retryable=True,
        )
    )


def _normalize_unknown_error(exc: Exception, operation: str) -> ProviderError:
    return ProviderError(
        NormalizedProviderError(
            provider=PROVIDER,
            operation=operation,
            http_status=None,
            code="TOS_UNKNOWN_ERROR",
            message=f"TOS {operation} failed with unexpected error: {exc}",
            request_id=None,
            retryable=True,
        )
    )
