import json
import logging
import re
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime, time as dt_time, timedelta, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import quote, unquote

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.auth import router as auth_router, verify_token, require_pro
from pydantic import BaseModel

from app import config
from app import email_service
from app.coupang.client import CoupangApiError
from app.toss.client import TossApiError
from app.processors import (
    batch_tracking_merge,
    chamdureup_order,
    chamdureup_tracking,
    daangn_order,
    event_order,
    gaegeolmu_order,
    gaegeolmu_tracking,
    goguma_auto,
    goguma_cs,
    goguma_order,
    goguma_tracking,
    goguma_tracking_alwayz,
    goguma_tracking_api,
    kolrabi_order,
    myeongi_order,
    myeongi_tracking,
    issued_orders,
    sabang_fruit,
    temu_order,
    temu_tracking,
    tomato_order,
    tomato_tracking,
    toss_auto,
    tracking_input,
)
from app.sabang import client as sabang_client
from app.sabang.client import SabangApiError
from app.routes.dashboard import router as dashboard_router
from app.routes.products import router as products_router
from app.routes.pricing import router as pricing_router
from app.routes.toss import router as toss_router
from app.routes.admin import router as admin_router
from app.routes.tenant import router as tenant_router
from app.routes.billing import router as billing_router
from app.routes.automation import router as automation_router
from app.routes.rules import router as rules_router
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
    try:
        from app import rules_engine
        await rules_engine.refresh_rules()
    except Exception as e:
        # 캐시 미로드 시 프로세서들은 하드코딩 폴백으로 동작 — 발주 기능은 영향 없음
        logger.warning(f"규칙 엔진 초기 로드 실패(하드코딩 폴백으로 계속): {e}")
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
app.include_router(rules_router)
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


def _today_kst() -> str:
    return datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")


def _exclude_issued_enabled(flag: str) -> bool:
    return (flag or "").strip().lower() not in ("false", "0", "off", "no")


async def _issued_exclusions(section: str, flag: str) -> set[str]:
    """전일 이전 발주서에 포함됐던 주문번호(중복발주 방지). 같은 날 재생성은 막지 않는다."""
    if not _exclude_issued_enabled(flag):
        return set()
    try:
        return await database.issued_order_ids_before(section, _today_kst())
    except Exception:
        logger.exception("발주 이력 조회 실패(제외 없이 계속)")
        return set()


# 발주 마감(KST). 거래처 오전 마감(~10시) 이후 생성한 발주서는 실제 발주가 아니라
# 조회·테스트·미리보기일 가능성이 높아 발주 이력에 기록하지 않는다.
# (마감 후 생성분을 기록하면 다음 영업일 자동제외가 그 주문들을 '이미 발주됨'으로
#  잘못 걸러 조용히 누락됨 — 2026-07-10 토스 백도 최종화 건 실제 발생)
_ISSUE_RECORD_CUTOFF = dt_time(10, 30)


