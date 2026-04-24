"""Risk score calculation engine - Traffic Light Algorithm."""

import logging
from app import db

logger = logging.getLogger(__name__)

# Weights
W_INVENTORY = 0.6
W_MARGIN = 0.4

# Thresholds
DAYS_CRITICAL = 3
DAYS_WARNING = 7
MARGIN_CRITICAL = 3.0
MARGIN_WARNING = 10.0


async def calculate_risk_score(product: dict) -> dict:
    """Calculate risk score for a single product.

    Returns dict with: score, level, labels, days_remaining, etc.
    """
    product_id = product["seller_product_id"]
    stock = product.get("stock", 0)
    sale_price = product.get("sale_price", 0)

    # Get average daily sales
    avg_daily_sales = await db.get_daily_sales_avg(product_id, days=7)

    # Calculate days remaining
    if avg_daily_sales > 0:
        days_remaining = stock / avg_daily_sales
    else:
        days_remaining = 999.0 if stock > 0 else 0.0

    # Inventory score component (0-100, higher = safer)
    if days_remaining <= 0:
        inventory_score = 0
    elif days_remaining < DAYS_CRITICAL:
        inventory_score = 10
    elif days_remaining < DAYS_WARNING:
        inventory_score = 40
    elif days_remaining < 14:
        inventory_score = 70
    else:
        inventory_score = 100

    # Margin score component (simplified - will be enhanced with cost data)
    # For now, use a placeholder margin based on category averages
    # In production, this would come from settlement data
    margin_pct = 15.0  # Default assumption until we have real cost data
    if margin_pct <= 1.0:
        margin_score = 0
    elif margin_pct < MARGIN_CRITICAL:
        margin_score = 20
    elif margin_pct < MARGIN_WARNING:
        margin_score = 50
    else:
        margin_score = 100

    # Composite score
    score = inventory_score * W_INVENTORY + margin_score * W_MARGIN

    # Determine level
    if score < 40:
        level = "red"
    elif score < 70:
        level = "yellow"
    else:
        level = "green"

    # Generate labels
    labels = []
    if days_remaining < DAYS_CRITICAL:
        labels.append(f"재고 {stock}개 — {days_remaining:.0f}일 내 품절 예상")
    elif days_remaining < DAYS_WARNING:
        labels.append(f"재고 {stock}개 — {days_remaining:.0f}일 내 소진 예상")
    else:
        labels.append(f"재고 {stock}개 — 안정적")

    if margin_pct < MARGIN_CRITICAL:
        labels.append(f"마진 {margin_pct:.1f}% — 수익성 위험")
    elif margin_pct < MARGIN_WARNING:
        labels.append(f"마진 {margin_pct:.1f}% — 주의 필요")

    if avg_daily_sales > 0:
        labels.append(f"일평균 {avg_daily_sales:.1f}개 판매")

    return {
        "product_id": product_id,
        "product_name": product.get("product_name", ""),
        "score": round(score, 1),
        "level": level,
        "stock": stock,
        "avg_daily_sales": round(avg_daily_sales, 1),
        "days_remaining": round(days_remaining, 1),
        "margin_pct": round(margin_pct, 1),
        "labels": labels,
    }


async def calculate_all_risk_scores() -> list[dict]:
    """Calculate risk scores for all cached products."""
    products = await db.get_cached_products()
    scores = []
    for p in products:
        # 판매중지/비활성 상품은 리스크 평가 제외
        if p.get("status", "") in ("판매중지", "SUSPEND"):
            continue
        if not p.get("vendor_item_id"):
            continue
        try:
            score = await calculate_risk_score(p)
            scores.append(score)
        except Exception as e:
            logger.error(f"Error calculating risk for product {p.get('seller_product_id')}: {e}")
    # Sort by score ascending (most risky first)
    scores.sort(key=lambda x: x["score"])
    return scores
