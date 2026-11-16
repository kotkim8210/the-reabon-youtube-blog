"""Background scheduler for periodic Coupang data refresh."""

import asyncio
import logging
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
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
        orders: list[dict] = []
        for order_status in ("ACCEPT", "INSTRUCT"):
            result = await coupang_client.get_order_sheets(
                created_at_from=date_from,
                created_at_to=date_to,
                order_status=order_status,
            )
            if result and isinstance(result.get("data"), list):
                orders.extend(result["data"])
        if orders:
            await db.cache_orders(orders)
            logger.info(f"Orders refreshed: {len(orders)} items")
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


# ── DB 자동 백업 ──────────────────────────────────────────────────
# 종전엔 일요일 03:00 주 1회 + misfire 유예 1초(기본값)라 그 시각에 PC가 꺼져 있으면 그 주가 통째로 빠졌다
# (2026-10-25 이후 백업 0건). → 매일 12:30(KST), 그 시각에 PC가 잠들어 있었으면 깨어날 때 실행(유예 12시간),
# 서버 시작 때 마지막 백업이 24시간 넘었으면 몇 분 뒤 1회. 백업이 DB와 같은 디스크(C:)에만 있으면
# 디스크가 죽을 때 같이 사라지므로 다른 물리 디스크(BACKUP_MIRROR_DIR, 기본 D:)에도 복사한다.
KST = timezone(timedelta(hours=9))
BACKUP_KEEP_LOCAL = 14
BACKUP_KEEP_MIRROR = 30
BACKUP_MAX_AGE = timedelta(hours=24)
BACKUP_MISFIRE_GRACE_SECONDS = 12 * 3600
BACKUP_CATCHUP_DELAY = timedelta(minutes=3)
DEFAULT_BACKUP_MIRROR_DIR = "D:/rj-balju-backups"
# 자동 백업 파일명만 센다(종전 UTC 4자리 시각 이름 포함). 손으로 둔 다른 파일은 지우지 않는다.
_BACKUP_NAME_RE = re.compile(r"^backup_\d{8}_\d{4}(\d{2})?\.db$")


def _local_backup_dir() -> str:
    from app.config import DATABASE_PATH
    return os.path.join(os.path.dirname(DATABASE_PATH), "backups")


def _backup_mirror_dir() -> str:
    """다른 물리 디스크의 백업 폴더. 환경변수 BACKUP_MIRROR_DIR(빈 값이면 미러 안 함)."""
    return os.getenv("BACKUP_MIRROR_DIR", DEFAULT_BACKUP_MIRROR_DIR).strip()


def _backup_files(folder: str) -> list[str]:
    """자동 백업 파일명 목록, 오래된 것부터(이름 = 시각순). 폴더가 없으면 빈 목록."""
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    return sorted(n for n in names if _BACKUP_NAME_RE.match(n))


def _prune_backups(folder: str, keep: int) -> None:
    for old in _backup_files(folder)[:-keep]:
        try:
            os.remove(os.path.join(folder, old))
        except OSError as exc:  # 잠긴 파일 하나 때문에 나머지 오래된 백업까지 남지 않게 건너뛴다
            logger.warning(f"오래된 백업 삭제 실패(건너뜀): {old} — {exc}")


def backup_catchup_needed(backup_dir: str, now: datetime | None = None) -> bool:
    """가장 최근 자동 백업이 24시간보다 오래됐거나 하나도 없으면 True."""
    latest = None
    for name in _backup_files(backup_dir):
        try:
            mtime = os.path.getmtime(os.path.join(backup_dir, name))
        except OSError:
            continue
        latest = mtime if latest is None else max(latest, mtime)
    if latest is None:
        return True
    now_ts = (now or datetime.now(KST)).timestamp()
    return now_ts - latest > BACKUP_MAX_AGE.total_seconds()


