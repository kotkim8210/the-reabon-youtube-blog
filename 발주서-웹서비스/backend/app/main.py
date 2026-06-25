import json
import logging
import re
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.auth import router as auth_router, verify_token, require_pro
from pydantic import BaseModel

from app import config
from app.coupang.client import CoupangApiError
from app.toss.client import TossApiError
from app.processors import (
    batch_tracking_merge,
    chamoe_mixed_order,
    chamdureup_order,
    chamdureup_tracking,
    event_order,
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
    temu_order,
    temu_tracking,
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
from app.routes.automation import router as automation_router
from app.middleware import IPBlockMiddleware
from app import db as database
from app.scheduler import start_scheduler, stop_scheduler, refresh_products, refresh_orders

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


_ADDRESS_HINT_RE = re.compile(
    r"(특별시|광역시|특별자치|"
    r"\b도\s+\S+시|"
    r"\d+동\s*\d+호|"
    r"아파트|빌라|오피스텔|"
    r"\d{2,4}-\d+|"
    r"번길|로\s*\d+)"
)


def _looks_like_address(text: str) -> bool:
    """옵션 문자열이 주소처럼 보이면 True (잘못 들어온 데이터 차단)"""
    if not text:
        return False
    if len(text) > 40:
        return True
    return bool(_ADDRESS_HINT_RE.search(text))


def _filter_options(options: list[dict]) -> list[dict]:
    """주소가 옵션명에 들어간 잘못된 항목을 제거"""
    cleaned = []
    for opt in options:
        kw = str(opt.get("coupang_option_keyword") or "")
        vn = str(opt.get("vendor_option_name") or "")
        if _looks_like_address(kw) or _looks_like_address(vn):
            logger.warning("Skip address-like option entry: kw=%r vn=%r", kw, vn)
            continue
        cleaned.append(opt)
    return cleaned


def _extract_ymd_from_filename(filename: str | None) -> str | None:
    text = filename or ""
    match = re.search(r"(20\d{2})[-_.년 ]?(\d{1,2})[-_.월 ]?(\d{1,2})", text)
    if not match:
        return None
    year, month, day = match.groups()
    try:
        return datetime(int(year), int(month), int(day)).date().isoformat()
    except ValueError:
        return None


async def record_sales_from_process_stats(
    user_id: int,
    stats: dict | None,
    ymd: str | None = None,
) -> None:
    # 판매추적 기능 삭제: 발주 생성 시 더 이상 option_sales 백데이터를 적재하지 않는다.
    return


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


PROXY_TIMEOUT = httpx.Timeout(180.0, connect=20.0)


def _goguma_proxy_enabled() -> bool:
    return bool(config.GOGUMA_API_PROXY_BASE_URL and config.INTERNAL_API_KEY)


def _goguma_proxy_url(operation: str) -> str:
    return f"{config.GOGUMA_API_PROXY_BASE_URL}/api/internal/goguma/{operation}"


def _internal_api_key_guard(
    x_internal_api_key: str | None = Header(default=None, alias="X-Internal-Api-Key"),
) -> None:
    if not config.INTERNAL_API_KEY or x_internal_api_key != config.INTERNAL_API_KEY:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


def _remote_error(response: httpx.Response) -> str:
    try:
        data = response.json()
        if isinstance(data, dict):
            return str(data.get("detail") or data)
        return str(data)
    except Exception:
        return response.text[:500] or f"HTTP {response.status_code}"


def _coupang_api_error_detail(exc: CoupangApiError) -> str:
    if exc.status_code == status.HTTP_403_FORBIDDEN and exc.blocked_ip:
        return (
            "쿠팡 API IP 허용 오류입니다. "
            f"현재 rj-balju 서버 출구 IP {exc.blocked_ip}가 쿠팡 OpenAPI 허용 IP에 없습니다. "
            "쿠팡 Wing OpenAPI IP 허용 목록에 이 IP를 추가하거나, "
            "GOGUMA_API_PROXY_BASE_URL을 허용된 Hermes 프록시로 설정해주세요."
        )
    return f"쿠팡 API 오류({exc.status_code}): {exc.message}"


def _raise_coupang_http_error(exc: CoupangApiError) -> None:
    raise HTTPException(
        status_code=exc.status_code
        if exc.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
        else status.HTTP_502_BAD_GATEWAY,
        detail=_coupang_api_error_detail(exc),
    )


def _toss_api_error_detail(exc: TossApiError) -> str:
    if exc.is_invalid_ip:
        return (
            "토스 API IP 허용 오류입니다. "
            "토스가 현재 rj-balju 서버의 주문 조회 요청을 '허가되지 않은 IP'로 거부했습니다. "
            "토스 쇼핑 파트너스 > 쇼핑 > 연동 관리 > 직접 연동/Open API 키의 IP 주소 목록에도 "
            "이번 서버 출구 IP(화면에 표시된 79.127.159.103)를 추가한 뒤 다시 실행해주세요. "
            f"원문: {exc.error_code or 'INVALID_IP'} - {exc.reason or exc.message}"
        )
    return f"토스 API 오류: {exc.message}"


def _raise_toss_http_error(exc: TossApiError) -> None:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN if exc.is_invalid_ip else status.HTTP_502_BAD_GATEWAY,
        detail=_toss_api_error_detail(exc),
    )


