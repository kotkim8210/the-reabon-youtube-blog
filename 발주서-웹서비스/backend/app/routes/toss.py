"""Toss Shopping API routes — 주문관리 대시보드."""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import verify_token
from app.toss.client import toss_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/toss", tags=["toss"])

KST = timezone(timedelta(hours=9))


class ClaimActionRequest(BaseModel):
    order_product_id: int
    reason: str = ""


# ── Connection Test ──────────────────────────────────────────────


@router.get("/connection-test")
async def connection_test(_token: dict = Depends(verify_token)):
    """Verify Toss API credentials."""
    result = await toss_client.test_connection()
    return result


@router.get("/debug-orders")
async def debug_orders(_token: dict = Depends(verify_token)):
    """Debug: show raw Toss API response structure."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(KST)
    start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")

    try:
        await toss_client._ensure_token()
        client = await toss_client._get_client()
        response = await client.request(
            method="GET",
            url="https://shopping-fep.toss.im/api/v3/shopping-fep/orders/v2",
            headers={
                "Authorization": f"Bearer {toss_client._token}",
                "Content-Type": "application/json",
            },
            params={"startDate": start, "endDate": end, "limit": 5},
        )
        raw = response.json()
        return {
            "status_code": response.status_code,
            "response_keys": list(raw.keys()) if isinstance(raw, dict) else "not_dict",
            "raw_response_preview": str(raw)[:2000],
        }
    except Exception as e:
        return {"error": str(e)}


# ── Orders ───────────────────────────────────────────────────────


@router.get("/orders")
async def list_orders(
    start_date: str | None = None,
    end_date: str | None = None,
    order_status: str | None = None,
    _token: dict = Depends(verify_token),
):
    """List Toss orders with optional date range and status filter."""
    now = datetime.now(KST)
    if not end_date:
        end_date = now.strftime("%Y-%m-%d")
    if not start_date:
        start_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")

    try:
        orders = await toss_client.get_orders(
            start_date=start_date,
            end_date=end_date,
            status=order_status,
        )
        logger.info(
            f"토스 주문 조회 결과: {len(orders)}건 "
            f"(기간: {start_date}~{end_date}, 상태: {order_status})"
        )
        return {"orders": orders, "total": len(orders)}
    except Exception as e:
        logger.exception("토스 주문 조회 실패")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"토스 API 오류: {e}",
        )


# ── Claims (취소/교환/반품) ──────────────────────────────────────


@router.get("/claims")
async def list_claims(
    start_date: str | None = None,
    end_date: str | None = None,
    claim_type: str | None = None,
    _token: dict = Depends(verify_token),
):
    """List claims. claim_type: CANCEL, EXCHANGE, RETURN or omit for all."""
    now = datetime.now(KST)
    if not end_date:
        end_date = now.strftime("%Y-%m-%d")
    if not start_date:
        start_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")

    try:
        claims = await toss_client.get_claims(
            start_date=start_date,
            end_date=end_date,
            claim_type=claim_type,
        )
        return {"claims": claims, "total": len(claims)}
    except Exception as e:
        logger.exception("토스 클레임 조회 실패")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"토스 API 오류: {e}",
        )


# ── Cancel ───────────────────────────────────────────────────────


@router.post("/cancel/approve")
async def approve_cancel(
    req: ClaimActionRequest,
    _token: dict = Depends(verify_token),
):
    """Approve a cancellation request."""
    try:
        result = await toss_client.approve_cancel(req.order_product_id)
        return {"status": "ok", "result": result}
    except Exception as e:
        logger.exception("취소 승인 실패")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"취소 승인 실패: {e}",
        )


@router.post("/cancel/reject")
async def reject_cancel(
    req: ClaimActionRequest,
    _token: dict = Depends(verify_token),
):
    """Reject a cancellation request."""
    if not req.reason:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="거부 사유를 입력해주세요.",
        )
    try:
        result = await toss_client.reject_cancel(req.order_product_id, req.reason)
        return {"status": "ok", "result": result}
    except Exception as e:
        logger.exception("취소 거부 실패")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"취소 거부 실패: {e}",
        )


# ── Exchange ─────────────────────────────────────────────────────


@router.post("/exchange/approve")
async def approve_exchange(
    req: ClaimActionRequest,
    _token: dict = Depends(verify_token),
):
    """Approve an exchange request."""
    try:
        result = await toss_client.approve_exchange(req.order_product_id)
        return {"status": "ok", "result": result}
    except Exception as e:
        logger.exception("교환 승인 실패")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"교환 승인 실패: {e}",
        )


@router.post("/exchange/reject")
async def reject_exchange(
    req: ClaimActionRequest,
    _token: dict = Depends(verify_token),
):
    """Reject an exchange request."""
    if not req.reason:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="거부 사유를 입력해주세요.",
        )
    try:
        result = await toss_client.reject_exchange(req.order_product_id, req.reason)
        return {"status": "ok", "result": result}
    except Exception as e:
        logger.exception("교환 거부 실패")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"교환 거부 실패: {e}",
        )


# ── Return ───────────────────────────────────────────────────────


@router.post("/return/approve")
async def approve_return(
    req: ClaimActionRequest,
    _token: dict = Depends(verify_token),
):
    """Approve a return request."""
    try:
        result = await toss_client.approve_return(req.order_product_id)
        return {"status": "ok", "result": result}
    except Exception as e:
        logger.exception("반품 승인 실패")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"반품 승인 실패: {e}",
        )


@router.post("/return/reject")
async def reject_return(
    req: ClaimActionRequest,
    _token: dict = Depends(verify_token),
):
    """Reject a return request."""
    if not req.reason:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="거부 사유를 입력해주세요.",
        )
    try:
        result = await toss_client.reject_return(req.order_product_id, req.reason)
        return {"status": "ok", "result": result}
    except Exception as e:
        logger.exception("반품 거부 실패")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"반품 거부 실패: {e}",
        )
