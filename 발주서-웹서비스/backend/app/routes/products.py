"""Product data API routes."""

from fastapi import APIRouter, Depends

from app.auth import verify_token
from app import db

router = APIRouter(prefix="/api/products", tags=["products"])


@router.get("")
async def list_products(_token: dict = Depends(verify_token)):
    """Get all cached Coupang products."""
    products = await db.get_cached_products()
    return {"products": products}


@router.get("/{product_id}")
async def get_product(product_id: int, _token: dict = Depends(verify_token)):
    """Get product detail with sales data."""
    products = await db.get_cached_products()
    product = next((p for p in products if p["seller_product_id"] == product_id), None)
    if not product:
        return {"error": "Product not found"}

    avg_sales = await db.get_daily_sales_avg(product_id, days=7)
    stock = product.get("stock", 0)
    days_remaining = (stock / avg_sales) if avg_sales > 0 else 999.0

    return {
        **product,
        "avg_daily_sales": round(avg_sales, 1),
        "days_remaining": round(days_remaining, 1),
    }
