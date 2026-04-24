"""Background scheduler for periodic Coupang data refresh."""

import asyncio
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app import db
from app.config import DISABLE_BILLING
from app.coupang.client import coupang_client

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def fetch_all_products_list() -> list[dict]:
    """상품 목록 전체를 pagination으로 가져오기."""
    all_products = []
    next_token = None

    for _ in range(20):  # 최대 20페이지 (1000개)
        result = await coupang_client.get_seller_products(
            next_token=next_token, max_per_page=50
        )
        if not result or "data" not in result:
            break

        products = result["data"]
        if not isinstance(products, list) or len(products) == 0:
            break

        all_products.extend(products)
        next_token = result.get("nextToken")
        if not next_token:
            break

    return all_products


async def fetch_product_detail_stock(seller_product_id: int) -> dict | None:
    """상품 상세 API에서 재고/가격 정보 추출."""
    try:
        detail = await coupang_client.get_product_detail(seller_product_id)
        if not detail or "data" not in detail:
            return None

        data = detail["data"]
        if not isinstance(data, dict):
            return None

        # items 배열에서 재고/가격 추출
        items = data.get("items", [])
        total_stock = 0
        max_price = 0
        vendor_item_id = None
        status_name = data.get("statusName", "")

        for item in items:
            # 각 옵션(vendorItem)의 재고와 가격 (None 방어)
            qty = item.get("maximumBuyCount") or 0
            price = item.get("salePrice") or 0
            vid = item.get("vendorItemId")

            # vendorItemId가 없는 항목은 유효한 옵션이 아님 → 건너뜀
            if not vid:
                continue

            total_stock += qty
            if price > max_price:
                max_price = price
            if vendor_item_id is None:
                vendor_item_id = vid

        return {
            "stock": total_stock,
            "sale_price": max_price,
            "vendor_item_id": vendor_item_id,
            "status": status_name,
        }
    except Exception as e:
        logger.error(f"Failed to fetch detail for product {seller_product_id}: {e}")
        return None


async def refresh_products():
    """상품 목록 + 상세(재고/가격) 가져와서 캐시 업데이트."""
    try:
        # 1) 상품 목록 전체 가져오기
        products = await fetch_all_products_list()
        if not products:
            logger.warning("No products returned from Coupang API")
            return

        logger.info(f"Fetched {len(products)} products from list API")

        # 2) 먼저 기본 정보로 캐시 저장
        await db.cache_products(products)

        # 3) 각 상품의 상세 정보(재고/가격) 가져오기
        # 동시에 5개씩 처리 (rate limit 고려)
        semaphore = asyncio.Semaphore(5)

        async def update_one(product):
            async with semaphore:
                pid = product.get("sellerProductId", 0)
                if not pid:
                    return
                detail = await fetch_product_detail_stock(pid)
                if detail:
                    await db.update_product_stock_price(
                        seller_product_id=pid,
                        stock=detail["stock"],
                        sale_price=detail["sale_price"],
                        vendor_item_id=detail["vendor_item_id"],
                        status=detail["status"],
                    )

        tasks = [update_one(p) for p in products]
        await asyncio.gather(*tasks)
        logger.info(f"Products detail refreshed: {len(products)} items")

    except Exception as e:
        logger.error(f"Failed to refresh products: {e}")


async def refresh_orders():
    """Fetch recent orders from Coupang and update cache."""
    try:
        date_from = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
        date_to = datetime.utcnow().strftime("%Y-%m-%d")
        result = await coupang_client.get_order_sheets(
            created_at_from=date_from,
            created_at_to=date_to,
        )
        if result and "data" in result:
            orders = result["data"]
            if isinstance(orders, list):
                await db.cache_orders(orders)
                logger.info(f"Orders refreshed: {len(orders)} items")

                # Update daily sales aggregation
                for order in orders:
                    ordered_at = order.get("orderedAt", "")
                    if ordered_at:
                        date = ordered_at[:10]  # YYYY-MM-DD
                        pid = order.get("sellerProductId", 0)
                        pname = order.get("sellerProductName", "")
                        qty = order.get("shippingCount", 1)
                        revenue = order.get("orderPrice", 0)
                        if pid:
                            await db.upsert_daily_sales(pid, pname, date, qty, revenue)
    except Exception as e:
        logger.error(f"Failed to refresh orders: {e}")


