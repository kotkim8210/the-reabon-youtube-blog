"""Billing routes: plans, subscription, Toss Payments billing (subscription)."""

import base64
import logging
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.auth import verify_token
from app.config import (
    DISABLE_BILLING, TOSS_PAY_SECRET_KEY, TOSS_PAY_CLIENT_KEY,
    TOSS_PAY_API_BASE, APP_BASE_URL, PRO_PLAN_PRICE,
)
from app.db import (
    list_plans, get_plan, get_subscription, upsert_subscription,
    set_subscription_cancel, get_monthly_usage, add_billing_event,
    get_user_by_id,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/billing", tags=["billing"])
KST = timezone(timedelta(hours=9))


# --- Models ---

class SubscribeRequest(BaseModel):
    auth_key: str
    customer_key: str


class CheckoutConfig(BaseModel):
    client_key: str
    customer_key_prefix: str = "balju"


# --- Toss Payments HTTP helpers ---

def _toss_auth_header() -> dict:
    if not TOSS_PAY_SECRET_KEY:
        raise HTTPException(status_code=500, detail="토스페이먼츠 시크릿 키가 설정되지 않았습니다.")
    encoded = base64.b64encode(f"{TOSS_PAY_SECRET_KEY}:".encode()).decode()
    return {"Authorization": f"Basic {encoded}", "Content-Type": "application/json"}


async def _issue_billing_key(auth_key: str, customer_key: str) -> dict:
    url = f"{TOSS_PAY_API_BASE}/v1/billing/authorizations/issue"
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            url,
            headers=_toss_auth_header(),
            json={"authKey": auth_key, "customerKey": customer_key},
        )
    if resp.status_code >= 400:
        logger.error("Toss billing issue failed: %s %s", resp.status_code, resp.text)
        raise HTTPException(status_code=400, detail=f"빌링키 발급 실패: {resp.text}")
    return resp.json()


async def _charge_billing(billing_key: str, customer_key: str, amount: int,
                           order_id: str, order_name: str) -> dict:
    url = f"{TOSS_PAY_API_BASE}/v1/billing/{billing_key}"
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            url,
            headers=_toss_auth_header(),
            json={
                "customerKey": customer_key,
                "amount": amount,
                "orderId": order_id,
                "orderName": order_name,
            },
        )
    if resp.status_code >= 400:
        logger.error("Toss billing charge failed: %s %s", resp.status_code, resp.text)
        raise HTTPException(status_code=402, detail=f"결제 실패: {resp.text}")
    return resp.json()


# --- Public endpoints ---

@router.get("/plans")
async def get_plans_public():
    plans = await list_plans()
    return {"plans": plans, "billing_enabled": not DISABLE_BILLING}


@router.get("/config")
async def billing_config():
    """Return public client key for Toss widget."""
    return CheckoutConfig(client_key=TOSS_PAY_CLIENT_KEY or "")


# --- Authenticated ---

@router.get("/me")
async def my_subscription(user: dict = Depends(verify_token)):
    sub = await get_subscription(user["user_id"])
    if not sub:
        await upsert_subscription(user["user_id"], "free")
        sub = await get_subscription(user["user_id"])
    plan = await get_plan(sub["plan_code"]) if sub else None
    usage = await get_monthly_usage(user["user_id"])
    return {
        "subscription": {
            "plan_code": sub["plan_code"],
            "status": sub["status"],
            "current_period_end": sub.get("current_period_end"),
            "cancel_at_period_end": bool(sub.get("cancel_at_period_end")),
        },
        "plan": plan,
        "usage": usage,
    }


@router.post("/subscribe")
async def subscribe(req: SubscribeRequest, user: dict = Depends(verify_token)):
    if DISABLE_BILLING:
        raise HTTPException(status_code=403, detail="결제가 비활성화된 배포 환경입니다.")

    # 1) Issue billing key
    issue_resp = await _issue_billing_key(req.auth_key, req.customer_key)
    billing_key = issue_resp.get("billingKey")
    if not billing_key:
        raise HTTPException(status_code=400, detail="빌링키를 받지 못했습니다.")

    # 2) Charge first month immediately
    order_id = f"pro-{user['user_id']}-{uuid.uuid4().hex[:12]}"
    try:
        charge = await _charge_billing(
            billing_key, req.customer_key, PRO_PLAN_PRICE, order_id,
            f"발주서 Pro 구독 (월 {PRO_PLAN_PRICE:,}원)",
        )
    except HTTPException as e:
        await add_billing_event(user["user_id"], "fail", PRO_PLAN_PRICE,
                                raw={"error": e.detail, "order_id": order_id})
        raise

    # 3) Update subscription
    now = datetime.now(KST)
    period_end = now + timedelta(days=30)
    await upsert_subscription(
        user_id=user["user_id"],
        plan_code="pro",
        status="active",
        billing_key=billing_key,
        customer_key=req.customer_key,
        current_period_start=now.isoformat(),
        current_period_end=period_end.isoformat(),
        cancel_at_period_end=0,
    )
    await add_billing_event(
        user["user_id"], "subscribe", PRO_PLAN_PRICE,
        toss_payment_key=charge.get("paymentKey"),
        toss_order_id=order_id,
        raw=charge,
    )
    return {"status": "ok", "plan_code": "pro", "current_period_end": period_end.isoformat()}


@router.post("/cancel")
async def cancel(user: dict = Depends(verify_token)):
    sub = await get_subscription(user["user_id"])
    if not sub or sub["plan_code"] != "pro":
        raise HTTPException(status_code=400, detail="구독 중이 아닙니다.")
    await set_subscription_cancel(user["user_id"], True)
    await add_billing_event(user["user_id"], "cancel_scheduled", 0, raw={})
    return {"status": "ok", "message": "기간 만료 후 해지됩니다."}


@router.post("/resume")
async def resume(user: dict = Depends(verify_token)):
    sub = await get_subscription(user["user_id"])
    if not sub or sub["plan_code"] != "pro":
        raise HTTPException(status_code=400, detail="Pro 구독이 아닙니다.")
    await set_subscription_cancel(user["user_id"], False)
    return {"status": "ok"}


@router.post("/webhook/toss")
async def toss_webhook(request: Request):
    """Toss payment status webhook. Logs only — renewals handled by scheduler."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    logger.info("Toss webhook received: %s", payload)
    return {"status": "received"}
