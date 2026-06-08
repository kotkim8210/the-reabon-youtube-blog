"""Persistence helpers for the dedicated order automation dashboard."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.db import get_db

KST = timezone(timedelta(hours=9))


def _now_iso() -> str:
    return datetime.now(KST).isoformat()


async def create_order_batch(
    user_id: int,
    source_key: str,
    batch_name: str,
    template_name: str,
    output_filename: str,
    items: list[dict],
    metadata: dict | None = None,
    processed_at: str | None = None,
) -> dict:
    db = await get_db()
    processed_at = processed_at or _now_iso()
    total_rows = len(items)
    total_quantity = sum(int(item.get("quantity", 0) or 0) for item in items)
    metadata_json = json.dumps(metadata or {}, ensure_ascii=False)

    cursor = await db.execute(
        """
        INSERT INTO order_batches (
            user_id,
            source_key,
            batch_name,
            template_name,
            output_filename,
            total_rows,
            total_quantity,
            metadata_json,
            processed_at,
            sync_status,
            sync_error
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', '')
        """,
        (
            user_id,
            source_key,
            batch_name,
            template_name,
            output_filename,
            total_rows,
            total_quantity,
            metadata_json,
            processed_at,
        ),
    )
    batch_id = cursor.lastrowid
    created_at = _now_iso()

    for item in items:
        await db.execute(
            """
            INSERT INTO order_batch_items (
                batch_id,
                product_name,
                platform_option_name,
                supply_option_name,
                quantity,
                external_order_id,
                receiver_name,
                receiver_phone,
                receiver_address,
                memo,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                item.get("product_name", ""),
                item.get("platform_option_name", ""),
                item.get("supply_option_name", ""),
                int(item.get("quantity", 0) or 0),
                item.get("external_order_id", ""),
                item.get("receiver_name", ""),
                item.get("receiver_phone", ""),
                item.get("receiver_address", ""),
                item.get("memo", ""),
                created_at,
            ),
        )

    await db.commit()

    return {
        "id": batch_id,
        "user_id": user_id,
        "source_key": source_key,
        "batch_name": batch_name,
        "template_name": template_name,
        "output_filename": output_filename,
        "total_rows": total_rows,
        "total_quantity": total_quantity,
        "processed_at": processed_at,
    }


async def update_batch_sync_status(batch_id: int, status: str, error: str = "") -> None:
    db = await get_db()
    await db.execute(
        "UPDATE order_batches SET sync_status = ?, sync_error = ? WHERE id = ?",
        (status, error, batch_id),
    )
    await db.commit()


async def list_order_batches(user_id: int, limit: int = 20) -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT id, batch_name, template_name, output_filename, total_rows,
               total_quantity, processed_at, sync_status, sync_error
        FROM order_batches
        WHERE user_id = ?
        ORDER BY processed_at DESC
        LIMIT ?
        """,
        (user_id, limit),
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_order_automation_overview(user_id: int, date_from: str, date_to: str) -> dict:
    db = await get_db()

    totals_cursor = await db.execute(
        """
        SELECT
            COUNT(*) AS batch_count,
            COALESCE(SUM(total_rows), 0) AS order_count,
            COALESCE(SUM(total_quantity), 0) AS quantity,
            COUNT(DISTINCT substr(processed_at, 1, 10)) AS active_days,
            COALESCE(AVG(total_rows), 0) AS avg_orders_per_batch,
            SUM(CASE WHEN sync_status = 'synced' THEN 1 ELSE 0 END) AS synced_batches,
            SUM(CASE WHEN sync_status = 'error' THEN 1 ELSE 0 END) AS sync_errors,
            SUM(CASE WHEN sync_status = 'pending' THEN 1 ELSE 0 END) AS sync_pending
        FROM order_batches
        WHERE user_id = ?
          AND substr(processed_at, 1, 10) >= ?
          AND substr(processed_at, 1, 10) <= ?
        """,
        (user_id, date_from, date_to),
    )
    totals = dict(await totals_cursor.fetchone())

    unique_options_cursor = await db.execute(
        """
        SELECT COUNT(DISTINCT supply_option_name) AS unique_options
        FROM order_batch_items AS items
        JOIN order_batches AS batches ON batches.id = items.batch_id
        WHERE batches.user_id = ?
          AND substr(batches.processed_at, 1, 10) >= ?
          AND substr(batches.processed_at, 1, 10) <= ?
          AND supply_option_name <> ''
        """,
        (user_id, date_from, date_to),
    )
    unique_options = dict(await unique_options_cursor.fetchone())["unique_options"]

    trend_cursor = await db.execute(
        """
        SELECT substr(processed_at, 1, 10) AS ymd, COALESCE(SUM(total_quantity), 0) AS total_qty
        FROM order_batches
        WHERE user_id = ?
          AND substr(processed_at, 1, 10) >= ?
          AND substr(processed_at, 1, 10) <= ?
        GROUP BY substr(processed_at, 1, 10)
        ORDER BY ymd
        """,
        (user_id, date_from, date_to),
    )
    trend = [dict(row) for row in await trend_cursor.fetchall()]

    top_options_cursor = await db.execute(
        """
        SELECT
            items.product_name,
            items.supply_option_name,
            COALESCE(SUM(items.quantity), 0) AS total_qty
        FROM order_batch_items AS items
        JOIN order_batches AS batches ON batches.id = items.batch_id
        WHERE batches.user_id = ?
          AND substr(batches.processed_at, 1, 10) >= ?
          AND substr(batches.processed_at, 1, 10) <= ?
        GROUP BY items.product_name, items.supply_option_name
        ORDER BY total_qty DESC, items.product_name
        LIMIT 10
        """,
        (user_id, date_from, date_to),
    )
    top_options = [dict(row) for row in await top_options_cursor.fetchall()]

    recent_batches = await list_order_batches(user_id, limit=8)

    return {
        "from": date_from,
        "to": date_to,
        "totals": {
            "batch_count": int(totals["batch_count"] or 0),
            "order_count": int(totals["order_count"] or 0),
            "quantity": int(totals["quantity"] or 0),
            "active_days": int(totals["active_days"] or 0),
            "unique_options": int(unique_options or 0),
            "avg_orders_per_batch": round(float(totals["avg_orders_per_batch"] or 0), 1),
            "synced_batches": int(totals["synced_batches"] or 0),
            "sync_errors": int(totals["sync_errors"] or 0),
            "sync_pending": int(totals["sync_pending"] or 0),
        },
        "trend": trend,
        "top_options": top_options,
        "recent_batches": recent_batches,
    }
