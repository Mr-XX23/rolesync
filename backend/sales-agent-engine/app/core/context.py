"""Who is acting, for which tenant, in which run.

``AgentContext`` is built server-side only: from a verified access token plus a
workspace-membership check (interactive), or from the persisted session/goal row
(resume, autonomous wake). It is never assembled from tool arguments or model
output, and it is passed to the graph as runtime context rather than stored in
checkpointed state.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class RunMode(StrEnum):
    INTERACTIVE = "INTERACTIVE"
    AUTONOMOUS = "AUTONOMOUS"


@dataclass(frozen=True, slots=True)
class Principal:
    """A verified caller (auth-service ``userId`` claim)."""

    user_id: UUID
    email: str | None = None


@dataclass(frozen=True, slots=True)
class TenantContext:
    """A verified caller acting inside a workspace they belong to."""

    tenant_id: UUID
    principal: Principal

    @property
    def user_id(self) -> UUID:
        return self.principal.user_id


@dataclass(frozen=True, slots=True)
class AgentContext:
    tenant_id: UUID
    user_id: UUID
    session_id: UUID
    mode: RunMode
    goal_id: UUID | None = None