async def _record_issued(section: str, filename: str, *stats_list: dict, extra_ids: list[str] | None = None) -> None:
    """발주서에 실제 기록된 주문번호(stats options[].orders[])를 이력으로 저장.

    발주 마감(10:30 KST) 이후 생성분은 기록하지 않는다 — 같은 날 재생성·추가발주는
    어차피 당일 제외 대상이 아니고, 마감 후 생성을 기록하면 미발주 주문이
    다음 영업일에 침묵 누락된다.
    """
    now_kst = datetime.now(timezone(timedelta(hours=9)))
    if now_kst.time() > _ISSUE_RECORD_CUTOFF:
        logger.info(
            "발주 마감(10:30 KST) 이후 생성 → 발주 이력 미기록: section=%s file=%s (%s)",
            section, filename, now_kst.strftime("%H:%M"),
        )
        return
    try:
        ids = issued_orders.order_ids_from_stats(*stats_list)
        if extra_ids:
            ids = sorted(set(ids) | {i for i in extra_ids if i})
        await database.record_issued_orders(section, ids, filename, _today_kst())
    except Exception:
        logger.exception("발주 이력 기록 실패(발주서는 정상 생성)")


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
    toss_from_date: str = Form(""),
    toss_to_date: str = Form(""),
    include_toss: str = Form(""),
    exclude_issued: str = Form("true"),
    user: dict = Depends(verify_token),
):
    try:
        delivery_bytes = await delivery_file.read()
        issued_excluded = await _issued_exclusions("kolrabi", exclude_issued)
        dup_names: list[str] = []
        delivery_bytes, dup_skipped = issued_orders.filter_delivery_by_issued(
            delivery_bytes, issued_excluded, skipped_names=dup_names
        )
        # 토스 제주다팜 주문(콜라비 + 미니밤호박 1kg + 홍감자)을 토스 API로 수집해 각 발주서에 합친다.
        toss_colrabi_entries = []
        toss_bamhobak_entries = []
        toss_potato_entries = []
        toss_error = ""
        collect_dates = None
        if toss_from_date and toss_to_date:
            collect_dates = (toss_from_date, toss_to_date)
        elif include_toss.lower() == "true":
            today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
            collect_dates = (today, today)
        if collect_dates:
            try:
                toss_jeju = await tomato_order.collect_toss_jejudapam_orders(*collect_dates)
                toss_colrabi_entries = toss_jeju.get("colrabi", [])
                toss_bamhobak_entries = toss_jeju.get("bamhobak", [])
                toss_potato_entries = toss_jeju.get("potato", [])
                toss_colrabi_entries, _dup_c = issued_orders.filter_entries_by_issued(
                    toss_colrabi_entries, issued_excluded, skipped_names=dup_names
                )
                toss_bamhobak_entries, _dup_b = issued_orders.filter_entries_by_issued(
                    toss_bamhobak_entries, issued_excluded, skipped_names=dup_names
                )
                toss_potato_entries, _dup_p = issued_orders.filter_entries_by_issued(
                    toss_potato_entries, issued_excluded, skipped_names=dup_names
                )
                dup_skipped += _dup_c + _dup_b + _dup_p
            except Exception as toss_exc:
                toss_error = str(toss_exc)
                logger.warning(f"토스 제주다팜(콜라비·미니밤호박) 수집 실패(발주는 계속): {toss_exc}")

        results = kolrabi_order.process_outputs(
            delivery_bytes,
            toss_colrabi_entries=toss_colrabi_entries,
            toss_bamhobak_entries=toss_bamhobak_entries,
            toss_potato_entries=toss_potato_entries,
        )
        if not results:
            dup_note = f" (이전 발주분 {dup_skipped}건 자동 제외됨)" if dup_skipped else ""
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"제주다팜 발주로 출력할 콜라비·미니밤호박·홍감자 주문을 찾지 못했습니다.{dup_note}",
            )

        sales_ymd = _extract_ymd_from_filename(delivery_file.filename)
        for _, _, item_stats in results:
            await record_sales_from_process_stats(user["user_id"], item_stats, ymd=sales_ymd)
        await _record_issued("kolrabi", results[0][1], *[item_stats for _, _, item_stats in results])

        if len(results) == 1:
            output_bytes, filename, stats = results[0]
            if dup_skipped:
                stats = {**(stats or {}), "duplicate_skipped": dup_skipped}
                if dup_names:
                    stats["duplicate_skipped_names"] = ", ".join(n for n in dup_names if n)
            if toss_error:
                stats = {**(stats or {}), "toss_error": toss_error}
            response = make_excel_response(output_bytes, filename, stats)
        else:
            kst = timezone(timedelta(hours=9))
            filename = f"제주다팜_발주묶음({datetime.now(kst).strftime('%Y%m%d')}).zip"
            stats = {
                "files": len(results),
                "total": sum(int((item_stats or {}).get("total", 0)) for _, _, item_stats in results),
            }
            if dup_skipped:
                stats["duplicate_skipped"] = dup_skipped
                if dup_names:
                    stats["duplicate_skipped_names"] = ", ".join(n for n in dup_names if n)
            if toss_error:
                stats["toss_error"] = toss_error
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
    exclude_issued: str = Form("true"),
    user: dict = Depends(verify_token),
):
    try:
        delivery_bytes = await delivery_file.read()
        issued_excluded = await _issued_exclusions("chamdureup", exclude_issued)
        dup_names: list[str] = []
        delivery_bytes, dup_skipped = issued_orders.filter_delivery_by_issued(
            delivery_bytes, issued_excluded, skipped_names=dup_names
        )
        output_bytes, filename, stats = chamdureup_order.process(delivery_bytes)
        await _record_issued("chamdureup", filename, stats)
        if dup_skipped:
            stats = {**(stats or {}), "duplicate_skipped": dup_skipped}
            if dup_names:
                stats["duplicate_skipped_names"] = ", ".join(n for n in dup_names if n)
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


