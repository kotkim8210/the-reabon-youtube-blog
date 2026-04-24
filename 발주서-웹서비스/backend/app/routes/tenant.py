"""Tenant routes: template upload, product config, generic order processing."""

import zipfile
from io import BytesIO
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

from app.auth import verify_token
from app.db import (
    save_user_template, get_user_templates, get_user_template_data, delete_user_template,
    create_user_product, get_user_products, update_user_product, delete_user_product,
    log_option_sales,
)
from app.quota import check_product_limit, check_order_quota, record_order_usage

router = APIRouter(prefix="/api/tenant", tags=["tenant"])


# --- Models ---

class OptionInput(BaseModel):
    coupang_option_keyword: str
    vendor_option_name: str
    template_target_cell: Optional[str] = None
    unit_price_krw: int = 0


class ProductInput(BaseModel):
    product_label: str
    coupang_product_keyword: str
    template_id: Optional[int] = None
    output_filename_pattern: str = "{label}_{date}.xlsx"
    options: list[OptionInput]


# --- Templates ---

@router.post("/templates")
async def upload_template(
    template_file: UploadFile = File(...),
    user: dict = Depends(verify_token),
):
    if not template_file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="엑셀 파일만 업로드 가능합니다.")
    data = await template_file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="파일 크기는 10MB 이하여야 합니다.")
    template_id = await save_user_template(user["user_id"], template_file.filename, data)
    return {"status": "ok", "id": template_id, "name": template_file.filename}


@router.get("/templates")
async def list_templates(user: dict = Depends(verify_token)):
    templates = await get_user_templates(user["user_id"])
    return {"templates": templates}


@router.delete("/templates/{template_id}")
async def remove_template(template_id: int, user: dict = Depends(verify_token)):
    ok = await delete_user_template(template_id, user["user_id"])
    if not ok:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"status": "ok"}


# --- Products ---

@router.post("/products")
async def create_product(req: ProductInput, user: dict = Depends(verify_token)):
    if not req.options:
        raise HTTPException(status_code=400, detail="최소 1개의 옵션이 필요합니다.")
    await check_product_limit(user["user_id"])
    product_id = await create_user_product(
        user["user_id"], req.product_label, req.coupang_product_keyword,
        req.template_id, req.output_filename_pattern,
        [o.model_dump() for o in req.options],
    )
    return {"status": "ok", "id": product_id}


@router.get("/products")
async def list_products(user: dict = Depends(verify_token)):
    products = await get_user_products(user["user_id"])
    return {"products": products}


@router.put("/products/{product_id}")
async def edit_product(product_id: int, req: ProductInput, user: dict = Depends(verify_token)):
    await update_user_product(
        product_id, user["user_id"], req.product_label, req.coupang_product_keyword,
        req.template_id, req.output_filename_pattern,
        [o.model_dump() for o in req.options],
    )
    return {"status": "ok"}


@router.delete("/products/{product_id}")
async def remove_product(product_id: int, user: dict = Depends(verify_token)):
    ok = await delete_user_product(product_id, user["user_id"])
    if not ok:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"status": "ok"}


# --- Analyze DeliveryList (extract unique product/option names) ---

@router.post("/analyze")
async def analyze_delivery(
    delivery_file: UploadFile = File(...),
    user: dict = Depends(verify_token),
):
    """Upload a DeliveryList xlsx → returns unique K-col (product) and L-col (option) values."""
    import openpyxl

    if not delivery_file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="엑셀 파일만 업로드 가능합니다.")

    data = await delivery_file.read()
    try:
        from io import BytesIO
        wb = openpyxl.load_workbook(BytesIO(data), read_only=True, data_only=True)
        ws = wb.active

        products: dict[str, int] = {}   # product_name → count
        options: dict[str, int] = {}    # option_name → count

        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i == 0:
                continue  # skip header
            k_val = str(row[10]).strip() if row[10] else ""
            l_val = str(row[11]).strip() if row[11] else ""
            if k_val and k_val != "None":
                products[k_val] = products.get(k_val, 0) + 1
            if l_val and l_val != "None":
                options[l_val] = options.get(l_val, 0) + 1

        wb.close()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"파일 읽기 실패: {str(e)}")

    # Sort by frequency (most common first)
    sorted_products = sorted(products.items(), key=lambda x: -x[1])
    sorted_options = sorted(options.items(), key=lambda x: -x[1])

    return {
        "products": [{"name": name, "count": cnt} for name, cnt in sorted_products],
        "options": [{"name": name, "count": cnt} for name, cnt in sorted_options],
    }


# --- Process ---

@router.post("/process")
async def process_delivery(
    delivery_file: UploadFile = File(...),
    user: dict = Depends(verify_token),
):
    from app.processors.generic_order import process_generic_order

    delivery_bytes = await delivery_file.read()
    results = await process_generic_order(user["user_id"], delivery_bytes)

    if not results:
        raise HTTPException(status_code=400, detail="매칭되는 상품이 없습니다.")

    # Quota: sum all order counts and verify before finalizing
    total_orders = sum((stats or {}).get("total", 0) for _, _, stats in results)
    await check_order_quota(user["user_id"], total_orders)

    # Record usage + per-option sales
    for _, _, stats in results:
        if not stats:
            continue
        product_label = stats.get("product", "")
        order_count = stats.get("total", 0)
        if order_count > 0:
            await record_order_usage(user["user_id"], product_label, order_count)
        opts = stats.get("options") or []
        if opts:
            await log_option_sales(user["user_id"], product_label, opts)

    if len(results) == 1:
        file_bytes, filename, stats = results[0]
        output = BytesIO(file_bytes)
        encoded_name = quote(filename, safe="")
        headers = {
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
        }
        if stats:
            import json
            headers["X-Stats"] = json.dumps(stats, ensure_ascii=False)
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=headers,
        )

    # Multiple results → zip
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_bytes, filename, _ in results:
            zf.writestr(filename, file_bytes)
    zip_buffer.seek(0)

    from datetime import datetime, timezone, timedelta
    KST = timezone(timedelta(hours=9))
    now = datetime.now(KST)
    zip_name = f"발주서_{now.strftime('%Y%m%d')}.zip"
    encoded_zip = quote(zip_name, safe="")

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_zip}"},
    )
