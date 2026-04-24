"""Dashboard API routes — real-time Coupang data."""

from fastapi import APIRouter, Depends
from datetime import datetime, timedelta

from app.auth import verify_token
from app import db
from app.coupang.risk import calculate_all_risk_scores
from app.coupang.client import coupang_client

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/risk-scores")
async def get_risk_scores(_token: dict = Depends(verify_token)):
    """Get risk traffic light scores for all products."""
    scores = await calculate_all_risk_scores()
    return {"scores": scores}


@router.get("/recent-orders")
async def get_recent_orders(_token: dict = Depends(verify_token)):
    """Get recent orders from cache."""
    orders = await db.get_cached_orders(limit=20)
    return {"orders": orders}


@router.get("/inventory-alerts")
async def get_inventory_alerts(_token: dict = Depends(verify_token)):
    """Get products with low stock."""
    products = await db.get_cached_products()
    alerts = []
    for p in products:
        # 판매중지/비활성 상품은 재고 경고 제외
        # (vendorItemId 없거나 status가 판매중지면 제외)
        if p.get("status", "") in ("판매중지", "SUSPEND"):
            continue
        if not p.get("vendor_item_id"):
            continue

        stock = p.get("stock", 0)
        avg_sales = await db.get_daily_sales_avg(p["seller_product_id"], days=7)
        days_remaining = (stock / avg_sales) if avg_sales > 0 else 999.0

        if stock <= 10 or days_remaining < 7:
            status = "critical" if stock <= 5 or days_remaining < 3 else "warning"
            alerts.append({
                "product_id": p["seller_product_id"],
                "product_name": p["product_name"],
                "stock": stock,
                "status": status,
                "avg_daily_sales": round(avg_sales, 1),
                "days_remaining": round(days_remaining, 1),
            })

    alerts.sort(key=lambda x: x["stock"])
    return {"alerts": alerts}


@router.get("/summary")
async def get_summary(_token: dict = Depends(verify_token)):
    """Get dashboard summary stats."""
    products = await db.get_cached_products()
    orders = await db.get_cached_orders(limit=100)

    today = datetime.utcnow().strftime("%Y-%m-%d")
    today_orders = [o for o in orders if o.get("ordered_at", "").startswith(today)]

    total_revenue = sum(o.get("sale_price", 0) * o.get("quantity", 1) for o in today_orders)

    # Count critical alerts (판매중지/비활성 상품 제외)
    critical_count = 0
    for p in products:
        if p.get("status", "") in ("판매중지", "SUSPEND"):
            continue
        if not p.get("vendor_item_id"):
            continue
        if p.get("stock", 0) <= 5:
            critical_count += 1

    return {
        "total_orders_today": len(today_orders),
        "total_revenue_today": total_revenue,
        "total_products": len(products),
        "critical_alerts": critical_count,
    }


@router.post("/refresh")
async def refresh_data(_token: dict = Depends(verify_token)):
    """Manually trigger data refresh from Coupang API."""
    from app.scheduler import refresh_products, refresh_orders
    try:
        await refresh_products()
        await refresh_orders()
        return {"status": "ok", "message": "데이터 갱신 완료"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/debug-raw")
async def debug_raw_data(_token: dict = Depends(verify_token)):
    """디버그: 쿠팡 상품 상세 API 원본 응답 확인."""
    # 가격 0인 상품의 상세 데이터 확인
    products = await db.get_cached_products()
    zero_price = next((p for p in products if p.get("sale_price", 0) == 0 and p.get("stock", 0) > 0), None)
    has_price = next((p for p in products if p.get("sale_price", 0) > 0), None)

    results = {}
    for label, prod in [("zero_price_product", zero_price), ("has_price_product", has_price)]:
        if prod:
            try:
                detail = await coupang_client.get_product_detail(prod["seller_product_id"])
                results[label] = {
                    "product_id": prod["seller_product_id"],
                    "db_stock": prod["stock"],
                    "db_price": prod["sale_price"],
                    "api_detail": detail,
                }
            except Exception as e:
                results[label] = {"error": str(e)}

    return results
