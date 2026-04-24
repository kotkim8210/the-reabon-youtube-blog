"""Pydantic models for Coupang data and domain objects."""

from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class CoupangProduct(BaseModel):
    seller_product_id: int
    product_name: str
    sale_price: int = 0
    stock: int = 0
    status: str = ""
    vendor_item_id: Optional[int] = None
    category: str = ""
    updated_at: Optional[str] = None


class CoupangOrder(BaseModel):
    order_id: str
    ordered_at: str
    product_name: str
    seller_product_id: int = 0
    quantity: int = 1
    sale_price: int = 0
    status: str = ""
    receiver_name: str = ""


class RiskScore(BaseModel):
    product_id: int
    product_name: str
    score: float
    level: str  # "red", "yellow", "green"
    stock: int = 0
    avg_daily_sales: float = 0.0
    days_remaining: float = 0.0
    margin_pct: float = 0.0
    labels: list[str] = []


class InventoryAlert(BaseModel):
    product_id: int
    product_name: str
    stock: int
    status: str  # "critical", "warning", "ok"
    avg_daily_sales: float = 0.0
    days_remaining: float = 0.0


class PricingRule(BaseModel):
    id: Optional[int] = None
    product_id: int
    product_name: str = ""
    min_margin_pct: float = 3.0
    min_price: int = 0
    max_price: int = 0
    ad_stop_threshold: float = 1.0
    active: bool = True
    created_at: Optional[str] = None


class PriceProposal(BaseModel):
    product_id: int
    product_name: str
    current_price: int
    proposed_price: int
    current_margin_pct: float
    proposed_margin_pct: float
    reason: str
    ad_stop_recommended: bool = False


class PriceChangeLog(BaseModel):
    id: Optional[int] = None
    product_id: int
    product_name: str
    old_price: int
    new_price: int
    margin_before: float
    margin_after: float
    reason: str
    executed_at: Optional[str] = None


class DashboardSummary(BaseModel):
    total_orders_today: int = 0
    total_revenue_today: int = 0
    total_products: int = 0
    critical_alerts: int = 0
    avg_margin_pct: float = 0.0