@app.post("/api/process/daangn-order")
async def process_daangn_order(
    text: str = Form(...),
    user: dict = Depends(verify_token),
):
    """당근마켓 주문 상세 텍스트 → 쥬얼리프룻 발주서."""
    try:
        result = daangn_order.process(text)
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="당근 주문 텍스트에서 발주할 주문을 찾지 못했습니다. (상품·옵션(예: '대과 2kg 1개')·받는 사람 줄이 있는지 확인)",
            )
        output_bytes, filename, stats = result
        await record_sales_from_process_stats(user["user_id"], stats, ymd=None)
        logger.info(f"당근 발주 처리 완료: {stats}")
        return make_excel_response(output_bytes, filename, stats)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("당근 발주 처리 중 오류")
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
    exclude_issued: str = Form("true"),
    user: dict = Depends(verify_token),
):
    try:
        delivery_bytes = await delivery_file.read()
        issued_excluded = await _issued_exclusions("myeongi", exclude_issued)
        dup_names: list[str] = []
        delivery_bytes, dup_skipped = issued_orders.filter_delivery_by_issued(
            delivery_bytes, issued_excluded, skipped_names=dup_names
        )
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
                toss_entries, _dup_t = issued_orders.filter_entries_by_issued(
                    toss_entries, issued_excluded, skipped_names=dup_names
                )
                dup_skipped += _dup_t
            except Exception as toss_exc:
                toss_error = str(toss_exc)
                logger.warning(f"토스 쥬얼리 수집 실패(발주는 계속): {toss_exc}")

        output_bytes, filename, stats = myeongi_order.process(
            delivery_bytes, toss_entries=toss_entries
        )
        await _record_issued("myeongi", filename, stats)
        if dup_skipped:
            stats = {**(stats or {}), "duplicate_skipped": dup_skipped}
            if dup_names:
                stats["duplicate_skipped_names"] = ", ".join(n for n in dup_names if n)
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
    exclude_issued: str = Form("true"),
    user: dict = Depends(verify_token),
):
    try:
        delivery_bytes = await delivery_file.read()
        issued_excluded = await _issued_exclusions("tomato", exclude_issued)
        dup_names: list[str] = []
        delivery_bytes, dup_skipped = issued_orders.filter_delivery_by_issued(
            delivery_bytes, issued_excluded, skipped_names=dup_names
        )
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
                toss_peach_entries, _dup_p = issued_orders.filter_entries_by_issued(
                    toss_peach_entries, issued_excluded, skipped_names=dup_names
                )
                dup_skipped += _dup_p
            except Exception as toss_exc:
                toss_peach_error = str(toss_exc)
                logger.warning(f"토스 신비복숭아 3·4kg 수집 실패(발주는 계속): {toss_exc}")

        results = tomato_order.process_outputs(delivery_bytes, toss_peach_entries=toss_peach_entries)
        if not results:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="제이비티 발주로 출력할 대저토마토·남해땅두릅·초당옥수수·신비복숭아 주문을 찾지 못했습니다. 수박·성주참외는 쥬얼리프룻 메뉴에서 출력됩니다.",
            )
        sales_ymd = _extract_ymd_from_filename(delivery_file.filename)
        for _, _, item_stats in results:
            await record_sales_from_process_stats(user["user_id"], item_stats, ymd=sales_ymd)
        await _record_issued("tomato", results[0][1], *[item_stats for _, _, item_stats in results])

        toss_peach_info = {}
        if dup_skipped:
            toss_peach_info["duplicate_skipped"] = dup_skipped
            if dup_names:
                toss_peach_info["duplicate_skipped_names"] = ", ".join(n for n in dup_names if n)
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


