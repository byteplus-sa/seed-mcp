"""Unit tests for principal/auth context locality rules."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ark_mcp.security.auth_context import PrincipalContext


class TestPrincipalContextIsLocal:
    def test_local_principal_over_stdio_is_local(self) -> None:
        assert PrincipalContext(principal_id="local", transport="stdio").is_local is True

    def test_local_principal_over_http_is_not_local(self) -> None:
        assert PrincipalContext(principal_id="local", transport="http").is_local is False

    def test_spoofed_remote_principal_is_not_local(self) -> None:
        spoofed = PrincipalContext(
            principal_id="local",
            tenant_id="tenant-a",
            transport="http",
            scopes=frozenset({"gen:read"}),
        )
        assert spoofed.is_local is False

    @pytest.mark.parametrize(
        "field,value",
        [("principal_id", "other"), ("tenant_id", "other"), ("transport", "stdio")],
    )
    def test_http_ownership_identity_is_immutable(self, field: str, value: str) -> None:
        principal = PrincipalContext(
            principal_id="owner-a", tenant_id="credential-a", transport="http"
        )
        with pytest.raises(ValidationError, match="frozen"):
            setattr(principal, field, value)
        assert principal.principal_id == "owner-a"
        assert principal.tenant_id == "credential-a"
        assert not principal.is_local
