"""Dynamic Pricing & Ad-Stop monitoring engine.

Phase 1: Monitoring + Alert only (no auto-execution).
"""

import logging
from app import db

logger = logging.getLogger(__name__)

# Safety guards
MAX_PRICE_CHANGE_PCT = 10.0  # Maximum ±10% per adjustment


async def evaluate_product_margin(product: dict, rule: dict | None = None) -> dict:
    """Evaluate current margin status for a product.

    Returns margin info and whether ad-stop is recommended.
    """
    sale_price = product.get("sale_price", 0)
    # Estimated margin — in production, this comes from settlement data
    # For now, use a configurable estimate
    estimated_cost_ratio = 0.7  # 70% of sale price is cost (30% gross margin)
    estimated_cost = int(sale_price * estimated_cost_ratio)
    margin = sale_price - estimated_cost
    margin_pct = (margin / sale_price * 100) if sale_price > 0 else 0

    ad_stop_threshold = rule.get("ad_stop_threshold", 1.0) if rule else 1.0
    ad_stop_recommended = margin_pct <= ad_stop_threshold

    return {
        "product_id": product["seller_product_id"],
        "product_name": product.get("product_name", ""),
        "sale_price": sale_price,
        "estimated_cost": estimated_cost,
        "margin": margin,
        "margin_pct": round(margin_pct, 2),
        "ad_stop_recommended": ad_stop_recommended,
        "ad_stop_threshold": ad_stop_threshold,
    }


async def generate_proposals() -> list[dict]:
    """Generate price change proposals for all products with active rules.

    This is monitoring-only — proposals are shown in the UI but not executed.
    """
    products = await db.get_cached_products()
    rules = await db.get_pricing_rules()
    rules_map = {r["product_id"]: r for r in rules}

    proposals = []
    for product in products:
        pid = product["seller_product_id"]
        rule = rules_map.get(pid)
        if not rule:
            continue

        margin_info = await evaluate_product_margin(product, rule)
        sale_price = product.get("sale_price", 0)
        min_margin_pct = rule.get("min_margin_pct", 3.0)

        # Check if margin is below minimum
        if margin_info["margin_pct"] < min_margin_pct and sale_price > 0:
            # Calculate price needed for minimum margin
            estimated_cost = margin_info["estimated_cost"]
            target_price = int(estimated_cost / (1 - min_margin_pct / 100))

            # Apply safety guards
            price_change_pct = abs(target_price - sale_price) / sale_price * 100
            if price_change_pct > MAX_PRICE_CHANGE_PCT:
                target_price = int(sale_price * (1 + MAX_PRICE_CHANGE_PCT / 100))

            if rule.get("min_price") and target_price < rule["min_price"]:
                target_price = rule["min_price"]
            if rule.get("max_price") and target_price > rule["max_price"]:
                target_price = rule["max_price"]

            if target_price != sale_price:
                new_margin = target_price - estimated_cost
                new_margin_pct = (new_margin / target_price * 100) if target_price > 0 else 0

                proposals.append({
                    "product_id": pid,
                    "product_name": product.get("product_name", ""),
                    "current_price": sale_price,
                    "proposed_price": target_price,
                    "current_margin_pct": margin_info["margin_pct"],
                    "proposed_margin_pct": round(new_margin_pct, 2),
                    "reason": f"마진 {margin_info['margin_pct']:.1f}% → 최소 {min_margin_pct}% 미달",
                    "ad_stop_recommended": margin_info["ad_stop_recommended"],
                })

        # Check ad-stop condition even without price change
        elif margin_info["ad_stop_recommended"]:
            proposals.append({
                "product_id": pid,
                "product_name": product.get("product_name", ""),
                "current_price": sale_price,
                "proposed_price": sale_price,
                "current_margin_pct": margin_info["margin_pct"],
                "proposed_margin_pct": margin_info["margin_pct"],
                "reason": f"마진 {margin_info['margin_pct']:.1f}% — 광고 중지 권장",
                "ad_stop_recommended": True,
            })

    return proposals


async def get_all_margins() -> list[dict]:
    """Get margin status for all products."""
    products = await db.get_cached_products()
    rules = await db.get_pricing_rules()
    rules_map = {r["product_id"]: r for r in rules}

    margins = []
    for product in products:
        pid = product["seller_product_id"]
        rule = rules_map.get(pid)
        margin_info = await evaluate_product_margin(product, rule)
        margin_info["has_rule"] = rule is not None
        margins.append(margin_info)

    return margins
