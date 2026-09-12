"""What the agent remembers, for the rep to review and delete (decided for this build: memories
are saved automatically and are reviewable).

- ``/memory/rep``: what it learned about the caller; private to them
- ``/memory/accounts``, ``/memory/account?company=``, ``/memory/deals/{id}``: customer knowledge
  shared by the workspace; any member can read it, and every member except viewers can delete from it
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Path, Query
from pydantic import BaseModel

from app.api.deps import ContainerDep, TenantDep
from app.context.locks import MemoryBusy
from app.context.stores import MemoryRecord, account_key, facts_of, remove_fact
from app.core.context import TenantContext
from app.core.enums import MemoryScope
from app.core.errors import BadRequest, Conflict, NotFound, TenantAccessDenied
from app.container import Container

router = APIRouter(tags=["memory"])

AccountKey = Annotated[str, Path(min_length=1, max_length=120, pattern=r"^[^/\s]+$")]
FactId = Annotated[str, Path(pattern=r"^f_[0-9a-f]{12}$")]


class FactView(BaseModel):
    id: str
    text: str
    saved_at: str | None
    saved_by_me: bool


class MemoryView(BaseModel):
    about: str  # rep | account | deal
    key: str
    name: str | None
    facts: list[FactView]  # newest first
    version: int
    updated_at: datetime | None


class AccountSummary(BaseModel):
    key: str
    name: str
    facts: int
    updated_at: datetime | None


@router.get("/memory/rep", response_model=MemoryView)
async def rep_memory(tenant: TenantDep, container: ContainerDep) -> MemoryView:
    record = await container.memory.latest(tenant_id=tenant.tenant_id, scope=MemoryScope.REP, key=str(tenant.user_id))
    return _view("rep", "me", record, tenant)


@router.get("/memory/accounts", response_model=list[AccountSummary])
async def list_accounts(
    tenant: TenantDep, container: ContainerDep, q: Annotated[str | None, Query(max_length=200)] = None
) -> list[AccountSummary]:
    needle = (q or "").strip().lower()
    records = await container.memory.list_latest(tenant_id=tenant.tenant_id, scope=MemoryScope.ACCOUNT)
    return [
        AccountSummary(key=record.key, name=str(record.content.get("name") or record.key), facts=len(facts_of(record.content)), updated_at=record.updated_at)
        for record in records
        if facts_of(record.content) and (not needle or needle in f"{record.content.get('name', '')} {record.key}".lower())
    ]


@router.get("/memory/account", response_model=MemoryView)
async def account_memory(
    tenant: TenantDep, container: ContainerDep, company: Annotated[str, Query(min_length=1, max_length=200)]
) -> MemoryView:
    """A customer's memory by its name as written anywhere (on a deal, say) or by its key from the list."""
    try:
        key = account_key(company)
    except ValueError as exc:
        raise BadRequest(str(exc)) from exc
    record = await container.memory.latest(tenant_id=tenant.tenant_id, scope=MemoryScope.ACCOUNT, key=key)
    if record is None and key != company:
        # A listed key whose company name was long enough for the key to be cut short.
        exact = await container.memory.latest(tenant_id=tenant.tenant_id, scope=MemoryScope.ACCOUNT, key=company)
        if exact is not None:
            key, record = company, exact
    return _view("account", key, record, tenant)


@router.get("/memory/deals/{deal_id}", response_model=MemoryView)
async def deal_memory(deal_id: UUID, tenant: TenantDep, container: ContainerDep) -> MemoryView:
    record = await container.memory.latest(tenant_id=tenant.tenant_id, scope=MemoryScope.DEAL, key=str(deal_id))
    return _view("deal", str(deal_id), record, tenant)


@router.delete("/memory/rep/facts/{fact_id}", response_model=MemoryView)
async def forget_rep_fact(fact_id: FactId, tenant: TenantDep, container: ContainerDep) -> MemoryView:
    record = await _forget(container, tenant, MemoryScope.REP, str(tenant.user_id), fact_id)
    return _view("rep", "me", record, tenant)


@router.delete("/memory/accounts/{key}/facts/{fact_id}", response_model=MemoryView)
async def forget_account_fact(key: AccountKey, fact_id: FactId, tenant: TenantDep, container: ContainerDep) -> MemoryView:
    await _require_writer(container, tenant)
    record = await _forget(container, tenant, MemoryScope.ACCOUNT, key, fact_id)
    return _view("account", key, record, tenant)


@router.delete("/memory/deals/{deal_id}/facts/{fact_id}", response_model=MemoryView)
async def forget_deal_fact(deal_id: UUID, fact_id: FactId, tenant: TenantDep, container: ContainerDep) -> MemoryView:
    await _require_writer(container, tenant)
    record = await _forget(container, tenant, MemoryScope.DEAL, str(deal_id), fact_id)
    return _view("deal", str(deal_id), record, tenant)


async def _require_writer(container: Container, tenant: TenantContext) -> None:
    if await container.workspaces.role_in(tenant.user_id, tenant.tenant_id) == "VIEWER":
        raise TenantAccessDenied("viewers can't change the workspace's shared memory")


async def _forget(container: Container, tenant: TenantContext, scope: MemoryScope, key: str, fact_id: str) -> MemoryRecord:
    found: dict[str, bool] = {}

    def mutate(content: dict[str, Any]) -> dict[str, Any] | None:
        updated = remove_fact(content, fact_id)
        found["fact"] = updated is not None
        return updated

    try:
        record = await container.memory.update(
            tenant_id=tenant.tenant_id, scope=scope, key=key, mutate=mutate, written_by=tenant.user_id
        )
    except MemoryBusy as exc:
        raise Conflict(str(exc)) from exc
    if not found.get("fact") or record is None:
        raise NotFound("that memory no longer exists")
    return record


def _view(about: str, key: str, record: MemoryRecord | None, tenant: TenantContext) -> MemoryView:
    facts = facts_of(record.content if record else None)
    return MemoryView(
        about=about,
        key=key,
        name=str(record.content.get("name")) if record and record.content.get("name") else None,
        facts=[
            FactView(
                id=str(fact["id"]),
                text=str(fact.get("text") or ""),
                saved_at=fact.get("saved_at"),
                saved_by_me=fact.get("saved_by") == str(tenant.user_id),
            )
            for fact in reversed(facts)
        ],
        version=record.version if record else 0,
        updated_at=record.updated_at if record else None,
    )