@app.post("/api/process/goguma-order")
async def process_goguma_order(
    delivery_file: UploadFile = File(...),
    template_file: UploadFile = File(None),
    alwayz_file: UploadFile = File(None),
    toss_file: UploadFile = File(None),
    toss_from_date: str = "",
    toss_to_date: str = "",
    include_toss: str = "",
    exclude_issued: str = Form("true"),
    temu_file: UploadFile = File(None),
    user: dict = Depends(verify_token),
):
    try:
        delivery_bytes = await delivery_file.read()
        issued_excluded = await _issued_exclusions("goguma", exclude_issued)
        dup_names: list[str] = []
        delivery_bytes, dup_skipped = issued_orders.filter_delivery_by_issued(
            delivery_bytes, issued_excluded, skipped_names=dup_names
        )
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

        temu_bytes = None
        if temu_file is not None:
            temu_bytes = await temu_file.read()
            if len(temu_bytes) == 0:
                temu_bytes = None

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

        toss_entries, _dup_t = issued_orders.filter_entries_by_issued(
            toss_entries, issued_excluded, skipped_names=dup_names
        )
        dup_skipped += _dup_t

        output_bytes, filename, stats = goguma_order.process(
            delivery_bytes, template_bytes, alwayz_bytes, toss_entries, toss_file_bytes
        )
        # 테무 주문서(선택)의 고구마 주문을 같은 해달 발주서에 합친다
        temu_issued_ids: list[str] = []
        if temu_bytes:
            temu_entries = temu_order.extract_goguma_entries(temu_bytes, temu_file.filename or "")
            temu_entries, _dup_temu = issued_orders.filter_entries_by_issued(
                temu_entries, issued_excluded, skipped_names=dup_names
            )
            dup_skipped += _dup_temu
            output_bytes = goguma_order.append_entries_to_haedal(output_bytes, temu_entries)
            stats["temu"] = len(temu_entries)
            temu_issued_ids = [issued_orders.normalize_order_id(e.get("order_id")) for e in temu_entries]
            try:
                stats["total"] = int(stats.get("total") or 0) + len(temu_entries)
            except (TypeError, ValueError):
                pass
        await _record_issued("goguma", filename, stats, extra_ids=temu_issued_ids)
        if dup_skipped:
            stats = {**(stats or {}), "duplicate_skipped": dup_skipped}
            if dup_names:
                stats["duplicate_skipped_names"] = ", ".join(n for n in dup_names if n)
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


@app.post("/api/process/send-order-email")
async def send_order_email(
    files: list[UploadFile] = File(...),
    _token: dict = Depends(verify_token),
):
    """업로드한 발주서 파일(1개 이상)을 farmers2022@naver.com로 첨부 발송.

    테무 해달 발주서를 따로 뽑았거나 발주서를 수정해서 재발송할 때 사용.
    """
    attachments: list[tuple[bytes, str]] = []
    for upload in files:
        data = await upload.read()
        if data:
            attachments.append((data, upload.filename or "발주서.xlsx"))
    if not attachments:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="첨부할 발주서 파일이 없습니다.")
    result = email_service.send_order_files_email(attachments)
    if not result.get("sent"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"이메일 발송 실패: {result.get('error')}",
        )
    logger.info(f"발주서 수동 이메일 발송: {[name for _, name in attachments]}")
    return {"status": "ok", **result, "files": [name for _, name in attachments]}


class GogumaAutoRequest(BaseModel):
    from_date: str
    to_date: str
    include_toss: bool = False
    exclude_order_ids: list[str] = []


def _filename_from_proxy_response(response: httpx.Response, default: str) -> str:
    content_disposition = response.headers.get("content-disposition", "")
    match = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", content_disposition)
    return unquote(match.group(1)) if match else default