async def _post_proxy_json(operation: str, payload: dict) -> httpx.Response:
    async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
        response = await client.post(
            _goguma_proxy_url(operation),
            json=payload,
            headers={"X-Internal-Api-Key": config.INTERNAL_API_KEY},
        )
    if response.status_code >= 400:
        detail = _remote_error(response)
        if response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN):
            raise HTTPException(status_code=response.status_code, detail=detail)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"프록시 API 처리 실패: {detail}",
        )
    return response


async def _post_proxy_files(
    operation: str,
    files: list[tuple[str, tuple[str, bytes, str]]],
    data: dict[str, str] | None = None,
) -> httpx.Response:
    async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
        response = await client.post(
            _goguma_proxy_url(operation),
            files=files,
            data=data or {},
            headers={"X-Internal-Api-Key": config.INTERNAL_API_KEY},
        )
    if response.status_code >= 400:
        detail = _remote_error(response)
        if response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN):
            raise HTTPException(status_code=response.status_code, detail=detail)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"프록시 API 처리 실패: {detail}",
        )
    return response


async def _record_proxy_sales(user_id: int, response: httpx.Response) -> None:
    # 판매추적 기능 삭제: 프록시 응답의 X-Stats도 판매 로그로 적재하지 않는다.
    return


def _proxy_excel_response(response: httpx.Response) -> Response:
    headers = {"Access-Control-Expose-Headers": "Content-Disposition, X-Stats"}
    for name in ("content-disposition", "x-stats"):
        value = response.headers.get(name)
        if value:
            canonical = "Content-Disposition" if name == "content-disposition" else "X-Stats"
            headers[canonical] = value
    return Response(
        content=response.content,
        media_type=response.headers.get(
            "content-type",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        headers=headers,
    )


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}


