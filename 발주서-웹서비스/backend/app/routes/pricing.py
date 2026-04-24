"""Pricing management API routes."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional

from app.auth import verify_token
from app import db
from app.coupang.pricing import generate_proposals, get_all_margins

router = APIRouter(prefix="/api/pricing", tags=["pricing"])


class PricingRuleInput(BaseModel):
    product_id: int
    product_name: str = ""
    min_margin_pct: float = 3.0
    min_price: int = 0
    max_price: int = 0
    ad_stop_threshold: float = 1.0


@router.get("/rules")
async def list_rules(_token: dict = Depends(verify_token)):
    """Get all active pricing rules."""
    rules = await db.get_pricing_rules()
    return {"rules": rules}


@router.post("/rules")
async def create_rule(rule: PricingRuleInput, _token: dict = Depends(verify_token)):
    """Create or update a pricing rule."""
    await db.upsert_pricing_rule(rule.model_dump())
    return {"status": "ok", "message": f"상품 {rule.product_id} 가격 룰 저장됨"}


@router.delete("/rules/{product_id}")
async def remove_rule(product_id: int, _token: dict = Depends(verify_token)):
    """Deactivate a pricing rule."""
    await db.delete_pricing_rule(product_id)
    return {"status": "ok", "message": f"상품 {product_id} 가격 룰 비활성화됨"}


@router.get("/proposals")
async def list_proposals(_token: dict = Depends(verify_token)):
    """Get current price change proposals (dry-run)."""
    proposals = await generate_proposals()
    return {"proposals": proposals}


@router.get("/margins")
async def list_margins(_token: dict = Depends(verify_token)):
    """Get margin status for all products."""
    margins = await get_all_margins()
    return {"margins": margins}


@router.get("/log")
async def get_log(_token: dict = Depends(verify_token)):
    """Get price change audit log."""
    logs = await db.get_pricing_logs(limit=50)
    return {"logs": logs}
