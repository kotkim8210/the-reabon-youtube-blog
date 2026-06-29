"""Dashboard API routes for homepage widgets and refresh actions."""

from __future__ import annotations

import json
from datetime import datetime
from io import BytesIO
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app import db
from app.auth import require_admin, verify_token
from app.coupang.client import coupang_client
from app.coupang.risk import calculate_all_risk_scores
from app.supplier_price_monitor import (
    is_supplier_monitor_paused,
    refresh_supplier_price_snapshots,
    run_kolrabi_monitor,
    run_myeongi_monitor,
    run_supplier_monitor,
)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _make_excel_response(output_bytes: bytes, filename: str, stats: dict | None = None) -> StreamingResponse:
    encoded_filename = quote(filename)
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
        "Access-Control-Expose-Headers": "Content-Disposition, X-Stats",
    }
    if stats:
        headers["X-Stats"] = json.dumps(stats, ensure_ascii=True)
    return StreamingResponse(
        BytesIO(output_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@router.get("/risk-scores")
async def get_risk_scores(_token: dict = Depends(verify_token)):
    scores = await calculate_all_risk_scores()
    return {"scores": scores}


@router.get("/recent-orders")
async def get_recent_orders(_token: dict = Depends(verify_token)):
    orders = await db.get_cached_orders(limit=20)
    return {"orders": orders}


@router.get("/inventory-alerts")
async def get_inventory_alerts(_token: dict = Depends(verify_token)):
    products = await db.get_cached_products()
    alerts = []
    for product in products:
        if product.get("status", "") in ("판매중지", "SUSPEND"):
            continue
        if not product.get("vendor_item_id"):
            continue

        stock = product.get("stock", 0)
        avg_sales = await db.get_daily_sales_avg(product["seller_product_id"], days=7)
        days_remaining = (stock / avg_sales) if avg_sales > 0 else 999.0

        if stock <= 10 or days_remaining < 7:
            status = "critical" if stock <= 5 or days_remaining < 3 else "warning"
            alerts.append(
                {
                    "product_id": product["seller_product_id"],
                    "product_name": product["product_name"],
                    "stock": stock,
                    "status": status,
                    "avg_daily_sales": round(avg_sales, 1),
                    "days_remaining": round(days_remaining, 1),
                }
            )

    alerts.sort(key=lambda item: item["stock"])
    return {"alerts": alerts}


@router.get("/summary")
async def get_summary(_token: dict = Depends(verify_token)):
    products = await db.get_cached_products()
    orders = await db.get_cached_orders(limit=100)

    today = datetime.utcnow().strftime("%Y-%m-%d")
    today_orders = [order for order in orders if order.get("ordered_at", "").startswith(today)]
    total_revenue = sum(order.get("sale_price", 0) * order.get("quantity", 1) for order in today_orders)

    critical_count = 0
    for product in products:
        if product.get("status", "") in ("판매중지", "SUSPEND"):
            continue
        if not product.get("vendor_item_id"):
            continue
        if product.get("stock", 0) <= 5:
            critical_count += 1

    return {
        "total_orders_today": len(today_orders),
        "total_revenue_today": total_revenue,
        "total_products": len(products),
        "critical_alerts": critical_count,
    }


@router.post("/refresh")
async def refresh_data(_token: dict = Depends(verify_token)):
    from app.scheduler import refresh_orders, refresh_products

    try:
        await refresh_products()
        await refresh_orders()
        return {"status": "ok", "message": "데이터 갱신 완료"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


@router.get("/debug-raw")
async def debug_raw_data(_token: dict = Depends(verify_token)):
    products = await db.get_cached_products()
    zero_price = next(
        (product for product in products if product.get("sale_price", 0) == 0 and product.get("stock", 0) > 0),
        None,
    )
    has_price = next((product for product in products if product.get("sale_price", 0) > 0), None)

    results = {}
    for label, product in [("zero_price_product", zero_price), ("has_price_product", has_price)]:
        if not product:
            continue
        try:
            detail = await coupang_client.get_product_detail(product["seller_product_id"])
            results[label] = {
                "product_id": product["seller_product_id"],
                "db_stock": product["stock"],
                "db_price": product["sale_price"],
                "api_detail": detail,
            }
        except Exception as exc:
            results[label] = {"error": str(exc)}

    return results


@router.get("/supplier-price-monitor/myeongi")
async def get_myeongi_supplier_price_monitor(_token: dict = Depends(require_admin)):
    summary, _, _ = await run_myeongi_monitor()
    return summary


@router.get("/supplier-price-alerts")
async def get_supplier_price_alerts(_token: dict = Depends(require_admin)):
    rows = await db.list_latest_supplier_price_monitor_runs()
    rows = [row for row in rows if not is_supplier_monitor_paused(str(row.get("monitor_key") or ""))]
    active = [
        row for row in rows
        if row.get("status") != "ok" or int(row.get("changed_items") or 0) > 0
    ]
    return {
        "alerts": rows,
        "active_count": len(active),
        "checked_monitors": len(rows),
    }


@router.post("/supplier-price-monitor/refresh-all")
async def refresh_supplier_price_monitor_all(_token: dict = Depends(require_admin)):
    results = await refresh_supplier_price_snapshots()
    return {"status": "ok", "results": results}


@router.post("/supplier-price-monitor/myeongi/download")
async def download_myeongi_supplier_price_monitor(_token: dict = Depends(require_admin)):
    summary, output_bytes, filename = await run_myeongi_monitor()
    return _make_excel_response(output_bytes, filename, summary)


@router.get("/supplier-price-monitor/kolrabi")
async def get_kolrabi_supplier_price_monitor(_token: dict = Depends(require_admin)):
    summary, _, _ = await run_kolrabi_monitor()
    return summary


@router.post("/supplier-price-monitor/kolrabi/download")
async def download_kolrabi_supplier_price_monitor(_token: dict = Depends(require_admin)):
    summary, output_bytes, filename = await run_kolrabi_monitor()
    return _make_excel_response(output_bytes, filename, summary)


@router.get("/supplier-price-monitor/{monitor_key}")
async def get_supplier_price_monitor(monitor_key: str, _token: dict = Depends(require_admin)):
    summary, _, _ = await run_supplier_monitor(monitor_key)
    return summary


@router.post("/supplier-price-monitor/{monitor_key}/download")
async def download_supplier_price_monitor(monitor_key: str, _token: dict = Depends(require_admin)):
    summary, output_bytes, filename = await run_supplier_monitor(monitor_key)
    return _make_excel_response(output_bytes, filename, summary)
