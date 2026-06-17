from fastapi import APIRouter, HTTPException, Query
from typing import Optional

router = APIRouter(prefix="/api/account", tags=["account"])


@router.get("/info")
async def account_info(target: Optional[str] = Query(default="live")):
    try:
        from app.services.account_service import get_account_info
        return get_account_info(target=target)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/positions")
async def account_positions(target: Optional[str] = Query(default="live")):
    try:
        from app.services.account_service import get_positions
        return get_positions(target=target)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/open-orders")
async def account_open_orders(
    target: Optional[str] = Query(default="live"),
    symbol: Optional[str] = Query(default=None),
):
    try:
        from app.services.account_service import get_open_orders
        return get_open_orders(target=target, symbol=symbol)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/trades")
async def account_trades(
    target: Optional[str] = Query(default="live"),
    symbol: Optional[str] = Query(default=None),
    limit: int = Query(default=100),
    startTime: Optional[int] = Query(default=None),
    endTime: Optional[int] = Query(default=None),
):
    try:
        from app.services.account_service import get_trades
        return get_trades(
            target=target,
            symbol=symbol,
            limit=limit,
            start_time=startTime,
            end_time=endTime,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/income")
async def account_income(
    target: Optional[str] = Query(default="live"),
    symbol: Optional[str] = Query(default=None),
    incomeType: Optional[str] = Query(default=None),
    limit: int = Query(default=100),
    startTime: Optional[int] = Query(default=None),
    endTime: Optional[int] = Query(default=None),
):
    try:
        from app.services.account_service import get_income
        return get_income(
            target=target,
            symbol=symbol,
            income_type=incomeType,
            limit=limit,
            start_time=startTime,
            end_time=endTime,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))