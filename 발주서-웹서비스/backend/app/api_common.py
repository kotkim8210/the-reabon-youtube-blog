"""발주 라우트 공용 헬퍼 — 엑셀/zip 응답, 이전 발주분 제외·기록, 원격(고구마) 프록시, API 오류 변환.

main.py에서 분리(2026-11-17, 동작 변경 없음). 라우트 모듈은 `common.이름`으로 불러 테스트 monkeypatch가 먹는다.
"""

import httpx
import json
import logging
import re
import zipfile
from datetime import datetime, time as dt_time, timedelta, timezone
from fastapi import HTTPException, Header, status
from fastapi.responses import Response, StreamingResponse
from io import BytesIO
from urllib.parse import quote, unquote

from app import config, db as database
from app.coupang.client import CoupangApiError
from app.processors import issued_orders
from app.toss.client import TossApiError

logger = logging.getLogger("app.main")  # 분리 전과 같은 로그 이름

# 한국 시간. 이벤트 당첨자 묶음·사방넷·내부 고구마 발주가 이 이름을 쓰는데 정의가 한 함수 안에만 있어,
# 당첨자 경품이 거래처 2곳 이상으로 갈리면 "name 'KST' is not defined"로 발주서가 하나도 안 나왔다(2026-11-16 리뷰).
KST = timezone(timedelta(hours=9))


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


def _merge_needs_check(results: list[tuple[bytes, str, dict]]) -> list[str]:
    """여러 발주서를 zip으로 낼 때 파일별 needs_check('거래처 판매옵션에 없음' 등)를 '품목: 사유'로 모은다.

    zip 응답 stats에 다시 싣지 않으면 경고가 화면에서 사라져, 새 옵션 주문이 아무 표시 없이 발주에서 빠진다
    (2026-11-16 리뷰 — 콜라비 + 거래처 옵션에 없는 주문이 zip으로 나오면 경고 0).
    """
    notes: list[str] = []
    for _bytes, _name, item_stats in results:
        item_stats = item_stats or {}
        raw = item_stats.get("needs_check")
        items = raw if isinstance(raw, list) else ([raw] if raw else [])
        label = str(item_stats.get("product") or "").strip()
        notes += [f"{label}: {note}" if label else str(note) for note in items]
    return notes


PROXY_TIMEOUT = httpx.Timeout(180.0, connect=20.0)


def _today_kst() -> str:
    return datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")


def _exclude_issued_enabled(flag: str) -> bool:
    return (flag or "").strip().lower() not in ("false", "0", "off", "no")


async def _issued_exclusions(section: str, flag: str, reissue_stale: bool = True) -> set[str]:
    """전일 이전 발주서에 포함됐던 주문키(중복발주 방지). 같은 날 재생성은 막지 않는다.

    reissue_stale=True(기본): 영업일 2일 이상 지난 키는 제외 목록에서 뺀다 → 그 주문이 아직
    DeliveryList·토스 결제완료에 남아 있으면(=거래처 미출고) 자동으로 다시 발주서에 들어간다.
    (2026-10-08 해달 휴무일에 만든 발주서가 처리되지 않았는데 '이미 발주함'으로 막아 2건이 10/12까지 누락)
    이벤트 당첨자처럼 '아직 미출고'라는 신호가 없는 섹션은 False로 호출해 영구 제외를 유지한다.
    """
    if not _exclude_issued_enabled(flag):
        return set()
    try:
        dates = await database.issued_order_dates_before(section, _today_kst())
    except Exception:
        logger.exception("발주 이력 조회 실패(제외 없이 계속)")
        return set()
    keys = set(dates)
    if reissue_stale:
        keys -= await _issued_stale_keys(section, flag, dates)
    return keys


async def _issued_stale_keys(section: str, flag: str, issued_dates: dict[str, str] | None = None) -> set[str]:
    """자동 재발주 대상 키(거래처 접수일 기준 영업일 2일↑ 지난 발주분) — 발주서에 그대로 넣되 '미출고 재발주'로 표시.

    기산일은 발주서를 만든 시각으로 보정한다: 마감(10:30 KST) 이후·주말 생성분은 거래처가 다음 영업일에 받는다.
    """
    if not _exclude_issued_enabled(flag):
        return set()
    try:
        if issued_dates is None:
            issued_dates = await database.issued_order_dates_before(section, _today_kst())
        created = await database.issued_order_created_before(section, _today_kst())
    except Exception:
        logger.exception("발주 이력(생성시각) 조회 실패 — 재발주 없이 계속")
        return set()
    effective = {k: issued_orders.effective_issue_date(d, created.get(k)) for k, d in issued_dates.items()}
    return issued_orders.stale_issued_keys(effective, _today_kst())