@app.post("/api/process/goguma-auto")
async def process_goguma_auto(
    from_date: str = Form(...),
    to_date: str = Form(...),
    include_toss: str = Form("false"),
    send_email: str = Form("false"),
    exclude_issued: str = Form("true"),
    alwayz_file: UploadFile = File(None),
    temu_file: UploadFile = File(None),
    user: dict = Depends(verify_token),
):
    """쿠팡(+토스) 자동 수집 발주서에 올웨이즈·테무 주문서(선택)를 합치고, 옵션으로 발주 이메일 자동 발송."""
    try:
        include_toss_flag = include_toss.strip().lower() in ("true", "1", "on")
        send_email_flag = send_email.strip().lower() in ("true", "1", "on")
        issued_excluded = await _issued_exclusions("goguma", exclude_issued)
        temu_bytes = None
        if temu_file is not None:
            temu_bytes = await temu_file.read()
            if len(temu_bytes) == 0:
                temu_bytes = None
        alwayz_bytes = None
        if alwayz_file is not None:
            alwayz_bytes = await alwayz_file.read()
            if len(alwayz_bytes) == 0:
                alwayz_bytes = None

        if _goguma_proxy_enabled():
            proxy_response = await _post_proxy_json(
                "goguma-auto",
                {
                    "from_date": from_date,
                    "to_date": to_date,
                    "include_toss": include_toss_flag,
                    "exclude_order_ids": sorted(issued_excluded),
                },
            )
            await _record_proxy_sales(user["user_id"], proxy_response)
            output_bytes = proxy_response.content
            filename = _filename_from_proxy_response(proxy_response, "goguma-auto.xlsx")
            try:
                stats = json.loads(proxy_response.headers.get("x-stats") or "{}")
            except ValueError:
                stats = {}
        else:
            output_bytes, filename, stats = await goguma_auto.process_from_api(
                from_date, to_date, include_toss=include_toss_flag,
                exclude_order_ids=issued_excluded or None,
            )
            await record_sales_from_process_stats(
                user["user_id"], stats, ymd=from_date if from_date == to_date else None
            )

        # 올웨이즈·테무 주문서(선택)를 같은 해달 발주서에 합친다
        extra_issued_ids: list[str] = []
        dup_names: list[str] = []

        def _bump_stats(kind: str, count: int, dup: int) -> None:
            stats[kind] = count
            if dup:
                try:
                    stats["duplicate_skipped"] = int(stats.get("duplicate_skipped") or 0) + dup
                except (TypeError, ValueError):
                    stats["duplicate_skipped"] = dup
                if dup_names:
                    stats["duplicate_skipped_names"] = ", ".join(n for n in dup_names if n)
            try:
                stats["total"] = int(stats.get("total") or 0) + count
            except (TypeError, ValueError):
                pass

        if alwayz_bytes:
            alwayz_entries = goguma_order.parse_alwayz_entries(alwayz_bytes)
            alwayz_entries, _dup_alz = issued_orders.filter_entries_by_issued(
                alwayz_entries, issued_excluded, skipped_names=dup_names
            )
            output_bytes = goguma_order.append_entries_to_haedal(output_bytes, alwayz_entries)
            _bump_stats("alwayz", len(alwayz_entries), _dup_alz)
            extra_issued_ids += [issued_orders.normalize_order_id(e.get("order_id")) for e in alwayz_entries]

        if temu_bytes:
            temu_entries = temu_order.extract_goguma_entries(temu_bytes, temu_file.filename or "")
            temu_entries, _dup_temu = issued_orders.filter_entries_by_issued(
                temu_entries, issued_excluded, skipped_names=dup_names
            )
            output_bytes = goguma_order.append_entries_to_haedal(output_bytes, temu_entries)
            _bump_stats("temu", len(temu_entries), _dup_temu)
            extra_issued_ids += [issued_orders.normalize_order_id(e.get("order_id")) for e in temu_entries]

        # 발주 이력 기록 (다음 영업일 중복발주 방지)
        await _record_issued("goguma", filename, stats, extra_ids=extra_issued_ids)

        # 발주 이메일 자동 발송 (shach457@gmail.com -> farmers2022@naver.com)
        if send_email_flag:
            stats["email"] = email_service.send_haedal_order_email(output_bytes, filename)

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


# ── 사방넷 연동 (과일/Itsoft: 쥬얼리·제주다팜 자동수집 + 송장전송) ──


@app.get("/api/sabang/xml/{token}")
async def serve_sabang_request_xml(token: str):
    """사방넷이 xml_url 파라미터로 가져가는 요청 XML (임시 토큰·EUC-KR)."""
    xml_bytes = sabang_client.get_request_xml(token)
    if xml_bytes is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="XML not found or expired")
    return Response(content=xml_bytes, media_type="application/xml; charset=euc-kr")