@app.post("/api/process/kolrabi-order")
async def process_kolrabi_order(
    delivery_file: UploadFile = File(...),
    user: dict = Depends(verify_token),
):
    try:
        delivery_bytes = await delivery_file.read()
        results = kolrabi_order.process_outputs(delivery_bytes)
        if not results:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="제주다팜 발주로 출력할 콜라비 또는 초당옥수수 주문을 찾지 못했습니다.",
            )

        sales_ymd = _extract_ymd_from_filename(delivery_file.filename)
        for _, _, item_stats in results:
            await record_sales_from_process_stats(user["user_id"], item_stats, ymd=sales_ymd)

        if len(results) == 1:
            output_bytes, filename, stats = results[0]
            response = make_excel_response(output_bytes, filename, stats)
        else:
            kst = timezone(timedelta(hours=9))
            filename = f"제주다팜_발주묶음({datetime.now(kst).strftime('%Y%m%d')}).zip"
            stats = {
                "files": len(results),
                "total": sum(int((item_stats or {}).get("total", 0)) for _, _, item_stats in results),
            }
            response = make_zip_response(
                [(output_bytes, output_name) for output_bytes, output_name, _ in results],
                filename,
                stats,
            )
        logger.info(f"콜라비 발주 처리 완료: {stats}")
        return response
    except HTTPException:
        raise
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
    user: dict = Depends(verify_token),
):
    try:
        delivery_bytes = await delivery_file.read()
        output_bytes, filename, stats = chamdureup_order.process(delivery_bytes)
        await record_sales_from_process_stats(
            user["user_id"], stats, ymd=_extract_ymd_from_filename(delivery_file.filename)
        )
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
    toss_from_date: str = Form(""),
    toss_to_date: str = Form(""),
    include_toss: str = Form(""),
    user: dict = Depends(verify_token),
):
    try:
        delivery_bytes = await delivery_file.read()
        # 토스 쥬얼리 주문(수박·성주참외·신비복숭아·망고수박)을 토스 API로 수집해 함께 발주.
        # 토스 신비복숭아 수집은 이 페이지(명이)로 일원화됨.
        toss_entries = []
        toss_error = ""
        collect_dates = None
        if toss_from_date and toss_to_date:
            collect_dates = (toss_from_date, toss_to_date)
        elif include_toss.lower() == "true":
            today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
            collect_dates = (today, today)
        if collect_dates:
            try:
                toss_entries = await tomato_order.collect_toss_jewelry_orders(*collect_dates)
            except Exception as toss_exc:
                toss_error = str(toss_exc)
                logger.warning(f"토스 쥬얼리 수집 실패(발주는 계속): {toss_exc}")

        output_bytes, filename, stats = myeongi_order.process(
            delivery_bytes, toss_entries=toss_entries
        )
        if toss_error:
            stats = {**(stats or {}), "toss_error": toss_error}
        await record_sales_from_process_stats(
            user["user_id"], stats, ymd=_extract_ymd_from_filename(delivery_file.filename)
        )
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