def _mirror_backup(src: str, mirror_dir: str) -> str | None:
    """로컬 백업을 다른 디스크로 복사. 드라이브가 없거나 실패하면 경고만 남기고 None(로컬 백업은 유지)."""
    if not mirror_dir:
        return None
    anchor = Path(mirror_dir).anchor
    if not anchor or not os.path.isdir(anchor):
        logger.warning(f"DB 백업 미러 드라이브 없음 — 로컬 백업만 유지: {mirror_dir}")
        return None
    dst = os.path.join(mirror_dir, os.path.basename(src))
    tmp = dst + ".part"  # 복사 중 실패해도 깨진 파일이 백업 이름으로 남지 않게
    try:
        os.makedirs(mirror_dir, exist_ok=True)
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
    except Exception as e:
        logger.warning(f"DB 백업 미러 복사 실패 — 로컬 백업만 유지: {e}")
        try:
            os.remove(tmp)
        except OSError:
            pass
        return None
    logger.info(f"DB backup mirrored: {dst}")
    try:
        _prune_backups(mirror_dir, BACKUP_KEEP_MIRROR)
    except Exception as e:
        logger.warning(f"DB 백업 미러 정리 실패: {e}")
    return dst


async def backup_database() -> str | None:
    """SQLite VACUUM INTO 스냅샷 → data/backups(최근 14개) + 미러 디스크(최근 30개). 로컬 백업 경로를 돌려준다."""
    backup_dir = _local_backup_dir()
    ts = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
    target = os.path.join(backup_dir, f"backup_{ts}.db")
    try:
        os.makedirs(backup_dir, exist_ok=True)
        conn = await db.get_db()
        await conn.execute(f"VACUUM INTO '{target}'")
        logger.info(f"DB backup written: {target}")
    except Exception as e:
        logger.error(f"Backup failed: {e}")
        return None
    try:
        _prune_backups(backup_dir, BACKUP_KEEP_LOCAL)
    except Exception as e:
        logger.warning(f"DB 백업 정리 실패: {e}")
    # 잠든 HDD를 깨우거나 복사하는 몇 초 동안 서버(이벤트 루프)를 막지 않게 스레드에서
    await asyncio.to_thread(_mirror_backup, target, _backup_mirror_dir())
    return target


async def refresh_supplier_price_monitors():
    """Daily 10:00 KST supplier price check for margin defense."""
    from app.supplier_price_monitor import refresh_supplier_price_snapshots

    try:
        results = await refresh_supplier_price_snapshots()
        failed = {key: value for key, value in results.items() if value != "ok"}
        if failed:
            logger.warning("Supplier price monitor finished with errors: %s", failed)
        else:
            logger.info("Supplier price monitor refreshed: %s", results)
    except Exception as e:
        logger.error(f"Supplier price monitor refresh failed: {e}")


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
        trigger=CronTrigger(hour=12, minute=30, timezone="Asia/Seoul"),
        id="backup_database",
        replace_existing=True,
        misfire_grace_time=BACKUP_MISFIRE_GRACE_SECONDS,
        coalesce=True,
    )
    # 서버 시작 시 마지막 백업이 24시간 넘었으면(그 시각에 PC가 꺼져 있었으면) 몇 분 뒤 1회 따라잡기
    try:
        if backup_catchup_needed(_local_backup_dir()):
            scheduler.add_job(
                backup_database,
                trigger=DateTrigger(run_date=datetime.now(KST) + BACKUP_CATCHUP_DELAY),
                id="backup_database_catchup",
                replace_existing=True,
                misfire_grace_time=BACKUP_MISFIRE_GRACE_SECONDS,
            )
            logger.info("마지막 DB 백업이 24시간 넘음 — 몇 분 뒤 캐치업 백업")
    except Exception as e:
        logger.warning(f"DB 백업 캐치업 예약 실패: {e}")
    scheduler.add_job(
        refresh_supplier_price_monitors,
        trigger=CronTrigger(hour=10, minute=0, timezone="Asia/Seoul"),
        id="refresh_supplier_price_monitors",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Background scheduler started")


def stop_scheduler():
    """Stop background scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Background scheduler stopped")