@app.get("/api/sabang/status")
async def sabang_status(_token: dict = Depends(verify_token)):
    return {
        "configured": bool(config.SABANG_COMPANY_ID and config.SABANG_AUTH_KEY),
        "admin_url": config.SABANG_ADMIN_URL,
        "tak_code": config.SABANG_TAK_CODE,
        "order_statuses": config.SABANG_ORDER_STATUSES,
    }


@app.post("/api/sabang/test-connection")
async def sabang_test_connection(_token: dict = Depends(verify_token)):
    """쇼핑몰 목록 조회로 사방넷 연동키 유효성 확인."""
    try:
        return await sabang_client.test_connection()
    except SabangApiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.message)


def _sabang_delivery_upload(orders: list[dict]) -> UploadFile:
    ymd = datetime.now(KST).strftime("%Y%m%d")
    delivery_bytes = sabang_fruit.orders_to_delivery_xlsx(orders)
    return UploadFile(file=BytesIO(delivery_bytes), filename=f"DeliveryList_sabang_{ymd}.xlsx")


def _ymd_compact(date_str: str) -> str:
    return (date_str or "").replace("-", "").strip()


@app.post("/api/process/sabang-myeongi-order")
async def process_sabang_myeongi_order(
    from_date: str = Form(...),
    to_date: str = Form(...),
    toss_from_date: str = Form(""),
    toss_to_date: str = Form(""),
    exclude_issued: str = Form("true"),
    user: dict = Depends(verify_token),
):
    """사방넷 주문 자동수집 → 쥬얼리프룻 발주서 (DeliveryList 업로드 대체)."""
    try:
        orders = await sabang_client.fetch_orders(_ymd_compact(from_date), _ymd_compact(to_date))
    except SabangApiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.message)
    if not orders:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"사방넷에서 수집된 주문이 없습니다 ({from_date}~{to_date}, 상태 {config.SABANG_ORDER_STATUSES}).",
        )
    upload = _sabang_delivery_upload(orders)
    return await process_myeongi_order(
        delivery_file=upload,
        toss_from_date=toss_from_date,
        toss_to_date=toss_to_date,
        include_toss="",
        exclude_issued=exclude_issued,
        user=user,
    )


@app.post("/api/process/sabang-kolrabi-order")
async def process_sabang_kolrabi_order(
    from_date: str = Form(...),
    to_date: str = Form(...),
    toss_from_date: str = Form(""),
    toss_to_date: str = Form(""),
    exclude_issued: str = Form("true"),
    user: dict = Depends(verify_token),
):
    """사방넷 주문 자동수집 → 제주다팜 발주서 (DeliveryList 업로드 대체)."""
    try:
        orders = await sabang_client.fetch_orders(_ymd_compact(from_date), _ymd_compact(to_date))
    except SabangApiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.message)
    if not orders:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"사방넷에서 수집된 주문이 없습니다 ({from_date}~{to_date}, 상태 {config.SABANG_ORDER_STATUSES}).",
        )
    upload = _sabang_delivery_upload(orders)
    return await process_kolrabi_order(
        delivery_file=upload,
        toss_from_date=toss_from_date,
        toss_to_date=toss_to_date,
        include_toss="",
        exclude_issued=exclude_issued,
        user=user,
    )


