"""HTTP route for the workspace's settlement currency.

The unit of figures read from the settlement. It is NOT the unit of everything
a workspace shows: a KGS workspace is priced in RUB, and its campaigns bill in the
currency each was created in (RUB before WB moved the ad account on 2026-08-20),
so monitoring labels its prices and spend from its own data instead. The A/B
summary still reads this for its spend — right for every test so far, all of
them on campaigns created after the move. The unit lives in this module's
settlement rows, so this module answers for it; monitoring cannot, because this
module already depends on monitoring's contract and a dependency back would
close a cycle.

It is mounted beside the P&L routes but **not behind the P&L grant**: a manager
granted only monitoring or A/B tests reads money in this currency on every
screen they can reach, and what comes back is a currency code, not a figure.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from src.modules.finreports.deps import PnlServiceDep
from src.modules.finreports.schemas import SettlementCurrencyResponse
from src.modules.organizations.contract import MemberAccess
from src.modules.workspaces.contract import CurrentWorkspaceId

router = APIRouter()


@router.get(
    "/currency",
    response_model=SettlementCurrencyResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "The active кабинет's settlement currency, or empty."},
        401: {"description": "Unauthorized access token."},
        403: {"description": "Not a member of an organisation with a live subscription."},
    },
)
async def get_settlement_currency(
    _member: MemberAccess,
    service: PnlServiceDep,
    workspace_id: CurrentWorkspaceId,
) -> SettlementCurrencyResponse:
    """Return the currency WB settles the active workspace in.

    Membership, not the P&L grant: monitoring and the A/B tests print money in
    this unit for managers who cannot open the P&L. Nothing weaker either —
    ``MemberAccess`` is the paywall, and a bare account has no workspace to ask
    about.
    """
    return SettlementCurrencyResponse(
        currency=await service.settlement_currency(workspace_id=workspace_id)
    )
