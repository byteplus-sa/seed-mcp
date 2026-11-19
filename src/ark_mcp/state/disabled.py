"""No local artifacts or object-store state in forward-only HTTP deployments."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from ark_mcp.artifacts.store import ArtifactLocation, StoredArtifact
    from ark_mcp.domain.artifacts import ArtifactRef, MediaType
    from ark_mcp.security.auth_context import AuthContext


def _disabled() -> PermissionError:
    return PermissionError("Local persistence is unavailable over HTTP.")


class DisabledArtifactStore:
    async def put_base64(
        self,
        data: str,
        media_type: MediaType,
        mime_type: str,
        source_expires_at: str | None = None,
        auth: AuthContext | None = None,
    ) -> ArtifactRef:
        raise _disabled()

    async def copy_from_trusted_url(
        self,
        url: str,
        media_type: MediaType,
        mime_type: str,
        source_expires_at: str | None = None,
        auth: AuthContext | None = None,
    ) -> ArtifactRef:
        raise _disabled()

    async def get(self, artifact_id: str, auth: AuthContext | None = None) -> StoredArtifact:
        raise _disabled()

    async def locate(self, artifact_id: str, auth: AuthContext | None = None) -> ArtifactLocation:
        raise _disabled()

    async def delete_expired(self, now: datetime) -> int:
        return 0

    async def close(self) -> None:
        pass


class DisabledObjectKeyOwnershipStore:
    async def record(self, object_key: str, owner: AuthContext) -> None:
        raise _disabled()

    async def require_owner(self, object_key: str, owner: AuthContext) -> None:
        raise _disabled()

    async def prune(self, max_age_days: int) -> int:
        return 0

    async def ping(self) -> None:
        raise _disabled()

    async def close(self) -> None:
        pass


class DisabledTaskArtifactCache:
    async def get(self, provider: str, task_id: str) -> dict[str, ArtifactRef | None] | None:
        raise _disabled()

    async def set(
        self, provider: str, task_id: str, artifacts: dict[str, ArtifactRef | None]
    ) -> None:
        raise _disabled()

    async def pop(self, provider: str, task_id: str) -> dict[str, ArtifactRef | None] | None:
        raise _disabled()

    async def prune_expired(self) -> int:
        return 0

    async def clear(self) -> None:
        raise _disabled()

    async def close(self) -> None:
        pass
