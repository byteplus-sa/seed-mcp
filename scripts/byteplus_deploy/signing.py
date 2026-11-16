"""Pure BytePlus OpenAPI V4 signing for infrastructure and secret-manager calls."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import quote

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True, slots=True)
class OpenApiCredentials:
    """Infrastructure AK/SK with an optional STS session token."""

    access_key_id: str
    secret_access_key: str
    session_token: str = ""

    def __repr__(self) -> str:
        return "OpenApiCredentials(***)"


def sha256_hex(payload: bytes) -> str:
    """Return the lowercase hex SHA-256 digest of the payload."""
    return hashlib.sha256(payload).hexdigest()


def canonical_query_string(query: dict[str, str]) -> str:
    """Sort and percent-encode query parameters according to RFC 3986."""
    return "&".join(
        f"{quote(key, safe='-_.~')}={quote(value, safe='-_.~')}"
        for key, value in sorted(query.items())
    )


def signing_key(secret_access_key: str, short_date: str, region: str, service: str) -> bytes:
    """Derive the signing key from the credential scope."""
    key = secret_access_key.encode("utf-8")
    for part in (short_date, region, service, "request"):
        key = hmac.new(key, part.encode("utf-8"), hashlib.sha256).digest()
    return key


def sign_request(
    *,
    credentials: OpenApiCredentials,
    method: str,
    host: str,
    query: dict[str, str],
    payload: bytes,
    region: str,
    service: str,
    now: datetime,
    content_type: str = "application/json",
) -> dict[str, str]:
    """Authenticate one request using an explicit timezone-aware UTC timestamp."""
    request_date = now.strftime("%Y%m%dT%H%M%SZ")
    short_date = now.strftime("%Y%m%d")
    content_sha256 = sha256_hex(payload)
    header_values = {
        "host": host,
        "x-content-sha256": content_sha256,
        "x-date": request_date,
    }
    if method.upper() != "GET":
        header_values["content-type"] = content_type
    if credentials.session_token:
        header_values["x-security-token"] = credentials.session_token

    names = sorted(header_values)
    canonical_headers = "".join(f"{name}:{header_values[name].strip()}\n" for name in names)
    signed_headers = ";".join(names)
    canonical_request = "\n".join(
        (
            method.upper(),
            "/",
            canonical_query_string(query),
            canonical_headers,
            signed_headers,
            content_sha256,
        )
    )
    scope = f"{short_date}/{region}/{service}/request"
    string_to_sign = "\n".join(
        ("HMAC-SHA256", request_date, scope, sha256_hex(canonical_request.encode("utf-8")))
    )
    signature = hmac.new(
        signing_key(credentials.secret_access_key, short_date, region, service),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    headers = {
        "Host": host,
        "X-Date": request_date,
        "X-Content-Sha256": content_sha256,
        "Authorization": (
            f"HMAC-SHA256 Credential={credentials.access_key_id}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        ),
    }
    if "content-type" in header_values:
        headers["Content-Type"] = content_type
    if credentials.session_token:
        headers["X-Security-Token"] = credentials.session_token
    return headers
