"""Atomic enforcement for a provider's daily request allowance."""

from __future__ import annotations

from datetime import date
from typing import cast
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from prem_engine_api.domain.models import ProviderRequestBudget


class RequestBudgetExhaustedError(RuntimeError):
    """Raised before a provider call would exceed the operational allowance."""


async def reserve_request_slot(
    session: AsyncSession,
    *,
    provider: str,
    budget_date: date,
    operational_limit: int = 85,
    hard_limit: int = 100,
) -> UUID:
    """Atomically reserve one request while retaining a fifteen-request safety margin."""

    initial_insert = insert(ProviderRequestBudget).values(
        provider=provider,
        budget_date=budget_date,
        request_count=1,
        operational_limit=operational_limit,
        hard_limit=hard_limit,
    )
    reservation = initial_insert.on_conflict_do_update(
        index_elements=[ProviderRequestBudget.provider, ProviderRequestBudget.budget_date],
        set_={"request_count": ProviderRequestBudget.request_count + 1},
        where=ProviderRequestBudget.request_count < ProviderRequestBudget.operational_limit,
    ).returning(ProviderRequestBudget.budget_uuid)
    budget_uuid = cast(UUID | None, await session.scalar(reservation))
    if budget_uuid is None:
        raise RequestBudgetExhaustedError(
            f"{provider} operational request limit reached for {budget_date.isoformat()}"
        )
    return budget_uuid
