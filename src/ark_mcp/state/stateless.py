"""HTTP task authorization is delegated to the selected provider, never a local ledger."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from ark_mcp.runtime import OwnedTask
    from ark_mcp.security.auth_context import AuthContext


class ProviderAuthorizedTasks:
    """No task IDs are retained; these hooks do not assert provider authorization."""

    async def require_capacity(self) -> None:
        pass

    async def record(self, provider: str, task_id: str, owner: AuthContext) -> None:
        pass

    async def require_owner(self, provider: str, task_id: str, owner: AuthContext) -> None:
        # Every tool still requires live BYOK credentials before provider access.
        pass

    async def list_owned_tasks(
        self,
        provider: str,
        owner: AuthContext,
        *,
        since: datetime,
        before: tuple[datetime, str] | None,
        limit: int,
    ) -> list[OwnedTask]:
        raise RuntimeError("Stateless HTTP must list tasks through the provider.")

    async def prune(self, max_age_days: int) -> int:
        return 0

    async def ping(self) -> None:
        pass

    async def close(self) -> None:
        pass
