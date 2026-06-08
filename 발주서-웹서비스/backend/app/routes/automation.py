"""Dedicated order automation routes for the Danharu workflow."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from io import BytesIO
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from app.auth import verify_token
from app.order_automation_store import (
    create_order_batch,
    get_order_automation_overview,
    list_order_batches,
    update_batch_sync_status,
)
from app.processors import danharu_order, danharu_tracking, unified_tracking
from app.quota import check_order_quota, record_order_usage
from app.supabase_sync import supabase_enabled, sync_batch_to_supabase

router = APIRouter(prefix="/api/automation", tags=["automation"])
KST = timezone(timedelta(hours=9))


def _stream_excel(output_bytes: bytes, filename: str, exposed_headers: str, extra_headers: dict | None = None) -> StreamingResponse:
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "Access-Control-Expose-Headers": exposed_headers,
    }
    if extra_headers:
        headers.update(extra_headers)
    return StreamingResponse(
        BytesIO(output_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


def _batch_excel_response(
    output_bytes: bytes,
    filename: str,
    stats: dict,
    batch_id: int,
    sync_status: str,
) -> StreamingResponse:
    return _stream_excel(
        output_bytes,
        filename,
        "Content-Disposition, X-Stats, X-Batch-Id, X-Sync-Status",
        {
            "X-Stats": json.dumps(stats, ensure_ascii=False),
            "X-Batch-Id": str(batch_id),
            "X-Sync-Status": sync_status,
        },
    )


def _download_response(output_bytes: bytes, filename: str, stats: dict | None = None) -> StreamingResponse:
    headers: dict[str, str] = {}
    if stats is not None:
        headers["X-Stats"] = json.dumps(stats, ensure_ascii=False)
    return _stream_excel(output_bytes, filename, "Content-Disposition, X-Stats", headers)


@router.get("/overview")
async def overview(
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    user: dict = Depends(verify_token),
):
    today = datetime.now(KST).date()
    date_to = date_to or today.isoformat()
    date_from = date_from or (today - timedelta(days=29)).isoformat()

    try:
        datetime.strptime(date_from, "%Y-%m-%d")
        datetime.strptime(date_to, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="날짜 형식은 YYYY-MM-DD 이어야 합니다.") from exc

    if date_from > date_to:
        raise HTTPException(status_code=400, detail="시작일은 종료일보다 늦을 수 없습니다.")

    data = await get_order_automation_overview(user["user_id"], date_from, date_to)
    data["supabase_enabled"] = supabase_enabled()
    return data


@router.get("/batches")
async def batches(
    limit: int = Query(12, ge=1, le=50),
    user: dict = Depends(verify_token),
):
    rows = await list_order_batches(user["user_id"], limit=limit)
    return {"batches": rows}


@router.post("/process/danharu")
async def process_danharu(
    delivery_file: UploadFile = File(...),
    template_file: UploadFile | None = File(None),
    user: dict = Depends(verify_token),
):
    if not delivery_file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="DeliveryList는 엑셀 파일만 업로드할 수 있습니다.")

    delivery_bytes = await delivery_file.read()
    template_bytes = None
    template_name = "danharu_order_template.xlsx"
    if template_file is not None:
        template_bytes = await template_file.read()
        if template_bytes:
            template_name = template_file.filename or template_name

    try:
        output_bytes, filename, stats, items = danharu_order.process(delivery_bytes, template_bytes)
        await check_order_quota(user["user_id"], stats["total_rows"])
        await record_order_usage(user["user_id"], "단하루_자동발주", stats["total_rows"])

        batch = await create_order_batch(
            user["user_id"],
            "danharu",
            f"단하루 발주 {datetime.now(KST).strftime('%Y-%m-%d %H:%M')}",
            template_name,
            filename,
            items,
            metadata={"stats": stats},
        )

        sync_status = "local_only"
        sync_error = ""
        if supabase_enabled():
            synced, sync_error = await sync_batch_to_supabase(batch, items)
            sync_status = "synced" if synced else "error"
        await update_batch_sync_status(batch["id"], sync_status, sync_error)

        return _batch_excel_response(output_bytes, filename, stats, batch["id"], sync_status)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive API guard
        raise HTTPException(status_code=500, detail=f"발주서 생성 중 오류가 발생했습니다: {exc}") from exc


@router.post("/tracking/danharu")
async def process_danharu_tracking(
    reply_files: list[UploadFile] | None = File(default=None),
    reply_file: UploadFile | None = File(default=None),
    delivery_file: UploadFile = File(...),
    user: dict = Depends(verify_token),
):
    del user

    all_reply_files = list(reply_files or [])
    if reply_file is not None:
        all_reply_files.append(reply_file)

    if not all_reply_files:
        raise HTTPException(status_code=400, detail="단하루 회신 파일을 1개 이상 업로드해 주세요.")
    for f in all_reply_files:
        if not (f.filename or "").endswith((".xlsx", ".xls")):
            raise HTTPException(status_code=400, detail=f"단하루 회신 파일은 엑셀만 업로드할 수 있습니다: {f.filename}")
    if not (delivery_file.filename or "").endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="DeliveryList는 엑셀 파일만 업로드할 수 있습니다.")

    reply_bytes_list = [await f.read() for f in all_reply_files]
    delivery_bytes = await delivery_file.read()

    try:
        output_bytes, filename, stats = danharu_tracking.process(reply_bytes_list, delivery_bytes)
        return _download_response(output_bytes, filename, stats)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive API guard
        raise HTTPException(status_code=500, detail=f"운송장 입력 중 오류가 발생했습니다: {exc}") from exc


@router.post("/tracking/unified")
async def process_unified_tracking(
    reply_files: list[UploadFile] | None = File(default=None),
    reply_file: UploadFile | None = File(default=None),
    delivery_file: UploadFile = File(...),
    user: dict = Depends(verify_token),
):
    del user

    all_reply_files = list(reply_files or [])
    if reply_file is not None:
        all_reply_files.append(reply_file)

    if not all_reply_files:
        raise HTTPException(status_code=400, detail="회신/송장 파일을 1개 이상 업로드해 주세요.")
    for f in all_reply_files:
        if not (f.filename or "").endswith((".xlsx", ".xls")):
            raise HTTPException(status_code=400, detail=f"회신/송장 파일은 엑셀만 업로드할 수 있습니다: {f.filename}")
    if not (delivery_file.filename or "").endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="DeliveryList는 엑셀 파일만 업로드할 수 있습니다.")

    reply_bytes_list = [
        (f.filename or f"reply_{index + 1}.xlsx", await f.read())
        for index, f in enumerate(all_reply_files)
    ]
    delivery_bytes = await delivery_file.read()

    try:
        output_bytes, filename, stats = unified_tracking.process(reply_bytes_list, delivery_bytes)
        return _download_response(output_bytes, filename, stats)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive API guard
        raise HTTPException(status_code=500, detail=f"통합 운송장 입력 중 오류가 발생했습니다: {exc}") from exc
