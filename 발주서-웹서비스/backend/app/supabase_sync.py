"""Best-effort Supabase mirroring for order automation batches."""

from __future__ import annotations

from typing import Iterable

import httpx

from app.config import (
    SUPABASE_BATCHES_TABLE,
    SUPABASE_BATCH_ITEMS_TABLE,
    SUPABASE_SCHEMA,
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_URL,
)


def supabase_enabled() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


def _headers() -> dict[str, str]:
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
        "Content-Profile": SUPABASE_SCHEMA,
    }


def _batch_payload(batch: dict) -> dict:
    return {
        "local_batch_id": batch["id"],
        "user_id": batch["user_id"],
        "source_key": batch["source_key"],
        "batch_name": batch["batch_name"],
        "template_name": batch["template_name"],
        "output_filename": batch["output_filename"],
        "total_rows": batch["total_rows"],
        "total_quantity": batch["total_quantity"],
        "processed_at": batch["processed_at"],
        "sync_version": 1,
    }


def _item_payload(batch: dict, items: Iterable[dict]) -> list[dict]:
    payload: list[dict] = []
    for item in items:
        payload.append(
            {
                "batch_local_id": batch["id"],
                "user_id": batch["user_id"],
                "source_key": batch["source_key"],
                "product_name": item.get("product_name", ""),
                "platform_option_name": item.get("platform_option_name", ""),
                "supply_option_name": item.get("supply_option_name", ""),
                "quantity": int(item.get("quantity", 0) or 0),
                "external_order_id": item.get("external_order_id", ""),
                "receiver_name": item.get("receiver_name", ""),
                "receiver_phone": item.get("receiver_phone", ""),
                "receiver_address": item.get("receiver_address", ""),
                "memo": item.get("memo", ""),
                "processed_at": batch["processed_at"],
            }
        )
    return payload


async def sync_batch_to_supabase(batch: dict, items: list[dict]) -> tuple[bool, str]:
    """Mirror a batch to Supabase if credentials are configured."""
    if not supabase_enabled():
        return True, ""

    if not items:
        return True, ""

    timeout = httpx.Timeout(15.0, connect=5.0)
    headers = _headers()

    async with httpx.AsyncClient(timeout=timeout) as client:
        batch_response = await client.post(
            f"{SUPABASE_URL}/rest/v1/{SUPABASE_BATCHES_TABLE}",
            headers=headers,
            json=[_batch_payload(batch)],
        )
        if batch_response.is_error:
            return False, batch_response.text[:500]

        item_response = await client.post(
            f"{SUPABASE_URL}/rest/v1/{SUPABASE_BATCH_ITEMS_TABLE}",
            headers=headers,
            json=_item_payload(batch, items),
        )
        if item_response.is_error:
            return False, item_response.text[:500]

    return True, ""

