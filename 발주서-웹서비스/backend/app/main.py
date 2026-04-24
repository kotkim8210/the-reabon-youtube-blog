import json
import logging
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.auth import router as auth_router, verify_token, require_pro
from pydantic import BaseModel

from app.processors import (
    batch_tracking_merge,
    chamdureup_order,
    chamdureup_tracking,
    gaegeolmu_order,
    gaegeolmu_tracking,
    goguma_auto,
    goguma_order,
    goguma_tracking,
    goguma_tracking_alwayz,
    goguma_tracking_api,
    kolrabi_order,
    myeongi_order,
    myeongi_tracking,
    tomato_order,
    tomato_tracking,
    toss_auto,
    tracking_input,
)
from app.routes.dashboard import router as dashboard_router
from app.routes.products import router as products_router
from app.routes.pricing import router as pricing_router
from app.routes.toss import router as toss_router
from app.routes.admin import router as admin_router
from app.routes.tenant import router as tenant_router
from app.routes.billing import router as billing_router
from app.routes.sales import router as sales_router
from app.routes.automation import router as automation_router
from app.middleware import IPBlockMiddleware
from app import db as database
from app.scheduler import start_scheduler, stop_scheduler, refresh_products, refresh_orders

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await database.init_db()
    start_scheduler()
    # Initial data load
    try:
        await refresh_products()
        await refresh_orders()
    except Exception as e:
        logger.warning(f"Initial data load failed (API keys may not be set): {e}")
    yield
    # Shutdown
    stop_scheduler()
    await database.close_db()


app = FastAPI(title="발주서 웹서비스 API", version="3.0.0", lifespan=lifespan)

# Middleware (order matters: IP block runs first)
app.add_middleware(IPBlockMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(tenant_router)
app.include_router(billing_router)
app.include_router(sales_router)
app.include_router(automation_router)
app.include_router(dashboard_router, dependencies=[Depends(require_pro)])
app.include_router(products_router, dependencies=[Depends(require_pro)])
app.include_router(pricing_router, dependencies=[Depends(require_pro)])
app.include_router(toss_router, dependencies=[Depends(require_pro)])


def make_excel_response(output_bytes: bytes, filename: str, stats: dict = None) -> StreamingResponse:
    """Create a StreamingResponse for an Excel file download."""
    encoded_filename = quote(filename)
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
        "Access-Control-Expose-Headers": "Content-Disposition, X-Stats",
    }
    if stats:
        headers["X-Stats"] = json.dumps(stats, ensure_ascii=True)
    return StreamingResponse(
        BytesIO(output_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


def make_zip_response(
    files: list[tuple[bytes, str]],
    filename: str,
    stats: dict | None = None,
) -> StreamingResponse:
    encoded_filename = quote(filename)
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
        "Access-Control-Expose-Headers": "Content-Disposition, X-Stats",
    }
    if stats:
        headers["X-Stats"] = json.dumps(stats, ensure_ascii=True)

    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for output_bytes, output_name in files:
            zip_file.writestr(output_name, output_bytes)
    zip_buffer.seek(0)

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers=headers,
    )


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}


