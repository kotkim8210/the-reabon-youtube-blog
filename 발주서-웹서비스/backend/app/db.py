"""SQLite database layer for caching Coupang data and storing pricing rules."""

import json
import logging
import re
import aiosqlite
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import DATABASE_PATH

logger = logging.getLogger(__name__)

_db: aiosqlite.Connection | None = None
KST = timezone(timedelta(hours=9))
SETTLEMENT_LOGIC_VERSION = "2026-05-06-order-date-grade-v2"
SUPPLIER_PRICE_HISTORY_RETENTION_DAYS = 8


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        _db = await aiosqlite.connect(DATABASE_PATH)
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA foreign_keys=ON")
    return _db


async def close_db():
    global _db
    if _db:
        await _db.close()
        _db = None


async def init_db():
    """Create tables if they don't exist."""
    db = await get_db()
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS cached_products (
            seller_product_id INTEGER PRIMARY KEY,
            product_name TEXT NOT NULL,
            sale_price INTEGER DEFAULT 0,
            stock INTEGER DEFAULT 0,
            status TEXT DEFAULT '',
            vendor_item_id INTEGER,
            category TEXT DEFAULT '',
            data_json TEXT DEFAULT '{}',
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS cached_orders (
            order_id TEXT PRIMARY KEY,
            ordered_at TEXT NOT NULL,
            product_name TEXT NOT NULL,
            seller_product_id INTEGER DEFAULT 0,
            quantity INTEGER DEFAULT 1,
            sale_price INTEGER DEFAULT 0,
            status TEXT DEFAULT '',
            receiver_name TEXT DEFAULT '',
            data_json TEXT DEFAULT '{}',
            cached_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS daily_sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            date TEXT NOT NULL,
            total_quantity INTEGER DEFAULT 0,
            total_revenue INTEGER DEFAULT 0,
            UNIQUE(product_id, date)
        );

        CREATE TABLE IF NOT EXISTS pricing_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER UNIQUE NOT NULL,
            product_name TEXT DEFAULT '',
            min_margin_pct REAL DEFAULT 3.0,
            min_price INTEGER DEFAULT 0,
            max_price INTEGER DEFAULT 0,
            ad_stop_threshold REAL DEFAULT 1.0,
            active INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS pricing_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            product_name TEXT DEFAULT '',
            old_price INTEGER NOT NULL,
            new_price INTEGER NOT NULL,
            margin_before REAL DEFAULT 0,
            margin_after REAL DEFAULT 0,
            reason TEXT DEFAULT '',
            executed_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            email TEXT UNIQUE,
            google_id TEXT UNIQUE,
            kakao_id TEXT,
            display_name TEXT,
            avatar_url TEXT,
            role TEXT NOT NULL DEFAULT 'user',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS blocked_ips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip_address TEXT NOT NULL,
            user_id INTEGER,
            blocked_by INTEGER NOT NULL,
            reason TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (blocked_by) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_blocked_ips ON blocked_ips(ip_address);

        CREATE TABLE IF NOT EXISTS user_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            template_name TEXT NOT NULL,
            file_data BLOB NOT NULL,
            uploaded_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS user_products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_label TEXT NOT NULL,
            coupang_product_keyword TEXT NOT NULL,
            template_id INTEGER,
            output_filename_pattern TEXT DEFAULT '{label}_{date}.xlsx',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (template_id) REFERENCES user_templates(id)
        );

        CREATE TABLE IF NOT EXISTS user_product_options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_product_id INTEGER NOT NULL,
            coupang_option_keyword TEXT NOT NULL,
            vendor_option_name TEXT NOT NULL,
            template_target_cell TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_product_id) REFERENCES user_products(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            price_krw INTEGER NOT NULL DEFAULT 0,
            max_products INTEGER,
            max_monthly_orders INTEGER,
            features_json TEXT DEFAULT '{}',
            active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            plan_code TEXT NOT NULL DEFAULT 'free',
            status TEXT NOT NULL DEFAULT 'active',
            billing_key TEXT,
            customer_key TEXT,
            current_period_start TEXT,
            current_period_end TEXT,
            cancel_at_period_end INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS billing_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            amount_krw INTEGER DEFAULT 0,
            toss_payment_key TEXT,
            toss_order_id TEXT,
            raw_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_billing_events_user ON billing_events(user_id);

        CREATE TABLE IF NOT EXISTS usage_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            product_label TEXT DEFAULT '',
            order_count INTEGER DEFAULT 0,
            ym TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_usage_user_ym ON usage_logs(user_id, ym);

        CREATE TABLE IF NOT EXISTS option_sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_label TEXT NOT NULL,
            coupang_option_keyword TEXT NOT NULL,
            vendor_option_name TEXT DEFAULT '',
            quantity INTEGER NOT NULL DEFAULT 0,
            external_order_id TEXT DEFAULT '',
            ymd TEXT NOT NULL,
            ym TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_option_sales_user_ymd ON option_sales(user_id, ymd);
        CREATE INDEX IF NOT EXISTS idx_option_sales_user_ym ON option_sales(user_id, ym);
        CREATE INDEX IF NOT EXISTS idx_option_sales_user_label_ymd ON option_sales(user_id, product_label, ymd);

        CREATE TABLE IF NOT EXISTS supplier_price_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            monitor_key TEXT NOT NULL,
            supplier_name TEXT NOT NULL,
            product_name TEXT NOT NULL,
            option_name TEXT NOT NULL,
            supplier_option_name TEXT NOT NULL,
            normalized_option_key TEXT NOT NULL,
            supplier_price INTEGER NOT NULL DEFAULT 0,
            checked_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_supplier_price_snapshots_key
            ON supplier_price_snapshots(normalized_option_key, checked_at DESC);
        CREATE INDEX IF NOT EXISTS idx_supplier_price_snapshots_monitor
            ON supplier_price_snapshots(monitor_key, checked_at DESC);

        CREATE TABLE IF NOT EXISTS supplier_price_monitor_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date TEXT NOT NULL,
            monitor_key TEXT NOT NULL,
            supplier_name TEXT DEFAULT '',
            product_name TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'ok',
            total_items INTEGER NOT NULL DEFAULT 0,
            changed_items INTEGER NOT NULL DEFAULT 0,
            blue_count INTEGER NOT NULL DEFAULT 0,
            red_count INTEGER NOT NULL DEFAULT 0,
            same_count INTEGER NOT NULL DEFAULT 0,
            output_filename TEXT DEFAULT '',
            error_message TEXT DEFAULT '',
            checked_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_supplier_price_monitor_runs_date
            ON supplier_price_monitor_runs(run_date DESC, checked_at DESC);
        CREATE INDEX IF NOT EXISTS idx_supplier_price_monitor_runs_key
            ON supplier_price_monitor_runs(monitor_key, checked_at DESC);

        CREATE TABLE IF NOT EXISTS daily_settlement_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_label TEXT NOT NULL,
            coupang_option_keyword TEXT NOT NULL,
            vendor_option_name TEXT DEFAULT '',
            quantity INTEGER NOT NULL DEFAULT 0,
            unit_price_krw INTEGER NOT NULL DEFAULT 0,
            unit_price_source TEXT NOT NULL DEFAULT 'missing',
            supplier_price_option_name TEXT DEFAULT '',
            settlement_krw INTEGER NOT NULL DEFAULT 0,
            ymd TEXT NOT NULL,
            ym TEXT NOT NULL,
            logic_version TEXT NOT NULL DEFAULT '',
            snapshot_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_daily_settlement_snapshots_user_ymd
            ON daily_settlement_snapshots(user_id, ymd);
        CREATE INDEX IF NOT EXISTS idx_daily_settlement_snapshots_user_ym
            ON daily_settlement_snapshots(user_id, ym);

        CREATE TABLE IF NOT EXISTS risk_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            product_name TEXT DEFAULT '',
            score REAL NOT NULL,
            level TEXT NOT NULL,
            stock INTEGER DEFAULT 0,
            avg_daily_sales REAL DEFAULT 0,
            days_remaining REAL DEFAULT 0,
            margin_pct REAL DEFAULT 0,
            snapshot_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS order_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            source_key TEXT NOT NULL,
            batch_name TEXT NOT NULL,
            template_name TEXT NOT NULL,
            output_filename TEXT NOT NULL,
            total_rows INTEGER NOT NULL DEFAULT 0,
            total_quantity INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT DEFAULT '{}',
            processed_at TEXT NOT NULL,
            sync_status TEXT NOT NULL DEFAULT 'pending',
            sync_error TEXT DEFAULT '',
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_order_batches_user_processed_at
            ON order_batches(user_id, processed_at DESC);

        CREATE TABLE IF NOT EXISTS order_batch_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            platform_option_name TEXT DEFAULT '',
            supply_option_name TEXT DEFAULT '',
            quantity INTEGER NOT NULL DEFAULT 0,
            external_order_id TEXT DEFAULT '',
            receiver_name TEXT DEFAULT '',
            receiver_phone TEXT DEFAULT '',
            receiver_address TEXT DEFAULT '',
            memo TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY (batch_id) REFERENCES order_batches(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_order_batch_items_batch_id
            ON order_batch_items(batch_id);
    """)
    # --- Column migrations for existing deployments ---
    # user_product_options.unit_price_krw (정산 단가)
    cursor = await db.execute("PRAGMA table_info(user_product_options)")
    cols = {r["name"] for r in await cursor.fetchall()}
    if "unit_price_krw" not in cols:
        await db.execute(
            "ALTER TABLE user_product_options ADD COLUMN unit_price_krw INTEGER NOT NULL DEFAULT 0"
        )
        logger.info("Migrated: user_product_options.unit_price_krw added")

    # Seed default team password from env if not already set
    from app.config import TEAM_PASSWORD
    cursor = await db.execute("SELECT value FROM app_settings WHERE key = 'team_password'")
    row = await cursor.fetchone()
    if not row:
        now = datetime.utcnow().isoformat()
        await db.execute(
            "INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("team_password", TEAM_PASSWORD, now),
        )

    # Seed admin user if users table is empty
    cursor = await db.execute("SELECT COUNT(*) as cnt FROM users")
    row = await cursor.fetchone()
    if row["cnt"] == 0:
        from passlib.hash import bcrypt
        now = datetime.utcnow().isoformat()
        admin_hash = bcrypt.hash(TEAM_PASSWORD)
        await db.execute(
            "INSERT INTO users (username, password_hash, role, created_at, updated_at) VALUES (?, ?, 'admin', ?, ?)",
            ("admin", admin_hash, now, now),
        )
        logger.info("Admin user seeded")

    # Seed plans
    cursor = await db.execute("SELECT COUNT(*) as cnt FROM plans")
    if (await cursor.fetchone())["cnt"] == 0:
        await db.execute(
            "INSERT INTO plans (code, name, price_krw, max_products, max_monthly_orders, features_json, active) VALUES (?, ?, ?, ?, ?, ?, 1)",
            ("free", "무료", 0, 1, 50, '{"tracking": false, "coupang_api": false, "pricing": false, "sales_history_days": 30}'),
        )
        await db.execute(
            "INSERT INTO plans (code, name, price_krw, max_products, max_monthly_orders, features_json, active) VALUES (?, ?, ?, ?, ?, ?, 1)",
            ("pro", "Pro", 29000, None, 3000, '{"tracking": true, "coupang_api": true, "pricing": true, "sales_history_days": null}'),
        )
        logger.info("Plans seeded")

    # Ensure admin has pro subscription
    cursor = await db.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
    admin_row = await cursor.fetchone()
    if admin_row:
        now = datetime.utcnow().isoformat()
        await db.execute(
            """INSERT INTO subscriptions (user_id, plan_code, status, created_at, updated_at)
               VALUES (?, 'pro', 'active', ?, ?)
               ON CONFLICT(user_id) DO NOTHING""",
            (admin_row["id"], now, now),
        )

    # Migrate: add kakao_id, display_name, avatar_url columns if missing (existing DBs)
    # NOTE: SQLite ALTER TABLE ADD COLUMN does NOT support inline UNIQUE/PRIMARY KEY.
    #       We add the column first, then create a separate unique index.
    cursor = await db.execute("PRAGMA table_info(users)")
    rows = await cursor.fetchall()
    existing_cols = {row["name"] for row in rows}
    for col, definition in [
        ("kakao_id",    "TEXT"),
        ("display_name","TEXT"),
        ("avatar_url",  "TEXT"),
    ]:
        if col not in existing_cols:
            await db.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
            logger.info("Migrated users: added column %s", col)
    # Ensure unique partial index on kakao_id (created here so it runs AFTER the column migration)
    await db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_kakao_id ON users(kakao_id) WHERE kakao_id IS NOT NULL"
    )
    await db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_id ON users(google_id) WHERE google_id IS NOT NULL"
    )

    cursor = await db.execute("PRAGMA table_info(option_sales)")
    option_sales_cols = {row["name"] for row in await cursor.fetchall()}
    if "external_order_id" not in option_sales_cols:
        await db.execute(
            "ALTER TABLE option_sales ADD COLUMN external_order_id TEXT DEFAULT ''"
        )
        logger.info("Migrated: option_sales.external_order_id added")
    await db.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_option_sales_unique_order_line
           ON option_sales(user_id, external_order_id, product_label, coupang_option_keyword, vendor_option_name)
           WHERE external_order_id <> ''"""
    )

    cursor = await db.execute("PRAGMA table_info(daily_settlement_snapshots)")
    settlement_cols = {row["name"] for row in await cursor.fetchall()}
    if "logic_version" not in settlement_cols:
        await db.execute(
            "ALTER TABLE daily_settlement_snapshots ADD COLUMN logic_version TEXT NOT NULL DEFAULT ''"
        )
        logger.info("Migrated: daily_settlement_snapshots.logic_version added")

    await db.commit()
    logger.info("Database initialized")


# --- App settings helpers ---

async def get_setting(key: str) -> str | None:
    db = await get_db()
    cursor = await db.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return row["value"] if row else None


async def set_setting(key: str, value: str):
    db = await get_db()
    now = datetime.utcnow().isoformat()
    await db.execute(
        """INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
        (key, value, now),
    )
    await db.commit()


# --- Cache helpers ---

async def cache_products(products: list[dict]):
    db = await get_db()
    now = datetime.utcnow().isoformat()
    for p in products:
        await db.execute(
            """INSERT OR REPLACE INTO cached_products
               (seller_product_id, product_name, sale_price, stock, status, vendor_item_id, category, data_json, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                p.get("sellerProductId", 0),
                p.get("sellerProductName", ""),
                p.get("salePrice", 0),
                p.get("stockQuantity", 0),
                p.get("statusName", ""),
                p.get("vendorItemId"),
                p.get("displayCategoryName", ""),
                json.dumps(p, ensure_ascii=False),
                now,
            ),
        )
    await db.commit()


async def update_product_stock_price(
    seller_product_id: int,
    stock: int,
    sale_price: int,
    vendor_item_id: int | None = None,
    status: str = "",
):
    """상품 상세에서 가져온 재고/가격/상태 업데이트."""
    db = await get_db()
    await db.execute(
        """UPDATE cached_products
           SET stock = ?, sale_price = ?, vendor_item_id = ?, status = ?
           WHERE seller_product_id = ?""",
        (stock, sale_price, vendor_item_id, status, seller_product_id),
    )
    await db.commit()


async def get_cached_products() -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM cached_products ORDER BY product_name"
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def cache_orders(orders: list[dict]):
    db = await get_db()
    now = datetime.utcnow().isoformat()
    for o in orders:
        await db.execute(
            """INSERT OR REPLACE INTO cached_orders
               (order_id, ordered_at, product_name, seller_product_id, quantity, sale_price, status, receiver_name, data_json, cached_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(o.get("orderId", "")),
                o.get("orderedAt", ""),
                o.get("sellerProductName", o.get("productName", "")),
                o.get("sellerProductId", 0),
                o.get("shippingCount", 1),
                o.get("orderPrice", 0),
                o.get("statusName", o.get("status", "")),
                o.get("receiver", {}).get("name", "") if isinstance(o.get("receiver"), dict) else "",
                json.dumps(o, ensure_ascii=False),
                now,
            ),
        )
    await db.commit()


async def get_cached_orders(limit: int = 20) -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM cached_orders ORDER BY ordered_at DESC LIMIT ?",
        (limit,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_daily_sales_avg(product_id: int, days: int = 7) -> float:
    """Get average daily sales for a product over the past N days."""
    db = await get_db()
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    cursor = await db.execute(
        "SELECT AVG(total_quantity) as avg_qty FROM daily_sales WHERE product_id = ? AND date >= ?",
        (product_id, since),
    )
    row = await cursor.fetchone()
    return float(row["avg_qty"]) if row and row["avg_qty"] else 0.0


async def upsert_daily_sales(product_id: int, product_name: str, date: str, quantity: int, revenue: int):
    db = await get_db()
    await db.execute(
        """INSERT INTO daily_sales (product_id, product_name, date, total_quantity, total_revenue)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(product_id, date) DO UPDATE SET
             total_quantity = total_quantity + excluded.total_quantity,
             total_revenue = total_revenue + excluded.total_revenue""",
        (product_id, product_name, date, quantity, revenue),
    )
    await db.commit()


# --- Pricing rules ---

async def get_pricing_rules() -> list[dict]:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM pricing_rules WHERE active = 1")
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def upsert_pricing_rule(rule: dict):
    db = await get_db()
    now = datetime.utcnow().isoformat()
    await db.execute(
        """INSERT INTO pricing_rules (product_id, product_name, min_margin_pct, min_price, max_price, ad_stop_threshold, active, created_at)
           VALUES (?, ?, ?, ?, ?, ?, 1, ?)
           ON CONFLICT(product_id) DO UPDATE SET
             product_name = excluded.product_name,
             min_margin_pct = excluded.min_margin_pct,
             min_price = excluded.min_price,
             max_price = excluded.max_price,
             ad_stop_threshold = excluded.ad_stop_threshold,
             active = 1""",
        (
            rule["product_id"],
            rule.get("product_name", ""),
            rule.get("min_margin_pct", 3.0),
            rule.get("min_price", 0),
            rule.get("max_price", 0),
            rule.get("ad_stop_threshold", 1.0),
            now,
        ),
    )
    await db.commit()


async def delete_pricing_rule(product_id: int):
    db = await get_db()
    await db.execute("UPDATE pricing_rules SET active = 0 WHERE product_id = ?", (product_id,))
    await db.commit()


async def add_pricing_log(log: dict):
    db = await get_db()
    now = datetime.utcnow().isoformat()
    await db.execute(
        """INSERT INTO pricing_log (product_id, product_name, old_price, new_price, margin_before, margin_after, reason, executed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            log["product_id"],
            log.get("product_name", ""),
            log["old_price"],
            log["new_price"],
            log.get("margin_before", 0),
            log.get("margin_after", 0),
            log.get("reason", ""),
            now,
        ),
    )
    await db.commit()


async def get_pricing_logs(limit: int = 50) -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM pricing_log ORDER BY executed_at DESC LIMIT ?", (limit,)
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


# --- User management ---

async def get_user_by_id(user_id: int) -> dict | None:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_user_by_username(username: str) -> dict | None:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM users WHERE username = ?", (username,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_user_by_email(email: str) -> dict | None:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM users WHERE email = ?", (email,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_all_users() -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT id, username, email, role, is_active, created_at, updated_at FROM users ORDER BY id"
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def create_user(username: str, password_hash: str, role: str = "user", email: str | None = None) -> int:
    db = await get_db()
    now = datetime.utcnow().isoformat()
    cursor = await db.execute(
        "INSERT INTO users (username, password_hash, email, role, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (username, password_hash, email, role, now, now),
    )
    await db.commit()
    return cursor.lastrowid


async def update_user_active(user_id: int, is_active: bool):
    db = await get_db()
    now = datetime.utcnow().isoformat()
    await db.execute(
        "UPDATE users SET is_active = ?, updated_at = ? WHERE id = ?",
        (1 if is_active else 0, now, user_id),
    )
    await db.commit()


async def get_user_by_google_id(google_id: str) -> dict | None:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM users WHERE google_id = ?", (google_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_user_by_kakao_id(kakao_id: str) -> dict | None:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM users WHERE kakao_id = ?", (kakao_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def upsert_oauth_user(
    provider: str,            # "google" | "kakao"
    provider_id: str,
    email: str | None,
    display_name: str | None,
    avatar_url: str | None = None,
) -> dict:
    """Find or create a user from an OAuth provider. Returns the user dict.

    Priority:
    1. Match by provider_id column
    2. Match by email (link provider_id to existing account)
    3. Create new account
    """
    db = await get_db()
    now = datetime.utcnow().isoformat()
    id_col = f"{provider}_id"  # "google_id" or "kakao_id"

    # 1. Match by provider_id
    cursor = await db.execute(f"SELECT * FROM users WHERE {id_col} = ?", (provider_id,))
    user = await cursor.fetchone()
    if user:
        user = dict(user)
        # Refresh display info if changed
        await db.execute(
            f"UPDATE users SET display_name=?, avatar_url=?, updated_at=? WHERE id=?",
            (display_name, avatar_url, now, user["id"]),
        )
        await db.commit()
        user["display_name"] = display_name
        user["avatar_url"] = avatar_url
        return user

    # 2. Match by email → link provider_id
    if email:
        cursor = await db.execute("SELECT * FROM users WHERE email = ?", (email,))
        user = await cursor.fetchone()
        if user:
            user = dict(user)
            await db.execute(
                f"UPDATE users SET {id_col}=?, display_name=?, avatar_url=?, updated_at=? WHERE id=?",
                (provider_id, display_name, avatar_url, now, user["id"]),
            )
            await db.commit()
            user[id_col] = provider_id
            return user

    # 3. Create new user (no password — social-only account)
    base = (display_name or email or f"{provider}user").split("@")[0][:20]
    username = base
    # Ensure uniqueness
    suffix = 1
    while True:
        cursor = await db.execute("SELECT id FROM users WHERE username = ?", (username,))
        if not await cursor.fetchone():
            break
        username = f"{base}{suffix}"
        suffix += 1

    cursor = await db.execute(
        f"INSERT INTO users (username, password_hash, email, {id_col}, display_name, avatar_url, role, created_at, updated_at) "
        "VALUES (?, '', ?, ?, ?, ?, 'user', ?, ?)",
        (username, email, provider_id, display_name, avatar_url, now, now),
    )
    await db.commit()
    user_id = cursor.lastrowid
    cursor = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    return dict(await cursor.fetchone())


async def update_user_password(user_id: int, password_hash: str):
    db = await get_db()
    now = datetime.utcnow().isoformat()
    await db.execute(
        "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
        (password_hash, now, user_id),
    )
    await db.commit()


# --- Blocked IPs ---

async def get_blocked_ips() -> list[dict]:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM blocked_ips ORDER BY created_at DESC")
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def is_ip_blocked(ip_address: str) -> bool:
    db = await get_db()
    cursor = await db.execute("SELECT 1 FROM blocked_ips WHERE ip_address = ?", (ip_address,))
    return await cursor.fetchone() is not None


async def add_blocked_ip(ip_address: str, blocked_by: int, user_id: int | None = None, reason: str = "") -> int:
    db = await get_db()
    now = datetime.utcnow().isoformat()
    cursor = await db.execute(
        "INSERT INTO blocked_ips (ip_address, user_id, blocked_by, reason, created_at) VALUES (?, ?, ?, ?, ?)",
        (ip_address, user_id, blocked_by, reason, now),
    )
    await db.commit()
    return cursor.lastrowid


async def remove_blocked_ip(block_id: int):
    db = await get_db()
    await db.execute("DELETE FROM blocked_ips WHERE id = ?", (block_id,))
    await db.commit()


# --- User templates ---

async def save_user_template(user_id: int, template_name: str, file_data: bytes) -> int:
    db = await get_db()
    now = datetime.utcnow().isoformat()
    cursor = await db.execute(
        "INSERT INTO user_templates (user_id, template_name, file_data, uploaded_at) VALUES (?, ?, ?, ?)",
        (user_id, template_name, file_data, now),
    )
    await db.commit()
    return cursor.lastrowid


async def get_user_templates(user_id: int) -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT id, user_id, template_name, uploaded_at FROM user_templates WHERE user_id = ? ORDER BY id",
        (user_id,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_user_template_data(template_id: int, user_id: int) -> bytes | None:
    db = await get_db()
    cursor = await db.execute(
        "SELECT file_data FROM user_templates WHERE id = ? AND user_id = ?",
        (template_id, user_id),
    )
    row = await cursor.fetchone()
    return row["file_data"] if row else None


async def delete_user_template(template_id: int, user_id: int) -> bool:
    db = await get_db()
    cursor = await db.execute(
        "DELETE FROM user_templates WHERE id = ? AND user_id = ?",
        (template_id, user_id),
    )
    await db.commit()
    return cursor.rowcount > 0


# --- User products ---

async def create_user_product(user_id: int, product_label: str, keyword: str,
                               template_id: int | None, output_pattern: str,
                               options: list[dict]) -> int:
    db = await get_db()
    now = datetime.utcnow().isoformat()
    cursor = await db.execute(
        """INSERT INTO user_products (user_id, product_label, coupang_product_keyword,
           template_id, output_filename_pattern, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user_id, product_label, keyword, template_id, output_pattern, now),
    )
    product_id = cursor.lastrowid
    for opt in options:
        await db.execute(
            """INSERT INTO user_product_options
               (user_product_id, coupang_option_keyword, vendor_option_name,
                template_target_cell, unit_price_krw, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (product_id, opt["coupang_option_keyword"], opt["vendor_option_name"],
             opt.get("template_target_cell"),
             int(opt.get("unit_price_krw") or 0), now),
        )
    await db.commit()
    return product_id


async def get_user_products(user_id: int) -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM user_products WHERE user_id = ? AND is_active = 1 ORDER BY id",
        (user_id,),
    )
    products = [dict(r) for r in await cursor.fetchall()]
    for p in products:
        cursor = await db.execute(
            "SELECT * FROM user_product_options WHERE user_product_id = ? ORDER BY id",
            (p["id"],),
        )
        p["options"] = [dict(r) for r in await cursor.fetchall()]
    return products


async def update_user_product(product_id: int, user_id: int, product_label: str,
                               keyword: str, template_id: int | None,
                               output_pattern: str, options: list[dict]):
    db = await get_db()
    now = datetime.utcnow().isoformat()
    await db.execute(
        """UPDATE user_products SET product_label = ?, coupang_product_keyword = ?,
           template_id = ?, output_filename_pattern = ? WHERE id = ? AND user_id = ?""",
        (product_label, keyword, template_id, output_pattern, product_id, user_id),
    )
    await db.execute("DELETE FROM user_product_options WHERE user_product_id = ?", (product_id,))
    for opt in options:
        await db.execute(
            """INSERT INTO user_product_options
               (user_product_id, coupang_option_keyword, vendor_option_name,
                template_target_cell, unit_price_krw, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (product_id, opt["coupang_option_keyword"], opt["vendor_option_name"],
             opt.get("template_target_cell"),
             int(opt.get("unit_price_krw") or 0), now),
        )
    await db.commit()


async def delete_user_product(product_id: int, user_id: int) -> bool:
    db = await get_db()
    cursor = await db.execute(
        "UPDATE user_products SET is_active = 0 WHERE id = ? AND user_id = ?",
        (product_id, user_id),
    )
    await db.commit()
    return cursor.rowcount > 0


# --- Plans / Subscriptions / Billing / Usage ---

async def list_plans() -> list[dict]:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM plans WHERE active = 1 ORDER BY price_krw")
    return [dict(r) for r in await cursor.fetchall()]


async def get_plan(code: str) -> dict | None:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM plans WHERE code = ?", (code,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_subscription(user_id: int) -> dict | None:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM subscriptions WHERE user_id = ?", (user_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def upsert_subscription(
    user_id: int,
    plan_code: str,
    status: str = "active",
    billing_key: str | None = None,
    customer_key: str | None = None,
    current_period_start: str | None = None,
    current_period_end: str | None = None,
    cancel_at_period_end: int = 0,
):
    db = await get_db()
    now = datetime.utcnow().isoformat()
    await db.execute(
        """INSERT INTO subscriptions
           (user_id, plan_code, status, billing_key, customer_key,
            current_period_start, current_period_end, cancel_at_period_end,
            created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET
             plan_code = excluded.plan_code,
             status = excluded.status,
             billing_key = COALESCE(excluded.billing_key, subscriptions.billing_key),
             customer_key = COALESCE(excluded.customer_key, subscriptions.customer_key),
             current_period_start = COALESCE(excluded.current_period_start, subscriptions.current_period_start),
             current_period_end = COALESCE(excluded.current_period_end, subscriptions.current_period_end),
             cancel_at_period_end = excluded.cancel_at_period_end,
             updated_at = excluded.updated_at""",
        (user_id, plan_code, status, billing_key, customer_key,
         current_period_start, current_period_end, cancel_at_period_end, now, now),
    )
    await db.commit()


async def set_subscription_cancel(user_id: int, cancel: bool):
    db = await get_db()
    now = datetime.utcnow().isoformat()
    await db.execute(
        "UPDATE subscriptions SET cancel_at_period_end = ?, updated_at = ? WHERE user_id = ?",
        (1 if cancel else 0, now, user_id),
    )
    await db.commit()


async def list_due_subscriptions(now_iso: str) -> list[dict]:
    """Pro subs whose period has ended."""
    db = await get_db()
    cursor = await db.execute(
        """SELECT * FROM subscriptions
           WHERE plan_code = 'pro' AND status = 'active'
             AND current_period_end IS NOT NULL
             AND current_period_end <= ?""",
        (now_iso,),
    )
    return [dict(r) for r in await cursor.fetchall()]


async def add_billing_event(
    user_id: int,
    event_type: str,
    amount_krw: int = 0,
    toss_payment_key: str | None = None,
    toss_order_id: str | None = None,
    raw: dict | None = None,
):
    db = await get_db()
    now = datetime.utcnow().isoformat()
    await db.execute(
        """INSERT INTO billing_events
           (user_id, type, amount_krw, toss_payment_key, toss_order_id, raw_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (user_id, event_type, amount_krw, toss_payment_key, toss_order_id,
         json.dumps(raw or {}, ensure_ascii=False), now),
    )
    await db.commit()


async def log_usage(user_id: int, event_type: str, product_label: str, order_count: int):
    db = await get_db()
    now = datetime.utcnow()
    await db.execute(
        """INSERT INTO usage_logs
           (user_id, event_type, product_label, order_count, ym, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user_id, event_type, product_label, order_count,
         now.strftime("%Y-%m"), now.isoformat()),
    )
    await db.commit()


async def get_monthly_usage(user_id: int, ym: str | None = None) -> dict:
    if ym is None:
        ym = datetime.utcnow().strftime("%Y-%m")
    db = await get_db()
    cursor = await db.execute(
        """SELECT COALESCE(SUM(order_count), 0) as total_orders,
                  COUNT(*) as event_count
           FROM usage_logs WHERE user_id = ? AND ym = ?""",
        (user_id, ym),
    )
    row = await cursor.fetchone()
    return {"ym": ym, "order_count": row["total_orders"] or 0, "event_count": row["event_count"] or 0}


# --- Option sales ---

async def log_option_sales(user_id: int, product_label: str, options: list[dict], ymd: str | None = None):
    """Log option sales.

    options accepts either aggregate rows:
      {coupang_option_keyword, vendor_option_name, quantity}

    or order-aware rows:
      {coupang_option_keyword, vendor_option_name, quantity,
       orders: [{order_id, quantity}, ...]}

    When order_id is present, the unique index prevents the same order line from
    being counted again if a user regenerates the same order file.
    """
    if not options:
        return
    db = await get_db()
    now = datetime.now(KST)
    ymd = ymd or now.strftime("%Y-%m-%d")
    ym = ymd[:7]
    created_at = now.isoformat()
    for o in options:
        option_name = str(o.get("coupang_option_keyword") or "")
        vendor_name = str(o.get("vendor_option_name") or "")
        order_entries = o.get("orders") or []
        if order_entries:
            order_quantities: dict[tuple[str, str], int] = {}
            anonymous_quantity = 0
            for entry in order_entries:
                if isinstance(entry, dict):
                    external_order_id = str(
                        entry.get("order_id")
                        or entry.get("external_order_id")
                        or entry.get("order_no")
                        or ""
                    ).strip()
                    try:
                        quantity = int(float(entry.get("quantity") or 0))
                    except (TypeError, ValueError):
                        quantity = 0
                    entry_ymd = str(entry.get("ymd") or ymd).strip()[:10] or ymd
                else:
                    external_order_id = str(entry or "").strip()
                    quantity = 1
                    entry_ymd = ymd
                if quantity <= 0:
                    continue
                if external_order_id:
                    key = (external_order_id, entry_ymd)
                    order_quantities[key] = order_quantities.get(key, 0) + quantity
                else:
                    anonymous_quantity += quantity

            for (external_order_id, entry_ymd), quantity in order_quantities.items():
                await db.execute(
                    """INSERT OR IGNORE INTO option_sales
                       (user_id, product_label, coupang_option_keyword, vendor_option_name,
                        quantity, external_order_id, ymd, ym, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        user_id,
                        product_label,
                        option_name,
                        vendor_name,
                        quantity,
                        external_order_id,
                        entry_ymd,
                        entry_ymd[:7],
                        created_at,
                    ),
                )

            if anonymous_quantity <= 0:
                continue
            await db.execute(
                """INSERT INTO option_sales
                   (user_id, product_label, coupang_option_keyword, vendor_option_name,
                    quantity, external_order_id, ymd, ym, created_at)
                   VALUES (?, ?, ?, ?, ?, '', ?, ?, ?)""",
                (
                    user_id,
                    product_label,
                    option_name,
                    vendor_name,
                    anonymous_quantity,
                    ymd,
                    ym,
                    created_at,
                ),
            )
            continue

        if not o.get("quantity"):
            continue
        await db.execute(
            """INSERT INTO option_sales
               (user_id, product_label, coupang_option_keyword, vendor_option_name,
                quantity, external_order_id, ymd, ym, created_at)
               VALUES (?, ?, ?, ?, ?, '', ?, ?, ?)""",
            (user_id, product_label, option_name,
             vendor_name, int(o["quantity"]),
             ymd, ym, created_at),
        )
    await db.commit()


def _compact_option_text(value: object, *, strip_groups: bool = False) -> str:
    text = "" if value is None else str(value).lower()
    text = text.replace("㎏", "kg")
    text = text.replace("키로", "kg")
    if strip_groups:
        text = re.sub(r"\[[^\]]*\]", "", text)
        text = re.sub(r"\([^)]*\)", "", text)
    return re.sub(r"[^0-9a-z가-힣.]+", "", text)


def _option_match_keys(*values: object) -> set[str]:
    raw = " ".join(str(v or "") for v in values if v is not None)
    keys = {
        _compact_option_text(raw),
        _compact_option_text(raw, strip_groups=True),
    }
    for value in values:
        if value is None:
            continue
        keys.add(_compact_option_text(value))
        keys.add(_compact_option_text(value, strip_groups=True))
    return {key for key in keys if key}


def _extract_weight_key(*values: object) -> str:
    raw = " ".join(str(v or "") for v in values)
    match = re.search(r"(\d+(?:\.\d+)?)\s*(kg|g|㎏)", raw, flags=re.IGNORECASE)
    if not match:
        return ""
    unit = "kg" if match.group(2).lower() in ("kg", "㎏") else "g"
    return f"{match.group(1).rstrip('0').rstrip('.')}{unit}"


def _product_family_key(*values: object) -> str:
    text = "".join(str(v or "") for v in values)
    for family, tokens in (
        ("myeongi", ("명이나물", "명이")),
        ("kolrabi", ("콜라비",)),
        ("chamoe_altteul", ("알뜰참외", "알뜰 참외", "알뜰과", "혼합과", "랜덤과")),
        ("chamoe", ("참외", "성주참외")),
        ("tomato", ("토마토", "대저")),
        ("dureup", ("두릅", "땅두릅")),
        ("goguma", ("고구마", "꿀고구마")),
        ("gaegeolmu", ("게걸무",)),
    ):
        if any(token in text for token in tokens):
            return family
    return ""


def _chamoe_altteul_kind(*values: object) -> str:
    text = "".join(str(v or "") for v in values)
    if "랜덤과" in text or "혼합과" in text:
        return "random"
    if "대중과" in text:
        return "daejung"
    return ""


def _option_trait_map(family: str, *values: object) -> dict[str, str]:
    text = " ".join(str(v or "") for v in values)
    compact = _compact_option_text(text)
    traits: dict[str, str] = {}

    if family in ("chamoe", "chamoe_altteul"):
        for grade in ("중소과", "로얄과", "혼합과", "랜덤과", "대중과"):
            if grade in text:
                traits["grade"] = grade
                break
        if family == "chamoe_altteul":
            kind = _chamoe_altteul_kind(*values)
            if kind:
                traits["altteul_kind"] = kind

    elif family == "tomato":
        lower_text = text.lower()
        if "대과" in text or re.search(r"(?<![a-z])2?l(?![a-z])", lower_text):
            traits["size"] = "대과"
        elif "중과" in text or re.search(r"(?<![a-z])m(?![a-z])", lower_text):
            traits["size"] = "중과"
        elif "로얄과" in text or re.search(r"(?<![a-z])s(?:~|-)?2?s?(?![a-z])", lower_text):
            traits["size"] = "로얄과"
        if "짭짤이" in text:
            traits["kind"] = "짭짤이"
        elif "특품" in text or "고품위" in text:
            traits["kind"] = "특품"

    elif family == "goguma":
        for grade in ("중상", "특상", "한입"):
            if grade in text:
                traits["grade"] = grade
                break
        if "grade" not in traits and ("(대)" in text or " 대" in text or compact.endswith("대")):
            traits["grade"] = "대"

    elif family == "dureup":
        for use in ("튀김용", "장아찌용", "특품"):
            if use in text:
                traits["use"] = use
                break

    return traits


def _option_trait_conflict(sale_traits: dict[str, str], supplier_traits: dict[str, str]) -> bool:
    for key in sale_traits.keys() & supplier_traits.keys():
        if sale_traits[key] != supplier_traits[key]:
            return True
    return False


def _manual_unit_price_match(
    sale_product_label: str,
    sale_coupang_option: str,
    sale_vendor_option: str,
) -> tuple[int, str, str]:
    raw = " ".join(
        str(value or "")
        for value in (sale_product_label, sale_coupang_option, sale_vendor_option)
    ).lower()
    compact = _compact_option_text(raw)
    family = _product_family_key(sale_product_label, sale_coupang_option, sale_vendor_option)

    if family == "goguma":
        goguma_prices = {
            ("10kg", "대"): 16000,
            ("10kg", "중상"): 23000,
            ("10kg", "특상"): 25000,
            ("10kg", "한입"): 14000,
            ("5kg", "대"): 8000,
            ("5kg", "중상"): 12500,
            ("5kg", "특상"): 12500,
            ("5kg", "한입"): 7000,
            ("3kg", "대"): 4800,
            ("3kg", "중상"): 6900,
            ("3kg", "특상"): 7500,
            ("3kg", "한입"): 4200,
            ("2kg", "대"): 3200,
            ("2kg", "중상"): 4600,
            ("2kg", "특상"): 4600,
            ("2kg", "한입"): 2800,
        }
        weight = next((key for key in ("10kg", "5kg", "3kg", "2kg") if key in compact), "")
        grade = ""
        for candidate in ("중상", "특상", "한입"):
            if candidate in raw:
                grade = candidate
                break
        if not grade and ("(대)" in raw or " 대" in raw or raw.endswith("대")):
            grade = "대"
        if weight and grade and (weight, grade) in goguma_prices:
            return goguma_prices[(weight, grade)], "manual_rule", "꿀고구마 기준단가"

    if family == "gaegeolmu":
        if (
            "2병" in raw
            or "2 병" in raw
            or "2개입" in compact
            or "2개" in raw
            or "2 개" in raw
            or "2세트" in raw
            or "2 세트" in raw
        ):
            return 80000, "manual_rule", "게걸무씨앗기름 기준단가"
        if (
            "1병" in raw
            or "1 병" in raw
            or "1개입" in compact
            or "1개" in raw
            or "1 개" in raw
            or "1세트" in raw
            or "1 세트" in raw
        ):
            return 40000, "manual_rule", "게걸무씨앗기름 기준단가"

    if family == "chamoe_altteul" and _chamoe_altteul_kind(
        sale_product_label,
        sale_coupang_option,
        sale_vendor_option,
    ) == "random":
        altteul_random_prices = {
            "2kg": 9500,
            "3kg": 13700,
            "5kg": 21600,
        }
        weight = next((key for key in ("5kg", "3kg", "2kg") if key in compact), "")
        if weight:
            return altteul_random_prices[weight], "manual_rule", "성주참외 알뜰 랜덤과 기준단가"

    if family == "chamoe" and "중소과" in raw:
        chamoe_jbt_small_prices = {
            "1.5kg": 11850,
            "1kg": 8850,
        }
        weight = next((key for key in ("1.5kg", "1kg") if key in compact), "")
        if weight:
            return chamoe_jbt_small_prices[weight], "manual_rule", "성주참외 중소과 기준단가"

    if family == "tomato" and "짭짤이" in raw:
        tomato_jjap_prices = {
            "2.5kg": 17500,
            "1.5kg": 11800,
        }
        weight = next((key for key in ("2.5kg", "1.5kg") if key in compact), "")
        if weight:
            return tomato_jjap_prices[weight], "manual_rule", "대저 짭짤이 기준단가"

    return 0, "", ""


async def save_supplier_price_snapshot(summary: dict) -> None:
    rows = summary.get("rows") or []
    if not rows:
        return

    db = await get_db()
    checked_at = summary.get("checked_at") or datetime.now(KST).isoformat()
    for row in rows:
        supplier_price = int(row.get("supplier_price") or 0)
        if supplier_price <= 0:
            continue
        option_name = str(row.get("option_name") or "")
        supplier_option_name = str(row.get("supplier_option_name") or option_name)
        normalized_key = next(iter(_option_match_keys(option_name, supplier_option_name)), "")
        await db.execute(
            """INSERT INTO supplier_price_snapshots
               (monitor_key, supplier_name, product_name, option_name, supplier_option_name,
                normalized_option_key, supplier_price, checked_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                summary.get("key") or "",
                summary.get("supplier_name") or "",
                summary.get("product_name") or "",
                option_name,
                supplier_option_name,
                normalized_key,
                supplier_price,
                checked_at,
            ),
        )
    await db.commit()


async def latest_supplier_price_snapshots_before_run_date(
    monitor_key: str,
    run_date: str,
) -> list[dict]:
    """Return the latest stored supplier prices before the current run date.

    Margin-defense alerts are based on supplier-site/spreadsheet price movement
    from the previous saved day, not on the static sourcing workbook baseline.
    """
    db = await get_db()
    cursor = await db.execute(
        """SELECT *
           FROM supplier_price_snapshots
           WHERE monitor_key = ?
             AND substr(checked_at, 1, 10) < ?
           ORDER BY checked_at DESC, id DESC""",
        (monitor_key, run_date),
    )
    rows = [dict(row) for row in await cursor.fetchall()]
    seen: set[tuple[str, str]] = set()
    latest: list[dict] = []
    for row in rows:
        key = (
            row.get("option_name") or "",
            row.get("supplier_option_name") or "",
        )
        if key in seen:
            continue
        seen.add(key)
        latest.append(row)
    return latest


async def save_supplier_price_monitor_run(
    monitor_key: str,
    summary: dict | None = None,
    status: str = "ok",
    error_message: str = "",
) -> None:
    db = await get_db()
    checked_at = (summary or {}).get("checked_at") or datetime.now(KST).isoformat()
    run_date = str(checked_at)[:10]
    await db.execute(
        """INSERT INTO supplier_price_monitor_runs
           (run_date, monitor_key, supplier_name, product_name, status,
            total_items, changed_items, blue_count, red_count, same_count,
            output_filename, error_message, checked_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run_date,
            monitor_key,
            (summary or {}).get("supplier_name") or "",
            (summary or {}).get("product_name") or "",
            status,
            int((summary or {}).get("total_items") or 0),
            int((summary or {}).get("changed_items") or 0),
            int((summary or {}).get("blue_count") or 0),
            int((summary or {}).get("red_count") or 0),
            int((summary or {}).get("same_count") or 0),
            (summary or {}).get("output_filename") or "",
            error_message,
            checked_at,
        ),
    )
    await db.commit()
    await cleanup_supplier_price_history()


async def cleanup_supplier_price_history(retention_days: int = SUPPLIER_PRICE_HISTORY_RETENTION_DAYS) -> dict[str, int]:
    """Keep margin-defense comparison history light while covering long holidays."""
    db = await get_db()
    cutoff = (datetime.now(KST) - timedelta(days=retention_days)).isoformat()
    snapshot_cursor = await db.execute(
        "DELETE FROM supplier_price_snapshots WHERE checked_at < ?",
        (cutoff,),
    )
    run_cursor = await db.execute(
        "DELETE FROM supplier_price_monitor_runs WHERE checked_at < ?",
        (cutoff,),
    )
    await db.commit()
    deleted = {
        "supplier_price_snapshots": max(snapshot_cursor.rowcount or 0, 0),
        "supplier_price_monitor_runs": max(run_cursor.rowcount or 0, 0),
    }
    if deleted["supplier_price_snapshots"] or deleted["supplier_price_monitor_runs"]:
        logger.info("Cleaned supplier price history older than %s: %s", cutoff, deleted)
    return deleted


async def list_latest_supplier_price_monitor_runs() -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        """SELECT runs.*
           FROM supplier_price_monitor_runs AS runs
           INNER JOIN (
               SELECT monitor_key, MAX(id) AS latest_id
               FROM supplier_price_monitor_runs
               GROUP BY monitor_key
           ) AS latest
             ON runs.monitor_key = latest.monitor_key
            AND runs.id = latest.latest_id
           ORDER BY runs.checked_at DESC, runs.id DESC"""
    )
    return [dict(row) for row in await cursor.fetchall()]


async def supplier_price_snapshot_count(monitor_key: str | None = None) -> int:
    db = await get_db()
    if monitor_key:
        cursor = await db.execute(
            "SELECT COUNT(*) AS cnt FROM supplier_price_snapshots WHERE monitor_key = ?",
            (monitor_key,),
        )
    else:
        cursor = await db.execute("SELECT COUNT(*) AS cnt FROM supplier_price_snapshots")
    row = await cursor.fetchone()
    return int(row["cnt"] or 0)


async def supplier_price_snapshot_latest_date(monitor_key: str) -> str:
    db = await get_db()
    cursor = await db.execute(
        "SELECT substr(MAX(checked_at), 1, 10) AS latest_date FROM supplier_price_snapshots WHERE monitor_key = ?",
        (monitor_key,),
    )
    row = await cursor.fetchone()
    return str(row["latest_date"] or "")


async def _latest_supplier_price_rows() -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        """SELECT *
           FROM supplier_price_snapshots
           ORDER BY checked_at DESC, id DESC
           LIMIT 1000"""
    )
    rows = [dict(r) for r in await cursor.fetchall()]
    seen: set[tuple[str, str, str]] = set()
    unique_rows: list[dict] = []
    for row in rows:
        key = (
            row.get("monitor_key") or "",
            row.get("option_name") or "",
            row.get("supplier_option_name") or "",
        )
        if key in seen:
            continue
        seen.add(key)
        unique_rows.append(row)
    return unique_rows


def _supplier_price_match(
    sale_product_label: str,
    sale_coupang_option: str,
    sale_vendor_option: str,
    supplier_rows: list[dict],
) -> tuple[int, str, str]:
    sale_values = (sale_product_label, sale_coupang_option, sale_vendor_option)
    sale_keys = _option_match_keys(*sale_values)
    sale_weight = _extract_weight_key(*sale_values)
    sale_family = _product_family_key(*sale_values)
    sale_altteul_kind = _chamoe_altteul_kind(*sale_values)
    sale_traits = _option_trait_map(sale_family, *sale_values)

    best: tuple[int, int, str, str] = (0, 0, "", "")
    for row in supplier_rows:
        supplier_values = (
            row.get("product_name") or "",
            row.get("option_name") or "",
            row.get("supplier_option_name") or "",
        )
        supplier_keys = _option_match_keys(*supplier_values)
        supplier_weight = _extract_weight_key(*supplier_values)
        supplier_family = _product_family_key(*supplier_values)
        supplier_altteul_kind = _chamoe_altteul_kind(*supplier_values)
        supplier_traits = _option_trait_map(supplier_family, *supplier_values)

        score = 0
        if sale_family and supplier_family and sale_family != supplier_family:
            score = 0
        elif _option_trait_conflict(sale_traits, supplier_traits):
            score = 0
        elif (
            sale_family == "chamoe_altteul"
            and sale_altteul_kind
            and supplier_altteul_kind
            and sale_altteul_kind != supplier_altteul_kind
        ):
            score = 0
        elif sale_weight and supplier_weight and sale_family and sale_family == supplier_family:
            # 같은 상품군에 kg/g 옵션이 있으면 상품명 공통어보다 무게 일치를 우선한다.
            score = 130 if sale_weight == supplier_weight else 0
        elif sale_keys & supplier_keys:
            score = 100
        elif any(a and b and (a in b or b in a) for a in sale_keys for b in supplier_keys):
            score = 80
        elif sale_weight and sale_weight == supplier_weight and sale_family and sale_family == supplier_family:
            score = 65

        supplier_price = int(row.get("supplier_price") or 0)
        if score and supplier_price > 0 and score > best[0]:
            label = row.get("supplier_option_name") or row.get("option_name") or ""
            best = (score, supplier_price, "margin_defense", label)

    return best[1], best[2], best[3]


async def sales_summary(user_id: int, date_from: str, date_to: str, group_by: str = "option") -> list[dict]:
    db = await get_db()
    if group_by == "day":
        sql = """SELECT ymd, SUM(quantity) as total_qty
                 FROM option_sales
                 WHERE user_id = ? AND ymd >= ? AND ymd <= ?
                 GROUP BY ymd ORDER BY ymd"""
    elif group_by == "product":
        sql = """SELECT product_label, SUM(quantity) as total_qty
                 FROM option_sales
                 WHERE user_id = ? AND ymd >= ? AND ymd <= ?
                 GROUP BY product_label ORDER BY total_qty DESC"""
    else:  # option
        sql = """SELECT product_label, coupang_option_keyword, vendor_option_name,
                        SUM(quantity) as total_qty
                 FROM option_sales
                 WHERE user_id = ? AND ymd >= ? AND ymd <= ?
                 GROUP BY product_label, coupang_option_keyword, vendor_option_name
                 ORDER BY total_qty DESC"""
    cursor = await db.execute(sql, (user_id, date_from, date_to))
    return [dict(r) for r in await cursor.fetchall()]


async def daily_settlement_cards(user_id: int, ymd: str) -> list[dict]:
    """지정일(ymd)에 판매된 옵션을 product 카드별로 집계 + 단가 기반 정산비용 계산.

    반환: [
      {
        product_label: str,
        total_qty: int,
        total_settlement_krw: int,
        options: [
          {coupang_option_keyword, vendor_option_name, quantity,
           unit_price_krw, settlement_krw}
        ]
      }
    ]
    """
    db = await get_db()
    # option_sales를 product_label + option 단위로 집계한 뒤,
    # 마진방어 공급가를 우선 적용하고, 없으면 상품 설정 단가를 사용한다.
    sql = """
        SELECT s.product_label,
               s.coupang_option_keyword,
               s.vendor_option_name,
               SUM(s.quantity) AS quantity,
               COALESCE(MAX(o.unit_price_krw), 0) AS unit_price_krw
        FROM option_sales s
        LEFT JOIN user_products p
          ON p.user_id = ?
         AND p.is_active = 1
         AND p.product_label = s.product_label
        LEFT JOIN user_product_options o
          ON o.user_product_id = p.id
         AND o.coupang_option_keyword = s.coupang_option_keyword
        WHERE s.user_id = ? AND s.ymd = ?
        GROUP BY s.product_label, s.coupang_option_keyword, s.vendor_option_name
        ORDER BY s.product_label, quantity DESC
    """
    cursor = await db.execute(sql, (user_id, user_id, ymd))
    rows = [dict(r) for r in await cursor.fetchall()]
    supplier_rows = await _latest_supplier_price_rows()

    cards: dict[str, dict] = {}
    for r in rows:
        label = r["product_label"] or "-"
        qty = int(r["quantity"] or 0)
        supplier_unit, unit_source, supplier_label = _supplier_price_match(
            label,
            r["coupang_option_keyword"] or "",
            r["vendor_option_name"] or "",
            supplier_rows,
        )
        if supplier_unit:
            unit = supplier_unit
        else:
            unit = int(r["unit_price_krw"] or 0)
            unit_source = "product_setting" if unit else "missing"
            supplier_label = ""
            if not unit:
                manual_unit, manual_source, manual_label = _manual_unit_price_match(
                    label,
                    r["coupang_option_keyword"] or "",
                    r["vendor_option_name"] or "",
                )
                if manual_unit:
                    unit = manual_unit
                    unit_source = manual_source
                    supplier_label = manual_label
        settlement = unit * qty
        card = cards.setdefault(label, {
            "product_label": label,
            "total_qty": 0,
            "total_settlement_krw": 0,
            "options": [],
        })
        card["total_qty"] += qty
        card["total_settlement_krw"] += settlement
        card["options"].append({
            "coupang_option_keyword": r["coupang_option_keyword"],
            "vendor_option_name": r["vendor_option_name"] or "",
            "quantity": qty,
            "unit_price_krw": unit,
            "unit_price_source": unit_source,
            "supplier_price_option_name": supplier_label,
            "settlement_krw": settlement,
        })
    # 카드는 매출 내림차순
    return sorted(cards.values(), key=lambda c: c["total_settlement_krw"], reverse=True)


async def _replace_daily_settlement_snapshot_from_cards(user_id: int, ymd: str, cards: list[dict]) -> None:
    db = await get_db()
    ym = ymd[:7]
    snapshot_at = datetime.now(KST).isoformat()
    await db.execute(
        "DELETE FROM daily_settlement_snapshots WHERE user_id = ? AND ymd = ?",
        (user_id, ymd),
    )
    for card in cards:
        for option in card.get("options", []):
            await db.execute(
                """INSERT INTO daily_settlement_snapshots
                   (user_id, product_label, coupang_option_keyword, vendor_option_name,
                    quantity, unit_price_krw, unit_price_source, supplier_price_option_name,
                    settlement_krw, ymd, ym, logic_version, snapshot_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id,
                    card.get("product_label") or "-",
                    option.get("coupang_option_keyword") or "",
                    option.get("vendor_option_name") or "",
                    int(option.get("quantity") or 0),
                    int(option.get("unit_price_krw") or 0),
                    option.get("unit_price_source") or "missing",
                    option.get("supplier_price_option_name") or "",
                    int(option.get("settlement_krw") or 0),
                    ymd,
                    ym,
                    SETTLEMENT_LOGIC_VERSION,
                    snapshot_at,
                ),
            )
    await db.commit()


async def _load_daily_settlement_snapshot_cards(user_id: int, ymd: str) -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        """SELECT product_label, coupang_option_keyword, vendor_option_name,
                  quantity, unit_price_krw, unit_price_source,
                  supplier_price_option_name, settlement_krw, logic_version, snapshot_at
           FROM daily_settlement_snapshots
           WHERE user_id = ? AND ymd = ?
           ORDER BY product_label, settlement_krw DESC, id ASC""",
        (user_id, ymd),
    )
    rows = [dict(r) for r in await cursor.fetchall()]
    cards: dict[str, dict] = {}
    for row in rows:
        label = row["product_label"] or "-"
        card = cards.setdefault(label, {
            "product_label": label,
            "total_qty": 0,
            "total_settlement_krw": 0,
            "snapshot_at": row.get("snapshot_at") or "",
            "logic_version": row.get("logic_version") or "",
            "options": [],
        })
        card["total_qty"] += int(row["quantity"] or 0)
        card["total_settlement_krw"] += int(row["settlement_krw"] or 0)
        card["snapshot_at"] = max(card["snapshot_at"], row.get("snapshot_at") or "")
        card["options"].append({
            "coupang_option_keyword": row["coupang_option_keyword"],
            "vendor_option_name": row.get("vendor_option_name") or "",
            "quantity": int(row["quantity"] or 0),
            "unit_price_krw": int(row["unit_price_krw"] or 0),
            "unit_price_source": row.get("unit_price_source") or "missing",
            "supplier_price_option_name": row.get("supplier_price_option_name") or "",
            "settlement_krw": int(row["settlement_krw"] or 0),
        })
    return sorted(cards.values(), key=lambda c: c["total_settlement_krw"], reverse=True)


def _settlement_snapshot_needs_refresh(cards: list[dict]) -> bool:
    for card in cards:
        if card.get("logic_version") != SETTLEMENT_LOGIC_VERSION:
            return True
        for option in card.get("options", []):
            if int(option.get("quantity") or 0) > 0 and int(option.get("unit_price_krw") or 0) <= 0:
                return True
    return False


async def daily_settlement_snapshot_cards(user_id: int, ymd: str, *, refresh: bool = False) -> list[dict]:
    today_ymd = datetime.now(KST).date().isoformat()
    cached_cards = await _load_daily_settlement_snapshot_cards(user_id, ymd)
    if cached_cards and not refresh and ymd != today_ymd and not _settlement_snapshot_needs_refresh(cached_cards):
        return cached_cards

    cards = await daily_settlement_cards(user_id, ymd)
    await _replace_daily_settlement_snapshot_from_cards(user_id, ymd, cards)
    return await _load_daily_settlement_snapshot_cards(user_id, ymd)


async def settlement_trend(user_id: int, date_from: str, date_to: str) -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        """SELECT DISTINCT ymd
           FROM option_sales
           WHERE user_id = ? AND ymd >= ? AND ymd <= ?
           ORDER BY ymd""",
        (user_id, date_from, date_to),
    )
    ymd_rows = [str(r["ymd"]) for r in await cursor.fetchall()]
    today_ymd = datetime.now(KST).date().isoformat()
    for ymd in ymd_rows:
        await daily_settlement_snapshot_cards(user_id, ymd, refresh=(ymd == today_ymd))

    cursor = await db.execute(
        """SELECT ymd,
                  SUM(quantity) AS total_qty,
                  SUM(settlement_krw) AS total_settlement_krw
           FROM daily_settlement_snapshots
           WHERE user_id = ? AND ymd >= ? AND ymd <= ?
           GROUP BY ymd
           ORDER BY ymd""",
        (user_id, date_from, date_to),
    )
    return [dict(r) for r in await cursor.fetchall()]


async def option_trend(user_id: int, option_keyword: str, date_from: str, date_to: str) -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        """SELECT ymd, SUM(quantity) as total_qty
           FROM option_sales
           WHERE user_id = ? AND coupang_option_keyword = ?
             AND ymd >= ? AND ymd <= ?
           GROUP BY ymd ORDER BY ymd""",
        (user_id, option_keyword, date_from, date_to),
    )
    return [dict(r) for r in await cursor.fetchall()]


async def option_decline_alerts(
    user_id: int,
    date_from: str,
    date_to: str,
    *,
    limit: int = 10,
    decline_days: int = 4,
) -> list[dict]:
    """Top option alerts when quantity decreases every day for decline_days."""
    db = await get_db()
    limit = max(1, min(int(limit or 10), 30))
    decline_days = max(1, min(int(decline_days or 4), 14))

    top_cursor = await db.execute(
        """SELECT product_label, coupang_option_keyword, vendor_option_name,
                  SUM(quantity) AS total_qty
           FROM option_sales
           WHERE user_id = ? AND ymd >= ? AND ymd <= ?
           GROUP BY product_label, coupang_option_keyword, vendor_option_name
           ORDER BY total_qty DESC
           LIMIT ?""",
        (user_id, date_from, date_to, limit),
    )
    top_options = [dict(row) for row in await top_cursor.fetchall()]
    if not top_options:
        return []

    end_date = datetime.strptime(date_to, "%Y-%m-%d").date()
    window_dates = [
        (end_date - timedelta(days=offset)).isoformat()
        for offset in range(decline_days, -1, -1)
    ]
    window_start = window_dates[0]

    alerts: list[dict] = []
    for option in top_options:
        trend_cursor = await db.execute(
            """SELECT ymd, SUM(quantity) AS total_qty
               FROM option_sales
               WHERE user_id = ?
                 AND product_label = ?
                 AND coupang_option_keyword = ?
                 AND COALESCE(vendor_option_name, '') = COALESCE(?, '')
                 AND ymd >= ? AND ymd <= ?
               GROUP BY ymd""",
            (
                user_id,
                option.get("product_label") or "",
                option.get("coupang_option_keyword") or "",
                option.get("vendor_option_name") or "",
                window_start,
                date_to,
            ),
        )
        qty_by_date = {
            str(row["ymd"]): int(row["total_qty"] or 0)
            for row in await trend_cursor.fetchall()
        }
        daily = [
            {"ymd": ymd, "total_qty": qty_by_date.get(ymd, 0)}
            for ymd in window_dates
        ]
        quantities = [item["total_qty"] for item in daily]
        if all(quantities[index] > quantities[index + 1] for index in range(len(quantities) - 1)):
            alerts.append({
                "product_label": option.get("product_label") or "",
                "coupang_option_keyword": option.get("coupang_option_keyword") or "",
                "vendor_option_name": option.get("vendor_option_name") or "",
                "period_total_qty": int(option.get("total_qty") or 0),
                "decline_days": decline_days,
                "daily": daily,
                "drop_qty": quantities[0] - quantities[-1],
                "message": f"{decline_days}일 연속 주문량 감소",
            })

    return sorted(alerts, key=lambda item: item["drop_qty"], reverse=True)
