"""Explicit VKE OIDC exchange; no metadata, environment chain or AK/SK fallback.

See specs/SPEC_VKE_DEPLOYMENT.md. Credentials remain in the owning runtime's
memory. The synchronous provider is called only from a drained SDK worker.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import httpx
from tos.credential import Credentials

if TYPE_CHECKING:
    from ark_mcp.config.env import Settings


class IrsaCredentialError(RuntimeError):
    """Sanitized exchange failure with no upstream body, token or credential echo."""


@dataclass(frozen=True)
class _Snapshot:
    credentials: Any = field(repr=False)
    expires_at: float


class IrsaCredentialsProvider:
    """Lazy, thread-safe credential refresh for one server lifespan."""

    def __init__(self, settings: Settings) -> None:
        self._role = settings.tos_irsa_role_trn
        self._token_file = Path(settings.tos_irsa_token_file)
        self._endpoint = settings.tos_irsa_sts_endpoint
        self._duration = settings.tos_irsa_duration_seconds
        self._session = f"seed-mcp-{uuid4().hex}"
        self._snapshot: _Snapshot | None = None
        self._retry_at = 0.0
        self._lock = threading.Lock()
        self._closed = False

    def get_credentials(self) -> Any:
        """Refresh five minutes early; never serve the last sixty seconds."""
        with self._lock:
            if self._closed:
                raise IrsaCredentialError("TOS IRSA credentials are closed.")
            now = time.time()
            cached = self._snapshot
            if cached is not None and now < cached.expires_at - 300:
                return cached.credentials
            if time.monotonic() >= self._retry_at:
                try:
                    self._snapshot = self._exchange()
                    self._retry_at = 0.0
                    return self._snapshot.credentials
                except Exception:
                    # Backoff limits failed refreshes across concurrent enrolled callers.
                    self._retry_at = time.monotonic() + 10
            if cached is not None and time.time() < cached.expires_at - 60:
                return cached.credentials
            raise IrsaCredentialError("Could not obtain valid TOS IRSA credentials.") from None

    def close(self) -> None:
        """Drop credentials once the lifespan has drained active signing calls."""
        with self._lock:
            self._snapshot = None
            self._closed = True

    def _exchange(self) -> _Snapshot:
        with self._token_file.open(encoding="ascii") as token_file:
            token = token_file.read(65537).strip()
        if not token or len(token) > 65536 or any(not 33 <= ord(c) <= 126 for c in token):
            raise IrsaCredentialError("Invalid projected OIDC token.")
        # No ambient proxy, redirect, retry, metadata request or request/body logging.
        with (
            httpx.Client(
                timeout=httpx.Timeout(10, connect=5), trust_env=False, follow_redirects=False
            ) as client,
            client.stream(
                "POST",
                self._endpoint + "/",
                params={"Action": "AssumeRoleWithOIDC", "Version": "2018-01-01"},
                data={
                    "RoleTrn": self._role,
                    "OIDCToken": token,
                    "RoleSessionName": self._session,
                    "DurationSeconds": str(self._duration),
                },
            ) as response,
        ):
            if not 200 <= response.status_code < 300:
                raise IrsaCredentialError("TOS IRSA exchange was rejected.")
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > 65536:
                    raise IrsaCredentialError("Invalid TOS IRSA response.")
            import json

            data = json.loads(body)
        if not isinstance(data, dict):
            raise IrsaCredentialError("Invalid TOS IRSA response.")
        metadata = data.get("ResponseMetadata", {})
        if not isinstance(metadata, dict) or metadata.get("Error"):
            raise IrsaCredentialError("TOS IRSA exchange was rejected.")
        result = data.get("Result")
        values = result.get("Credentials") if isinstance(result, dict) else None
        if not isinstance(values, dict):
            raise IrsaCredentialError("Invalid TOS IRSA response.")
        ak, sk, session_token = (
            values.get("AccessKeyId"),
            values.get("SecretAccessKey"),
            values.get("SessionToken"),
        )
        expiry = values.get("ExpiredTime") or values.get("Expiration")
        if not all(
            isinstance(value, str)
            and 0 < len(value) <= 32768
            and all(33 <= ord(c) <= 126 for c in value)
            for value in (ak, sk, session_token)
        ) or not isinstance(expiry, str):
            raise IrsaCredentialError("Invalid TOS IRSA response.")
        moment = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
        if moment.tzinfo is None or moment.astimezone(UTC).timestamp() <= time.time() + 60:
            raise IrsaCredentialError("TOS IRSA credentials are expired or too near expiry.")
        return _Snapshot(Credentials(ak, sk, session_token), moment.timestamp())