def _widen_start(from_ymd: str, issued_dates: dict[str, str], reissue_keys: set[str], max_days: int = 14) -> str:
    """API 수집 시작일을 재발주 대상의 발주일까지 앞당긴다(최대 max_days).

    쿠팡·토스 API 수집은 '주문일' 기준 기간 조회라, 며칠 전 발주분은 기본 기간(어제~오늘)에 안 들어와
    재발주가 영영 안 걸린다(리뷰 지적). 미출고 주문만 돌려주므로 기간을 넓혀도 중복 위험은 없다.
    """
    candidates = [issued_dates[k] for k in reissue_keys if issued_dates.get(k)]
    if not candidates or not from_ymd:
        return from_ymd
    try:
        today = datetime.strptime(_today_kst(), "%Y-%m-%d").date()
        floor = (today - timedelta(days=max_days)).isoformat()
    except ValueError:
        return from_ymd
    start = max(min(candidates), floor)
    return min(from_ymd, start)


async def _issued_exclusion_dates(section: str, flag: str) -> dict[str, str]:
    """제외 대상 주문키 → 최초 발주일. 제외 사유를 화면에 날짜와 함께 보여주기 위한 조회."""
    if not _exclude_issued_enabled(flag):
        return {}
    try:
        return await database.issued_order_dates_before(section, _today_kst())
    except Exception:
        logger.exception("발주 이력 날짜 조회 실패(경고 없이 계속)")
        return {}


def _issued_label(name: str, key: str, issued_dates: dict[str, str]) -> str:
    """'김영옥(10/8 발주분)' — 발주일을 못 찾으면 이름만."""
    issued = issued_dates.get(key) or issued_dates.get((key or "").split(issued_orders.KEY_SEP)[0], "")
    try:
        issued_d = datetime.strptime(issued, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return name
    return f"{name}({issued_d.month}/{issued_d.day} 발주분)"


def _annotate_excluded(
    stats: dict,
    dup_skipped: int,
    dup_names: list[str],
    dup_keys: list[str],
    issued_dates: dict[str, str],
    reissued: list[tuple[str, str]] | None = None,
) -> dict:
    """중복 제외·미출고 재발주 결과를 stats에 담는다 — 이름 옆에 원래 발주일을 붙여 침묵을 막는다.

    reissued: (받는분, 키) — 영업일 2일↑ 전에 발주서에 넣었는데 아직 미출고라 이번 발주서에 다시 넣은 주문.
    (종전의 '체크 해제하세요' 경고는 폐지 — 경고를 못 보고 넘어가 주문이 며칠씩 묻혔다. 이제 자동으로 넣는다.)
    """
    if not dup_skipped and not reissued:
        return stats
    stats = dict(stats or {})
    if dup_skipped:
        stats["duplicate_skipped"] = dup_skipped
        labels = [
            _issued_label(name, dup_keys[idx] if idx < len(dup_keys) else "", issued_dates)
            for idx, name in enumerate(n for n in dup_names if n)
        ]
        if labels:
            stats["duplicate_skipped_names"] = ", ".join(labels)
    if reissued:
        stats["reissued"] = len(reissued)
        stats["reissued_names"] = ", ".join(_issued_label(name, key, issued_dates) for name, key in reissued)
        old_days: list[str] = []
        for _, key in reissued:
            label = _issued_label("", key, issued_dates)      # '(10/8 발주분)' 또는 ''
            day = label[1:].split(" ")[0] if label.startswith("(") else ""
            if day and day not in old_days:
                old_days.append(day)
        stats["needs_check"] = list(stats.get("needs_check") or []) + [
            f"미출고 재발주 {len(reissued)}건 포함 — 거래처가 이전 발주서({', '.join(old_days) or '이전'})를 뒤늦게 처리하면 이중 출고되니 그 발주서는 폐기하라고 알려주세요"
        ]
    # 재발주를 안 하는 섹션(이벤트 당첨자)에서 2영업일↑ 지난 당첨자가 또 올라오면 알린다 — 침묵 영구 제외 방지
    stale_dups = [
        name for idx, name in enumerate(n for n in dup_names if n)
        if idx < len(dup_keys) and dup_keys[idx] in issued_orders.stale_issued_keys(issued_dates, _today_kst())
    ]
    if stale_dups:
        stats["needs_check"] = list(stats.get("needs_check") or []) + [
            f"이전에 발주한 당첨자가 다시 올라옴(자동 재발주 안 함): {', '.join(stale_dups)} — 거래처 발송 여부 확인 후 필요하면 당첨자만 다시 발주"
        ]
    return stats

def _require_xlsx(data: bytes, field_label: str = "DeliveryList") -> None:
    """발주 칸에 엑셀이 아닌 파일이 올라오면 원인을 알려준다.

    openpyxl 원본 오류가 'File is not a zip file'이라 화면만 보고는 원인을 알 수 없다.
    실제 사례: 이벤트 당첨자 CSV(winners_raw)를 DeliveryList 칸에 업로드(2026-07-27).
    """
    if data[:2] == b"PK":  # xlsx = zip
        return
    first_line = data[:512].lstrip(b"\xef\xbb\xbf").split(b"\n", 1)[0]
    if b"," in first_line:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{field_label} 칸에는 쿠팡 엑셀(.xlsx) 파일만 올릴 수 있습니다. "
                "라이브 이벤트 당첨자 CSV(winners_raw)라면 아래 "
                "'🎉 라이브 이벤트 당첨자 발주서 생성' 카드에 올려주세요."
            ),
        )
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"{field_label} 파일이 엑셀(.xlsx)이 아닙니다. 쿠팡에서 받은 .xlsx 파일을 그대로 올려주세요.",
    )