async def renew_subscriptions():
    """Charge all Pro subs whose period has ended. Daily 00:10 KST."""
    if DISABLE_BILLING:
        return
    import uuid
    from datetime import timezone
    from app.routes.billing import _charge_billing
    from app.config import PRO_PLAN_PRICE

    KST = timezone(timedelta(hours=9))
    now = datetime.now(KST)
    due = await db.list_due_subscriptions(now.isoformat())
    logger.info(f"Subscription renewals due: {len(due)}")

    for sub in due:
        user_id = sub["user_id"]
        billing_key = sub.get("billing_key")
        customer_key = sub.get("customer_key")
        if sub.get("cancel_at_period_end"):
            await db.upsert_subscription(user_id, plan_code="free", status="cancelled")
            await db.add_billing_event(user_id, "cancel", 0, raw={"reason": "period_end"})
            continue
        if not billing_key or not customer_key:
            await db.upsert_subscription(user_id, plan_code=sub["plan_code"], status="past_due")
            continue

        order_id = f"renew-{user_id}-{uuid.uuid4().hex[:12]}"
        try:
            charge = await _charge_billing(
                billing_key, customer_key, PRO_PLAN_PRICE, order_id,
                f"발주서 Pro 구독 갱신 (월 {PRO_PLAN_PRICE:,}원)",
            )
            new_start = now
            new_end = now + timedelta(days=30)
            await db.upsert_subscription(
                user_id, plan_code="pro", status="active",
                current_period_start=new_start.isoformat(),
                current_period_end=new_end.isoformat(),
            )
            await db.add_billing_event(
                user_id, "renew", PRO_PLAN_PRICE,
                toss_payment_key=charge.get("paymentKey"),
                toss_order_id=order_id, raw=charge,
            )
        except Exception as e:
            logger.error(f"Renewal failed for user {user_id}: {e}")
            await db.upsert_subscription(user_id, plan_code="pro", status="past_due")
            await db.add_billing_event(user_id, "fail", PRO_PLAN_PRICE,
                                        raw={"error": str(e), "order_id": order_id})


async def backup_database():
    """Weekly SQLite VACUUM INTO snapshot. Writes to /data/backups/."""
    import os
    from app.config import DATABASE_PATH
    backup_dir = os.path.dirname(DATABASE_PATH) + "/backups"
    os.makedirs(backup_dir, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M")
    target = f"{backup_dir}/backup_{ts}.db"
    try:
        conn = await db.get_db()
        await conn.execute(f"VACUUM INTO '{target}'")
        logger.info(f"DB backup written: {target}")
        # Retain last 8 backups
        files = sorted([f for f in os.listdir(backup_dir) if f.startswith("backup_")])
        for old in files[:-8]:
            os.remove(os.path.join(backup_dir, old))
    except Exception as e:
        logger.error(f"Backup failed: {e}")


def start_scheduler():
    """Start background scheduler with periodic jobs."""
    scheduler.add_job(
        refresh_products,
        trigger=IntervalTrigger(minutes=30),
        id="refresh_products",
        replace_existing=True,
    )
    scheduler.add_job(
        refresh_orders,
        trigger=IntervalTrigger(minutes=10),
        id="refresh_orders",
        replace_existing=True,
    )
    scheduler.add_job(
        renew_subscriptions,
        trigger=CronTrigger(hour=0, minute=10, timezone="Asia/Seoul"),
        id="renew_subscriptions",
        replace_existing=True,
    )
    scheduler.add_job(
        backup_database,
        trigger=CronTrigger(day_of_week="sun", hour=3, minute=0, timezone="Asia/Seoul"),
        id="backup_database",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Background scheduler started")


def stop_scheduler():
    """Stop background scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Background scheduler stopped")