@app.post("/api/process/event-winner-order")
async def process_event_winner_order(
    winners_file: UploadFile = File(...),
    user: dict = Depends(verify_token),
):
    """라이브 이벤트 당첨자 CSV → 쥬얼리프룻 발주서 (가성비 랜덤과)."""
    try:
        csv_bytes = await winners_file.read()
        output_bytes, filename, stats = event_order.process(csv_bytes)
        logger.info(f"이벤트 당첨자 발주 처리 완료: {stats}")
        return make_excel_response(output_bytes, filename, stats)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("이벤트 당첨자 발주 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@app.post("/api/process/tomato-order")
async def process_tomato_order(
    delivery_file: UploadFile = File(...),
    toss_from_date: str = Form(""),
    toss_to_date: str = Form(""),
    include_toss: str = Form(""),
    user: dict = Depends(verify_token),
):
    try:
        delivery_bytes = await delivery_file.read()
        # 신비복숭아 3·4kg은 쿠팡(DeliveryList) + 토스(API)에서 모두 제이비티 발주로 합친다.
        # (1·2kg은 명이/쥬얼리 메뉴, 수박·성주참외 등 다른 토스 품목은 명이로 일원화)
        toss_peach_entries = []
        toss_peach_error = ""
        collect_dates = None
        if toss_from_date and toss_to_date:
            collect_dates = (toss_from_date, toss_to_date)
        elif include_toss.lower() == "true":
            today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
            collect_dates = (today, today)
        if collect_dates:
            try:
                toss_peach_entries = await tomato_order.collect_toss_peach_orders(
                    *collect_dates, kgs=tomato_order.JBT_PEACH_KGS
                )
            except Exception as toss_exc:
                toss_peach_error = str(toss_exc)
                logger.warning(f"토스 신비복숭아 3·4kg 수집 실패(발주는 계속): {toss_exc}")

        results = tomato_order.process_outputs(delivery_bytes, toss_peach_entries=toss_peach_entries)
        if not results:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="제이비티 발주로 출력할 대저토마토·남해땅두릅·초당옥수수·신비복숭아 주문을 찾지 못했습니다. 수박·성주참외(로얄/중소)는 쥬얼리프룻 메뉴, 알뜰과는 콜라비 메뉴에서 출력됩니다.",
            )
        sales_ymd = _extract_ymd_from_filename(delivery_file.filename)
        for _, _, item_stats in results:
            await record_sales_from_process_stats(user["user_id"], item_stats, ymd=sales_ymd)

        toss_peach_info = {}
        if toss_peach_entries:
            toss_peach_info["toss_peach_orders"] = len(toss_peach_entries)
        if toss_peach_error:
            toss_peach_info["toss_peach_error"] = toss_peach_error

        if len(results) == 1:
            output_bytes, filename, stats = results[0]
            stats = {**(stats or {}), **toss_peach_info}
            response = make_excel_response(output_bytes, filename, stats)
        else:
            kst = timezone(timedelta(hours=9))
            filename = f"아이티소프트_발주묶음({datetime.now(kst).strftime('%Y%m%d')}).zip"
            stats = {
                "files": len(results),
                "total": sum(int((item_stats or {}).get("total", 0)) for _, _, item_stats in results),
                **toss_peach_info,
            }
            response = make_zip_response(
                [(output_bytes, output_name) for output_bytes, output_name, _ in results],
                filename,
                stats,
            )
        logger.info(f"대저토마토 발주 처리 완료: {stats}")
        return response
    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("대저토마토 발주 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@app.post("/api/process/toss-watermelon-order")
async def process_toss_watermelon_order(
    toss_from_date: str = Form(""),
    toss_to_date: str = Form(""),
    alwayz_file: UploadFile | None = File(default=None),
    user: dict = Depends(verify_token),
):
    try:
        alwayz_bytes = await alwayz_file.read() if alwayz_file else None
        # ※ 토스 수집은 명이(쥬얼리) 메뉴로 일원화됨 — 이 메뉴는 올웨이즈 파일만 처리.
        del toss_from_date, toss_to_date
        today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
        from_date = to_date = today
        results = await tomato_order.process_toss_watermelon_order(
            from_date,
            to_date,
            alwayz_bytes=alwayz_bytes,
            collect_toss=False,
        )
        if not results:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="토스/올웨이즈에서 발주 대상 주문을 찾지 못했습니다.",
            )
        sales_ymd = from_date if from_date == to_date else None
        for _, _, item_stats in results:
            await record_sales_from_process_stats(user["user_id"], item_stats, ymd=sales_ymd)

        if len(results) == 1:
            output_bytes, filename, stats = results[0]
            logger.info(f"토스 발주 처리 완료(단일): {stats}")
            return make_excel_response(output_bytes, filename, stats)

        kst = timezone(timedelta(hours=9))
        zip_name = f"토스발주묶음_쥬얼리_제이비티({datetime.now(kst).strftime('%Y%m%d')}).zip"
        zip_stats = {
            "files": len(results),
            "total": sum(int((s or {}).get("total", 0)) for _, _, s in results),
            "filenames": [fn for _, fn, _ in results],
        }
        logger.info(f"토스 발주 처리 완료(묶음): {zip_stats}")
        return make_zip_response(
            [(b, fn) for b, fn, _ in results],
            zip_name,
            zip_stats,
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.exception("토스 발주 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@app.post("/api/process/temu-order")
async def process_temu_order(
    order_file: UploadFile | None = File(None),
    order_text: str = Form(""),
    user: dict = Depends(verify_token),
):
    try:
        if order_file is not None and order_file.filename:
            order_bytes = await order_file.read()
            if not order_bytes:
                raise ValueError("테무 주문 파일이 비어 있습니다.")
            outputs = temu_order.process_file(order_bytes, order_file.filename or "")
            if len(outputs) == 1:
                output_bytes, filename, stats = outputs[0]
                await record_sales_from_process_stats(user["user_id"], stats)
                logger.info(f"테무 파일 발주 처리 완료: {stats}")
                return make_excel_response(output_bytes, filename, stats)

            kst = timezone(timedelta(hours=9))
            filename = f"테무_발주묶음({datetime.now(kst).strftime('%Y%m%d')}).zip"
            stats = temu_order.combine_output_stats(outputs)
            logger.info(f"테무 파일 발주 묶음 처리 완료: {stats}")
            return make_zip_response(
                [(output_bytes, output_name) for output_bytes, output_name, _ in outputs],
                filename,
                stats,
            )

        if not order_text.strip():
            raise ValueError("테무 주문 엑셀 파일을 업로드하거나 주문상세 텍스트를 붙여넣어 주세요.")
        output_bytes, filename, stats = temu_order.process(order_text)
        await record_sales_from_process_stats(user["user_id"], stats)
        logger.info(f"테무 텍스트 발주 처리 완료: {stats}")
        return make_excel_response(output_bytes, filename, stats)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("테무 발주 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@app.post("/api/process/temu-tracking")
async def process_temu_tracking(
    order_export_file: UploadFile = File(...),
    tracking_file: UploadFile = File(...),
    tracking_file2: UploadFile | None = File(None),
    _token: dict = Depends(verify_token),
):
    """테무 주문목록 + 택배 송장파일 → 배송 확인 업로드 템플릿 생성."""
    try:
        order_bytes = await order_export_file.read()
        tracking_files = [(tracking_file.filename or "tracking.xlsx", await tracking_file.read())]
        if tracking_file2 is not None:
            tracking_files.append(
                (tracking_file2.filename or "tracking2.xlsx", await tracking_file2.read())
            )
        output_bytes, filename, stats = temu_tracking.process(
            order_bytes,
            tracking_files,
            order_export_file.filename or "",
        )
        logger.info(f"테무 송장 대량등록 완료: {stats}")
        return make_excel_response(output_bytes, filename, stats)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("테무 송장 대량등록 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@app.post("/api/process/chamoe-mixed-order")
async def process_chamoe_mixed_order(
    delivery_file: UploadFile = File(...),
    user: dict = Depends(verify_token),
):
    try:
        delivery_bytes = await delivery_file.read()
        result = chamoe_mixed_order.process(delivery_bytes)
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="제주다팜 성주참외 알뜰과로 발주할 쿠팡 가정용 혼합과 주문을 찾지 못했습니다.",
            )

        output_bytes, filename, stats = result
        await record_sales_from_process_stats(
            user["user_id"], stats, ymd=_extract_ymd_from_filename(delivery_file.filename)
        )
        logger.info(f"성주참외 알뜰과(제주다팜) 발주 처리 완료: {stats}")
        return make_excel_response(output_bytes, filename, stats)
    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("성주참외 알뜰과(제주다팜) 발주 처리 중 오류")
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
    user: dict = Depends(verify_token),
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

        if _goguma_proxy_enabled():
            proxy_files: list[tuple[str, tuple[str, bytes, str]]] = [
                (
                    "delivery_file",
                    (
                        delivery_file.filename or "delivery.xlsx",
                        delivery_bytes,
                        delivery_file.content_type or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ),
                )
            ]
            if template_bytes is not None and template_file is not None:
                proxy_files.append((
                    "template_file",
                    (
                        template_file.filename or "template.xlsx",
                        template_bytes,
                        template_file.content_type or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ),
                ))
            if alwayz_bytes is not None and alwayz_file is not None:
                proxy_files.append((
                    "alwayz_file",
                    (
                        alwayz_file.filename or "alwayz.xlsx",
                        alwayz_bytes,
                        alwayz_file.content_type or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ),
                ))
            if toss_file_bytes is not None and toss_file is not None:
                proxy_files.append((
                    "toss_file",
                    (
                        toss_file.filename or "toss.xlsx",
                        toss_file_bytes,
                        toss_file.content_type or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ),
                ))
            proxy_response = await _post_proxy_files(
                "goguma-order",
                proxy_files,
                {
                    "toss_from_date": toss_from_date or "",
                    "toss_to_date": toss_to_date or "",
                    "include_toss": include_toss or "",
                },
            )
            await _record_proxy_sales(user["user_id"], proxy_response)
            return _proxy_excel_response(proxy_response)

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
        await record_sales_from_process_stats(
            user["user_id"], stats, ymd=_extract_ymd_from_filename(delivery_file.filename)
        )
        logger.info(f"고구마 발주 처리 완료: {stats}")
        return make_excel_response(output_bytes, filename, stats)
    except TossApiError as e:
        logger.warning("Goguma Toss order collection failed: %s", e.message)
        _raise_toss_http_error(e)
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
    include_toss: bool = False


@app.post("/api/process/goguma-auto")
async def process_goguma_auto(
    req: GogumaAutoRequest,
    user: dict = Depends(verify_token),
):
    try:
        if _goguma_proxy_enabled():
            proxy_response = await _post_proxy_json(
                "goguma-auto",
                {"from_date": req.from_date, "to_date": req.to_date, "include_toss": req.include_toss},
            )
            await _record_proxy_sales(user["user_id"], proxy_response)
            return _proxy_excel_response(proxy_response)

        output_bytes, filename, stats = await goguma_auto.process_from_api(
            req.from_date, req.to_date, include_toss=req.include_toss
        )
        await record_sales_from_process_stats(
            user["user_id"], stats, ymd=req.from_date if req.from_date == req.to_date else None
        )
        logger.info(f"고구마 자동 발주 처리 완료: {stats}")
        return make_excel_response(output_bytes, filename, stats)
    except CoupangApiError as e:
        logger.warning("Goguma Coupang auto failed: %s", e.message)
        _raise_coupang_http_error(e)
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
        try:
            toss_stats = await tomato_tracking.process_toss_watermelon_tracking(tomato_reply_bytes)
        except Exception as toss_error:
            logger.exception("토스 수박 6/7/8kg 송장 자동등록 중 오류")
            toss_stats = {
                "toss_orders": 0,
                "toss_success": 0,
                "toss_fail": 0,
                "toss_skip": 0,
                "toss_error": str(toss_error),
            }
        stats = {**(stats or {}), **toss_stats}
        logger.info(f"대저토마토 송장 처리 완료: {stats}")
        return make_excel_response(output_bytes, filename, stats)
    except Exception as e:
        logger.exception("대저토마토 송장 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@app.post("/api/process/toss-watermelon-tracking")
async def process_toss_watermelon_tracking(
    tomato_reply_file: UploadFile = File(...),
    _token: dict = Depends(verify_token),
):
    try:
        tomato_reply_bytes = await tomato_reply_file.read()
        stats = await tomato_tracking.process_toss_watermelon_tracking(tomato_reply_bytes)
        logger.info(f"토스 수박 6/7/8kg 송장 처리 완료: {stats}")
        return {"status": "ok", **stats}
    except Exception as e:
        logger.exception("토스 수박 6/7/8kg 송장 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@app.post("/api/process/alwayz-jbt-tracking")
async def process_alwayz_jbt_tracking(
    tomato_reply_file: UploadFile = File(...),
    alwayz_file: UploadFile = File(...),
    _token: dict = Depends(verify_token),
):
    """제이비티 회신 파일 운송장번호를 올웨이즈 주문내역 파일에 입력해 반환."""
    try:
        tomato_reply_bytes = await tomato_reply_file.read()
        alwayz_bytes = await alwayz_file.read()
        output_bytes, filename, stats = tomato_tracking.process_alwayz_tracking(
            tomato_reply_bytes, alwayz_bytes
        )
        logger.info(f"올웨이즈 송장 처리 완료: {stats}")
        return make_excel_response(output_bytes, filename, stats)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("올웨이즈 송장 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@app.post("/api/process/toss-excel-tracking")
async def process_toss_excel_tracking(
    tomato_reply_file: UploadFile = File(...),
    toss_export_file: UploadFile = File(...),
    _token: dict = Depends(verify_token),
):
    """거래처 회신 운송장번호를 토스 '엑셀 일괄발송' 파일에 채워 반환."""
    try:
        reply_bytes = await tomato_reply_file.read()
        toss_export_bytes = await toss_export_file.read()
        output_bytes, filename, stats = tomato_tracking.process_toss_excel_tracking(
            reply_bytes, toss_export_bytes
        )
        logger.info(f"토스 엑셀 송장 입력 완료: {stats}")
        return make_excel_response(output_bytes, filename, stats)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("토스 엑셀 송장 입력 중 오류")
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
        if _goguma_proxy_enabled():
            proxy_response = await _post_proxy_files(
                "goguma-tracking-api",
                [(
                    "haedal_file",
                    (
                        haedal_file.filename or "haedal.xlsx",
                        haedal_bytes,
                        haedal_file.content_type or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ),
                )],
            )
            return proxy_response.json()

        result = await goguma_tracking_api.process_tracking_api(haedal_bytes)
        logger.info(
            f"고구마 운송장 API 등록 완료: "
            f"성공={result['success']}, 실패={result['fail']}, 스킵={result['skip']}"
        )
        return result
    except CoupangApiError as e:
        logger.warning("Goguma Coupang tracking failed: %s", e.message)
        _raise_coupang_http_error(e)
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
    user: dict = Depends(verify_token),
):
    """토스 주문만 수집하여 해달 발주서 생성."""
    try:
        if _goguma_proxy_enabled():
            proxy_response = await _post_proxy_json(
                "toss-order",
                {"from_date": req.from_date, "to_date": req.to_date},
            )
            await _record_proxy_sales(user["user_id"], proxy_response)
            return _proxy_excel_response(proxy_response)

        output_bytes, filename, stats = await toss_auto.process_toss_order(
            req.from_date, req.to_date
        )
        await record_sales_from_process_stats(
            user["user_id"], stats, ymd=req.from_date if req.from_date == req.to_date else None
        )
        logger.info(f"토스 발주 처리 완료: {stats}")
        return make_excel_response(output_bytes, filename, stats)
    except TossApiError as e:
        logger.warning("Toss order API failed: %s", e.message)
        _raise_toss_http_error(e)
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
        if _goguma_proxy_enabled():
            proxy_response = await _post_proxy_files(
                "toss-tracking-api",
                [(
                    "haedal_file",
                    (
                        haedal_file.filename or "haedal.xlsx",
                        haedal_bytes,
                        haedal_file.content_type or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ),
                )],
            )
            return proxy_response.json()

        result = await toss_auto.process_toss_tracking(haedal_bytes)
        logger.info(
            f"토스 운송장 등록 완료: "
            f"성공={result['success']}, 실패={result['fail']}, 스킵={result['skip']}"
        )
        return result
    except TossApiError as e:
        logger.warning("Toss tracking API failed: %s", e.message)
        _raise_toss_http_error(e)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.exception("토스 운송장 등록 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@app.post("/api/internal/goguma/goguma-order")
async def internal_process_goguma_order(
    delivery_file: UploadFile = File(...),
    template_file: UploadFile = File(None),
    alwayz_file: UploadFile = File(None),
    toss_file: UploadFile = File(None),
    toss_from_date: str = "",
    toss_to_date: str = "",
    include_toss: str = "",
    _guard: None = Depends(_internal_api_key_guard),
):
    del _guard
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

        toss_entries = []
        if toss_from_date and toss_to_date:
            toss_entries = await goguma_order.collect_toss_orders(toss_from_date, toss_to_date)
        elif include_toss.lower() == "true":
            today = datetime.now(KST).strftime("%Y-%m-%d")
            toss_entries = await goguma_order.collect_toss_orders(today, today)

        output_bytes, filename, stats = goguma_order.process(
            delivery_bytes, template_bytes, alwayz_bytes, toss_entries, toss_file_bytes
        )
        return make_excel_response(output_bytes, filename, stats)
    except TossApiError as e:
        logger.warning("Internal goguma Toss order collection failed: %s", e.message)
        _raise_toss_http_error(e)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("Internal goguma order bridge failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@app.post("/api/internal/goguma/goguma-auto")
async def internal_process_goguma_auto(
    req: GogumaAutoRequest,
    _guard: None = Depends(_internal_api_key_guard),
):
    del _guard
    try:
        output_bytes, filename, stats = await goguma_auto.process_from_api(
            req.from_date, req.to_date, include_toss=req.include_toss
        )
        return make_excel_response(output_bytes, filename, stats)
    except CoupangApiError as e:
        logger.warning("Internal goguma Coupang auto failed: %s", e.message)
        _raise_coupang_http_error(e)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("Internal goguma auto bridge failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@app.post("/api/internal/goguma/goguma-tracking-api")
async def internal_process_goguma_tracking_api(
    haedal_file: UploadFile = File(...),
    _guard: None = Depends(_internal_api_key_guard),
):
    del _guard
    try:
        haedal_bytes = await haedal_file.read()
        return await goguma_tracking_api.process_tracking_api(haedal_bytes)
    except CoupangApiError as e:
        logger.warning("Internal goguma Coupang tracking failed: %s", e.message)
        _raise_coupang_http_error(e)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.exception("Internal goguma tracking bridge failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@app.post("/api/internal/goguma/toss-order")
async def internal_process_toss_order(
    req: TossAutoRequest,
    _guard: None = Depends(_internal_api_key_guard),
):
    del _guard
    try:
        output_bytes, filename, stats = await toss_auto.process_toss_order(
            req.from_date, req.to_date
        )
        return make_excel_response(output_bytes, filename, stats)
    except TossApiError as e:
        logger.warning("Internal toss order API failed: %s", e.message)
        _raise_toss_http_error(e)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("Internal toss order bridge failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@app.post("/api/internal/goguma/toss-tracking-api")
async def internal_process_toss_tracking_api(
    haedal_file: UploadFile = File(...),
    _guard: None = Depends(_internal_api_key_guard),
):
    del _guard
    try:
        haedal_bytes = await haedal_file.read()
        return await toss_auto.process_toss_tracking(haedal_bytes)
    except TossApiError as e:
        logger.warning("Internal toss tracking API failed: %s", e.message)
        _raise_toss_http_error(e)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.exception("Internal toss tracking bridge failed")
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
    user: dict = Depends(verify_token),
):
    try:
        delivery_bytes = await delivery_file.read()
        output_bytes, filename, stats = gaegeolmu_order.process(delivery_bytes)
        await record_sales_from_process_stats(
            user["user_id"], stats, ymd=_extract_ymd_from_filename(delivery_file.filename)
        )
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

    FRONTEND_ROOT = FRONTEND_DIR.resolve()

    # Mount static assets (js, css, images)
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve index.html for all non-API routes (SPA fallback)."""
        if full_path.startswith("api/"):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

        index_path = FRONTEND_ROOT / "index.html"
        try:
            file_path = (FRONTEND_ROOT / full_path).resolve()
            file_path.relative_to(FRONTEND_ROOT)
        except ValueError:
            return FileResponse(str(index_path))

        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(index_path))