@app.post("/api/process/sabang-fruit-tracking")
async def process_sabang_fruit_tracking(
    orderlist_file: UploadFile = File(...),
    tak_code: str = Form(""),
    _token: dict = Depends(verify_token),
):
    """거래처 회신(orderlist) → 사방넷 송장 자동 등록 (SABANG_INV_REGI).

    orderlist D열 주문번호가 사방넷 IDX여야 한다 — 즉 사방넷 수집으로 만든
    발주서의 회신 파일에만 사용 (쿠팡 DeliveryList 발주분은 대상 아님).
    """
    try:
        ol_bytes = await orderlist_file.read()
        entries = sabang_fruit.parse_orderlist_for_sabang(ol_bytes)
        if not entries:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="orderlist에서 (주문번호 D열, 운송장번호 R열) 쌍을 찾지 못했습니다. 거래처 회신 파일인지 확인해주세요.",
            )
        code = (tak_code or config.SABANG_TAK_CODE).strip()
        if not code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="사방넷 택배사코드가 없습니다. 화면의 택배사코드 칸에 입력하거나 "
                       "fly secrets set SABANG_TAK_CODE=<사방넷 롯데택배 코드> 로 설정해주세요.",
            )
        items = [{"idx": e["idx"], "tak_code": code, "invoice": e["tracking"]} for e in entries]
        result = await sabang_client.send_invoices(items)
        logger.info(f"사방넷 송장전송 완료: {len(items)}건")
        return {"total": len(items), "tak_code": code, **result}
    except SabangApiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.message)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("사방넷 송장전송 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


class GogumaCsReplyRequest(BaseModel):
    inquiry_id: int
    content: str


class GogumaCsInquiriesRequest(BaseModel):
    days: int = 7


@app.get("/api/process/goguma-cs/inquiries")
async def get_goguma_cs_inquiries(
    days: int = 7,
    _token: dict = Depends(verify_token),
):
    """고구마 쿠팡 계정 미답변 온라인문의 목록 + 추천 답변."""
    try:
        if _goguma_proxy_enabled():
            proxy_response = await _post_proxy_json("goguma-cs-inquiries", {"days": days})
            return proxy_response.json()
        return await goguma_cs.list_unanswered_inquiries(days)
    except CoupangApiError as e:
        logger.warning("Goguma CS inquiry fetch failed: %s", e.message)
        _raise_coupang_http_error(e)
    except Exception as e:
        logger.exception("고구마 CS 문의 조회 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@app.post("/api/process/goguma-cs/reply")
async def post_goguma_cs_reply(
    req: GogumaCsReplyRequest,
    _token: dict = Depends(verify_token),
):
    """고구마 쿠팡 온라인문의에 답변 전송 (사용자가 확인 버튼을 누른 뒤 호출)."""
    try:
        if _goguma_proxy_enabled():
            proxy_response = await _post_proxy_json(
                "goguma-cs-reply",
                {"inquiry_id": req.inquiry_id, "content": req.content},
            )
            return proxy_response.json()
        result = await goguma_cs.send_reply(req.inquiry_id, req.content)
        logger.info(f"고구마 CS 답변 전송: inquiry_id={req.inquiry_id}")
        return result
    except CoupangApiError as e:
        logger.warning("Goguma CS reply failed: %s", e.message)
        _raise_coupang_http_error(e)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("고구마 CS 답변 전송 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@app.post("/api/internal/goguma/goguma-cs-inquiries")
async def internal_goguma_cs_inquiries(
    req: GogumaCsInquiriesRequest,
    _guard: None = Depends(_internal_api_key_guard),
):
    del _guard
    try:
        return await goguma_cs.list_unanswered_inquiries(req.days)
    except CoupangApiError as e:
        logger.warning("Internal goguma CS inquiry fetch failed: %s", e.message)
        _raise_coupang_http_error(e)
    except Exception as e:
        logger.exception("Internal goguma CS inquiry bridge failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@app.post("/api/internal/goguma/goguma-cs-reply")
async def internal_goguma_cs_reply(
    req: GogumaCsReplyRequest,
    _guard: None = Depends(_internal_api_key_guard),
):
    del _guard
    try:
        return await goguma_cs.send_reply(req.inquiry_id, req.content)
    except CoupangApiError as e:
        logger.warning("Internal goguma CS reply failed: %s", e.message)
        _raise_coupang_http_error(e)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("Internal goguma CS reply bridge failed")
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
            req.from_date, req.to_date, include_toss=req.include_toss,
            exclude_order_ids=set(req.exclude_order_ids) or None,
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
    tracking_file: UploadFile = File(None),
    delivery_file: UploadFile = File(...),
    tracking_text: str = Form(""),
    _token: dict = Depends(verify_token),
):
    """게걸무 운송장 입력. 택배발송 파일 또는 이름/운송장 복붙 텍스트(둘 다 가능)."""
    try:
        tracking_bytes = None
        if tracking_file is not None:
            tracking_bytes = await tracking_file.read()
            if not tracking_bytes:
                tracking_bytes = None
        delivery_bytes = await delivery_file.read()
        output_bytes, filename, stats = gaegeolmu_tracking.process(
            tracking_bytes, delivery_bytes, tracking_text=tracking_text
        )
        logger.info(f"게걸무 운송장 입력 완료: {stats}")
        return make_excel_response(output_bytes, filename, stats)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
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