@app.post("/api/process/kolrabi-order")
async def process_kolrabi_order(
    delivery_file: UploadFile = File(...),
    _token: dict = Depends(verify_token),
):
    try:
        delivery_bytes = await delivery_file.read()
        output_bytes, filename, stats = kolrabi_order.process(delivery_bytes)
        logger.info(f"콜라비 발주 처리 완료: {stats}")
        return make_excel_response(output_bytes, filename, stats)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("콜라비 발주 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@app.post("/api/process/chamdureup-order")
async def process_chamdureup_order(
    delivery_file: UploadFile = File(...),
    _token: dict = Depends(verify_token),
):
    try:
        delivery_bytes = await delivery_file.read()
        output_bytes, filename, stats = chamdureup_order.process(delivery_bytes)
        logger.info(f"참두릅 발주 처리 완료: {stats}")
        return make_excel_response(output_bytes, filename, stats)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("참두릅 발주 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@app.post("/api/process/chamdureup-tracking")
async def process_chamdureup_tracking(
    orderlist_file: UploadFile = File(...),
    delivery_file: UploadFile = File(...),
    _token: dict = Depends(verify_token),
):
    try:
        orderlist_bytes = await orderlist_file.read()
        delivery_bytes = await delivery_file.read()
        output_bytes, filename, stats = chamdureup_tracking.process(
            orderlist_bytes, delivery_bytes
        )
        logger.info(f"참두릅 운송장 입력 처리 완료: {stats}")
        return make_excel_response(output_bytes, filename, stats)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("참두릅 운송장 입력 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@app.post("/api/process/myeongi-order")
async def process_myeongi_order(
    delivery_file: UploadFile = File(...),
    _token: dict = Depends(verify_token),
):
    try:
        delivery_bytes = await delivery_file.read()
        output_bytes, filename, stats = myeongi_order.process(delivery_bytes)
        logger.info(f"명이나물 발주 처리 완료: {stats}")
        return make_excel_response(output_bytes, filename, stats)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("명이나물 발주 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@app.post("/api/process/tomato-order")
async def process_tomato_order(
    delivery_file: UploadFile = File(...),
    _token: dict = Depends(verify_token),
):
    try:
        delivery_bytes = await delivery_file.read()
        results = tomato_order.process_outputs(delivery_bytes)
        if len(results) == 1:
            output_bytes, filename, stats = results[0]
            response = make_excel_response(output_bytes, filename, stats)
        else:
            kst = timezone(timedelta(hours=9))
            filename = f"아이티소프트_발주묶음({datetime.now(kst).strftime('%Y%m%d')}).zip"
            stats = {
                "files": len(results),
                "total": sum(int((item_stats or {}).get("total", 0)) for _, _, item_stats in results),
            }
            response = make_zip_response(
                [(output_bytes, output_name) for output_bytes, output_name, _ in results],
                filename,
                stats,
            )
        logger.info(f"대저토마토 발주 처리 완료: {stats}")
        return response
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("대저토마토 발주 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@app.post("/api/process/goguma-order")
async def process_goguma_order(
    delivery_file: UploadFile = File(...),
    template_file: UploadFile = File(None),
    alwayz_file: UploadFile = File(None),
    toss_file: UploadFile = File(None),
    toss_from_date: str = "",
    toss_to_date: str = "",
    include_toss: str = "",
    _token: dict = Depends(verify_token),
):
    try:
        delivery_bytes = await delivery_file.read()
        template_bytes = None
        if template_file is not None:
            template_bytes = await template_file.read()
            if len(template_bytes) == 0:
                template_bytes = None

        alwayz_bytes = None
        if alwayz_file is not None:
            alwayz_bytes = await alwayz_file.read()
            if len(alwayz_bytes) == 0:
                alwayz_bytes = None

        toss_file_bytes = None
        if toss_file is not None:
            toss_file_bytes = await toss_file.read()
            if len(toss_file_bytes) == 0:
                toss_file_bytes = None

        # Fetch Toss orders from API if date range provided
        toss_entries = []
        from datetime import datetime, timezone, timedelta
        KST = timezone(timedelta(hours=9))

        # 날짜 범위가 있으면 해당 기간 수집
        if toss_from_date and toss_to_date:
            toss_entries = await goguma_order.collect_toss_orders(toss_from_date, toss_to_date)
        # 하위호환: include_toss=true면 오늘 수집
        elif include_toss.lower() == "true":
            today = datetime.now(KST).strftime("%Y-%m-%d")
            toss_entries = await goguma_order.collect_toss_orders(today, today)

        output_bytes, filename, stats = goguma_order.process(
            delivery_bytes, template_bytes, alwayz_bytes, toss_entries, toss_file_bytes
        )
        logger.info(f"고구마 발주 처리 완료: {stats}")
        return make_excel_response(output_bytes, filename, stats)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("고구마 발주 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


class GogumaAutoRequest(BaseModel):
    from_date: str
    to_date: str


@app.post("/api/process/goguma-auto")
async def process_goguma_auto(
    req: GogumaAutoRequest,
    _token: dict = Depends(verify_token),
):
    try:
        output_bytes, filename, stats = await goguma_auto.process_from_api(
            req.from_date, req.to_date
        )
        logger.info(f"고구마 자동 발주 처리 완료: {stats}")
        return make_excel_response(output_bytes, filename, stats)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("고구마 자동 발주 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@app.post("/api/process/tracking-input")
async def process_tracking_input(
    orderlist_file: UploadFile = File(...),
    delivery_file: UploadFile = File(...),
    _token: dict = Depends(verify_token),
):
    try:
        orderlist_bytes = await orderlist_file.read()
        delivery_bytes = await delivery_file.read()
        output_bytes, filename, stats = tracking_input.process(
            orderlist_bytes, delivery_bytes
        )
        logger.info(f"운송장 입력 처리 완료: {stats}")
        return make_excel_response(output_bytes, filename, stats)
    except Exception as e:
        logger.exception("운송장 입력 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@app.post("/api/process/myeongi-tracking")
async def process_myeongi_tracking(
    orderlist_file: UploadFile = File(...),
    delivery_file: UploadFile = File(...),
    _token: dict = Depends(verify_token),
):
    try:
        orderlist_bytes = await orderlist_file.read()
        delivery_bytes = await delivery_file.read()
        output_bytes, filename, stats = myeongi_tracking.process(
            orderlist_bytes, delivery_bytes
        )
        logger.info(f"명이나물 운송장 입력 처리 완료: {stats}")
        return make_excel_response(output_bytes, filename, stats)
    except Exception as e:
        logger.exception("명이나물 운송장 입력 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@app.post("/api/process/tomato-tracking")
async def process_tomato_tracking(
    tomato_reply_file: UploadFile = File(...),
    delivery_file: UploadFile = File(...),
    _token: dict = Depends(verify_token),
):
    try:
        tomato_reply_bytes = await tomato_reply_file.read()
        delivery_bytes = await delivery_file.read()
        output_bytes, filename, stats = tomato_tracking.process(
            tomato_reply_bytes, delivery_bytes
        )
        logger.info(f"대저토마토 송장 처리 완료: {stats}")
        return make_excel_response(output_bytes, filename, stats)
    except Exception as e:
        logger.exception("대저토마토 송장 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@app.post("/api/process/goguma-tracking-api")
async def process_goguma_tracking_api_endpoint(
    haedal_file: UploadFile = File(...),
    _token: dict = Depends(verify_token),
):
    """Register 고구마 tracking numbers to Coupang via API."""
    try:
        haedal_bytes = await haedal_file.read()
        result = await goguma_tracking_api.process_tracking_api(haedal_bytes)
        logger.info(
            f"고구마 운송장 API 등록 완료: "
            f"성공={result['success']}, 실패={result['fail']}, 스킵={result['skip']}"
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.exception("고구마 운송장 API 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


class TossAutoRequest(BaseModel):
    from_date: str
    to_date: str


@app.post("/api/process/toss-order")
async def process_toss_order(
    req: TossAutoRequest,
    _token: dict = Depends(verify_token),
):
    """토스 주문만 수집하여 해달 발주서 생성."""
    try:
        output_bytes, filename, stats = await toss_auto.process_toss_order(
            req.from_date, req.to_date
        )
        logger.info(f"토스 발주 처리 완료: {stats}")
        return make_excel_response(output_bytes, filename, stats)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("토스 발주 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@app.post("/api/process/toss-tracking-api")
async def process_toss_tracking_api_endpoint(
    haedal_file: UploadFile = File(...),
    _token: dict = Depends(verify_token),
):
    """토스 운송장번호 자동 등록."""
    try:
        haedal_bytes = await haedal_file.read()
        result = await toss_auto.process_toss_tracking(haedal_bytes)
        logger.info(
            f"토스 운송장 등록 완료: "
            f"성공={result['success']}, 실패={result['fail']}, 스킵={result['skip']}"
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.exception("토스 운송장 등록 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@app.post("/api/process/goguma-tracking-alwayz")
async def process_goguma_tracking_alwayz_endpoint(
    haedal_file: UploadFile = File(...),
    alwayz_file: UploadFile = File(...),
    _token: dict = Depends(verify_token),
):
    try:
        haedal_bytes = await haedal_file.read()
        alwayz_bytes = await alwayz_file.read()
        output_bytes, filename, stats = goguma_tracking_alwayz.process(
            haedal_bytes, alwayz_bytes
        )
        logger.info(f"올웨이즈 송장 입력 완료: {stats}")
        return make_excel_response(output_bytes, filename, stats)
    except Exception as e:
        logger.exception("올웨이즈 송장 입력 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@app.post("/api/process/goguma-tracking")
async def process_goguma_tracking(
    haedal_file: UploadFile = File(...),
    delivery_file: UploadFile = File(...),
    _token: dict = Depends(verify_token),
):
    try:
        haedal_bytes = await haedal_file.read()
        delivery_bytes = await delivery_file.read()
        output_bytes, filename, stats = goguma_tracking.process(
            haedal_bytes, delivery_bytes
        )
        logger.info(f"고구마 송장 처리 완료: {stats}")
        return make_excel_response(output_bytes, filename, stats)
    except Exception as e:
        logger.exception("고구마 송장 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@app.post("/api/process/gaegeolmu-order")
async def process_gaegeolmu_order(
    delivery_file: UploadFile = File(...),
    _token: dict = Depends(verify_token),
):
    try:
        delivery_bytes = await delivery_file.read()
        output_bytes, filename, stats = gaegeolmu_order.process(delivery_bytes)
        logger.info(f"게걸무 발주 처리 완료: {stats}")
        return make_excel_response(output_bytes, filename, stats)
    except Exception as e:
        logger.exception("게걸무 발주 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@app.post("/api/process/gaegeolmu-tracking")
async def process_gaegeolmu_tracking(
    tracking_file: UploadFile = File(...),
    delivery_file: UploadFile = File(...),
    _token: dict = Depends(verify_token),
):
    try:
        tracking_bytes = await tracking_file.read()
        delivery_bytes = await delivery_file.read()
        output_bytes, filename, stats = gaegeolmu_tracking.process(
            tracking_bytes, delivery_bytes
        )
        logger.info(f"게걸무 운송장 입력 완료: {stats}")
        return make_excel_response(output_bytes, filename, stats)
    except Exception as e:
        logger.exception("게걸무 운송장 입력 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@app.post("/api/process/batch-tracking-merge")
async def process_batch_tracking_merge(
    result_files: list[UploadFile] = File(...),
    _token: dict = Depends(verify_token),
):
    try:
        files_to_merge = []
        for result_file in result_files:
            files_to_merge.append(
                (result_file.filename or "result.xlsx", await result_file.read())
            )
        output_bytes, filename, stats = batch_tracking_merge.process(files_to_merge)
        logger.info(f"일괄 운송장 입력 통합 파일 생성 완료: {stats}")
        return make_excel_response(output_bytes, filename, stats)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("일괄 운송장 입력 통합 파일 생성 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"통합 파일 생성 중 오류가 발생했습니다: {str(e)}",
        )


# Serve frontend static files with SPA fallback
FRONTEND_DIR = Path(__file__).parent.parent / "static"
if FRONTEND_DIR.exists():
    from fastapi.responses import FileResponse

    # Mount static assets (js, css, images)
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve index.html for all non-API routes (SPA fallback)."""
        file_path = FRONTEND_DIR / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(FRONTEND_DIR / "index.html"))
