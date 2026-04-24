"""Plan quota enforcement for SaaS deployment."""

import logging
from datetime import datetime

from fastapi import HTTPException

from app.config import DISABLE_QUOTA
from app.db import (
    get_subscription, get_plan, get_monthly_usage,
    get_user_products, get_user_by_id, log_usage,
)

logger = logging.getLogger(__name__)


async def _resolve_plan(user_id: int) -> dict:
    """Return plan dict for user. Admins get unlimited. Missing sub → free."""
    user = await get_user_by_id(user_id)
    if user and user.get("role") == "admin":
        return {
            "code": "admin",
            "max_products": None,
            "max_monthly_orders": None,
            "features_json": '{"tracking": true, "coupang_api": true, "pricing": true, "sales_history_days": null}',
        }
    sub = await get_subscription(user_id)
    plan_code = sub["plan_code"] if sub else "free"
    plan = await get_plan(plan_code)
    if not plan:
        plan = await get_plan("free")
    return plan or {"code": "free", "max_products": 1, "max_monthly_orders": 50, "features_json": "{}"}


async def check_product_limit(user_id: int) -> None:
    """Raise if user already at max_products (for CREATE)."""
    if DISABLE_QUOTA:
        return
    plan = await _resolve_plan(user_id)
    max_products = plan.get("max_products")
    if max_products is None:
        return
    products = await get_user_products(user_id)
    if len(products) >= max_products:
        raise HTTPException(
            status_code=402,
            detail=f"현재 플랜({plan['code']})은 최대 {max_products}개 제품까지 등록 가능합니다. Pro로 업그레이드하세요.",
        )


async def check_order_quota(user_id: int, incoming_orders: int) -> None:
    """Raise if processing `incoming_orders` would exceed monthly limit."""
    if DISABLE_QUOTA:
        return
    if incoming_orders <= 0:
        return
    plan = await _resolve_plan(user_id)
    max_orders = plan.get("max_monthly_orders")
    if max_orders is None:
        return
    usage = await get_monthly_usage(user_id)
    if usage["order_count"] + incoming_orders > max_orders:
        remaining = max(0, max_orders - usage["order_count"])
        raise HTTPException(
            status_code=402,
            detail=f"월 사용량 한도 초과 (남은 사용량: {remaining}/{max_orders}건). Pro 플랜으로 업그레이드하세요.",
        )


async def record_order_usage(user_id: int, product_label: str, order_count: int) -> None:
    """Log usage event. Separate from quota check so callers can decide order."""
    if order_count <= 0:
        return
    await log_usage(user_id, "order_generated", product_label, order_count)


async def feature_enabled(user_id: int, feature_key: str) -> bool:
    """Check if a plan feature flag is on (tracking, coupang_api, pricing)."""
    if DISABLE_QUOTA:
        return True
    import json
    plan = await _resolve_plan(user_id)
    try:
        flags = json.loads(plan.get("features_json") or "{}")
    except (ValueError, TypeError):
        flags = {}
    return bool(flags.get(feature_key, False))


async def require_feature(user_id: int, feature_key: str) -> None:
    if not await feature_enabled(user_id, feature_key):
        raise HTTPException(
            status_code=403,
            detail=f"'{feature_key}' 기능은 Pro 플랜 전용입니다.",
        )
