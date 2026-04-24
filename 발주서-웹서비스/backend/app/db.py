"""SQLite database layer for caching Coupang data and storing pricing rules."""

import json
import logging
import aiosqlite
from datetime import datetime, timedelta
from pathlib import Path

from app.config import DATABASE_PATH

logger = logging.getLogger(__name__)

_db: aiosqlite.Connection | None = None


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
            ymd TEXT NOT NULL,
            ym TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_option_sales_user_ymd ON option_sales(user_id, ymd);
        CREATE INDEX IF NOT EXISTS idx_option_sales_user_ym ON option_sales(user_id, ym);
        CREATE INDEX IF NOT EXISTS idx_option_sales_user_label_ymd ON option_sales(user_id, product_label, ymd);

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
    """options: list of {coupang_option_keyword, vendor_option_name, quantity}."""
    if not options:
        return
    db = await get_db()
    now = datetime.utcnow()
    ymd = ymd or now.strftime("%Y-%m-%d")
    ym = ymd[:7]
    created_at = now.isoformat()
    for o in options:
        if not o.get("quantity"):
            continue
        await db.execute(
            """INSERT INTO option_sales
               (user_id, product_label, coupang_option_keyword, vendor_option_name,
                quantity, ymd, ym, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, product_label, o["coupang_option_keyword"],
             o.get("vendor_option_name", ""), int(o["quantity"]),
             ymd, ym, created_at),
        )
    await db.commit()


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
    # 같은 user의 user_product_options에서 단가를 매칭 (키워드 기준, LEFT JOIN).
    sql = """
        SELECT s.product_label,
               s.coupang_option_keyword,
               s.vendor_option_name,
               SUM(s.quantity) AS quantity,
               COALESCE(MAX(o.unit_price_krw), 0) AS unit_price_krw
        FROM option_sales s
        LEFT JOIN user_product_options o
          ON o.coupang_option_keyword = s.coupang_option_keyword
         AND o.user_product_id IN (
             SELECT id FROM user_products WHERE user_id = ? AND is_active = 1
         )
        WHERE s.user_id = ? AND s.ymd = ?
        GROUP BY s.product_label, s.coupang_option_keyword, s.vendor_option_name
        ORDER BY s.product_label, quantity DESC
    """
    cursor = await db.execute(sql, (user_id, user_id, ymd))
    rows = [dict(r) for r in await cursor.fetchall()]

    cards: dict[str, dict] = {}
    for r in rows:
        label = r["product_label"] or "-"
        qty = int(r["quantity"] or 0)
        unit = int(r["unit_price_krw"] or 0)
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
            "settlement_krw": settlement,
        })
    # 카드는 매출 내림차순
    return sorted(cards.values(), key=lambda c: c["total_settlement_krw"], reverse=True)


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