# 발주 마감(KST). 이 시각 이후 생성분은 '늦은 발주'로 로그에만 표시한다 — 기록은 한다.
#
# 과거엔 마감 이후 생성분을 아예 기록하지 않았다(조회·미리보기로 간주). 그 이유는
# 마감 후 생성을 기록하면 다음 영업일 자동제외가 그 주문들을 '이미 발주됨'으로
# 걸러 조용히 누락시키기 때문이었다(2026-07-10 토스 백도 최종화 건).
# 하지만 그 침묵 누락은 이후 '제외된 주문(받는분) 표시'로 이미 막혔고, 대신 반대편
# 사고가 터졌다 — 2026-08-17 16:17 생성한 제주다팜 실제 발주(청사과 90·콜라비 1·
# 미니밤호박 41)가 마감 이후라 미기록되어, 다음날 132건이 통째로 중복 발주됐다.
#
# 시각만으로 '실제 발주'와 '미리보기'를 구분할 수 없다. 둘 중 하나를 골라야 한다면
# 기록하는 쪽이 안전하다: 잘못 기록되면 다음날 제외 목록에 이름이 떠서 눈에 보이고
# 체크박스를 꺼서 되살릴 수 있지만, 기록을 빠뜨리면 거래처로 중복 발주가 나간다.
_ISSUE_RECORD_CUTOFF = dt_time(10, 30)


async def _record_issued(section: str, filename: str, *stats_list: dict, extra_ids: list[str] | None = None) -> None:
    """발주서에 실제 기록된 주문번호(stats options[].orders[])를 이력으로 저장.

    생성 시각과 무관하게 항상 기록한다. 마감 이후 생성분도 실제 발주일 수 있어
    빠뜨리면 다음 영업일에 중복 발주가 나간다(2026-08-17 제주다팜 132건 사고).
    """
    now_kst = datetime.now(timezone(timedelta(hours=9)))
    if now_kst.time() > _ISSUE_RECORD_CUTOFF:
        logger.info(
            "발주 마감(10:30 KST) 이후 생성 → 발주 이력에 기록함(다음날 중복 방지): "
            "section=%s file=%s (%s)",
            section, filename, now_kst.strftime("%H:%M"),
        )
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


def _filename_from_proxy_response(response: httpx.Response, default: str) -> str:
    content_disposition = response.headers.get("content-disposition", "")
    match = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", content_disposition)
    return unquote(match.group(1)) if match else default
