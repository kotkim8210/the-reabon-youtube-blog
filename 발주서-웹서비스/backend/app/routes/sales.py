"""Sales dashboard routes: per-option sales aggregation."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import verify_token
from app.db import sales_summary, option_trend, daily_settlement_cards, get_subscription, get_plan

router = APIRouter(prefix="/api/sales", tags=["sales"])
KST = timezone(timedelta(hours=9))


def _clamp_range_by_plan(date_from: str, date_to: str, plan: dict | None) -> tuple[str, str]:
    """Free plan limited to last N days (from plan.features_json.sales_history_days)."""
    if not plan:
        return date_from, date_to
    import json
    try:
        flags = json.loads(plan.get("features_json") or "{}")
    except (ValueError, TypeError):
        flags = {}
    limit_days = flags.get("sales_history_days")
    if not limit_days:
        return date_from, date_to
    today = datetime.now(KST).date()
    earliest = today - timedelta(days=int(limit_days))
    earliest_str = earliest.isoformat()
    if date_from < earliest_str:
        date_from = earliest_str
    return date_from, date_to


async def _get_user_plan(user_id: int) -> dict | None:
    sub = await get_subscription(user_id)
    if not sub:
        return await get_plan("free")
    return await get_plan(sub["plan_code"])


@router.get("/summary")
async def summary(
    date_from: str = Query(..., alias="from", description="YYYY-MM-DD"),
    date_to: str = Query(..., alias="to", description="YYYY-MM-DD"),
    group_by: str = Query("option", regex="^(option|product|day)$"),
    user: dict = Depends(verify_token),
):
    try:
        datetime.strptime(date_from, "%Y-%m-%d")
        datetime.strptime(date_to, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="날짜 형식은 YYYY-MM-DD 여야 합니다.")

    if date_from > date_to:
        raise HTTPException(status_code=400, detail="시작일이 종료일보다 늦을 수 없습니다.")

    plan = await _get_user_plan(user["user_id"])
    date_from, date_to = _clamp_range_by_plan(date_from, date_to, plan)

    rows = await sales_summary(user["user_id"], date_from, date_to, group_by)
    return {
        "from": date_from,
        "to": date_to,
        "group_by": group_by,
        "rows": rows,
        "plan_code": plan["code"] if plan else "free",
    }


@router.get("/option-trend")
async def option_trend_endpoint(
    option_keyword: str = Query(...),
    date_from: str = Query(..., alias="from"),
    date_to: str = Query(..., alias="to"),
    user: dict = Depends(verify_token),
):
    plan = await _get_user_plan(user["user_id"])
    date_from, date_to = _clamp_range_by_plan(date_from, date_to, plan)
    rows = await option_trend(user["user_id"], option_keyword, date_from, date_to)
    return {"option_keyword": option_keyword, "from": date_from, "to": date_to, "rows": rows}


@router.get("/cards")
async def settlement_cards(
    date: str | None = Query(None, description="YYYY-MM-DD (기본: 오늘 KST)"),
    user: dict = Depends(verify_token),
):
    """제품별 당일 정산 카드. 옵션별 수량 + 단가 기반 settlement_krw 계산."""
    ymd = date or datetime.now(KST).date().isoformat()
    try:
        datetime.strptime(ymd, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="date 형식은 YYYY-MM-DD 여야 합니다.")
    cards = await daily_settlement_cards(user["user_id"], ymd)
    total = sum(c["total_settlement_krw"] for c in cards)
    total_qty = sum(c["total_qty"] for c in cards)
    return {
        "date": ymd,
        "cards": cards,
        "total_settlement_krw": total,
        "total_qty": total_qty,
    }


@router.get("/presets")
async def presets():
    """Return preset ranges for the dashboard."""
    today = datetime.now(KST).date()
    yesterday = today - timedelta(days=1)
    return {
        "presets": [
            {"label": "어제", "from": yesterday.isoformat(), "to": yesterday.isoformat()},
            {"label": "7일", "from": (today - timedelta(days=7)).isoformat(), "to": today.isoformat()},
            {"label": "한달", "from": (today - timedelta(days=30)).isoformat(), "to": today.isoformat()},
            {"label": "3달", "from": (today - timedelta(days=90)).isoformat(), "to": today.isoformat()},
        ]
    }
