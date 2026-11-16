"""쿠팡·토스 API 실패가 '성공'으로 보이던 문제 — 2026-11-16 리뷰 2순위(api_layer-2·tracking-4·completeness-1·2).

1) 클라이언트가 429/5xx를 3번 받으면 예외 없이 None을 돌려줘, 호출부가 '등록 성공'으로 세거나
   주문을 조용히 빠뜨렸다 → 재시도 소진은 CoupangApiError / TossApiError(상태코드 포함)로 올린다.
2) 토스 취소·교환·반품 승인/거부가 HTTP 200 + resultType=FAIL로 거절돼도 화면에 '완료' → 예외 → 502.
3) 쿠팡 CS 탭: 미답변(NOANSWER) 조회가 실패하면 모든 문의가 '답변완료'로 보이고 답변칸이 숨었다
   → '미답변 조회 실패' 오류로 올린다. 고객센터(v5) 문의 조회 실패도 조용히 빠뜨리지 않고 확인 필요로 알린다.
4) 서버 시작 때 쿠팡이 5xx를 끝까지 돌려줘도(이제 예외) 기동은 계속된다(refresh 함수가 예외를 삼킨다 — 확인).
5) 쿠팡·DeliveryList 주문이 0건이면 '주문 없음' 오류가 토스 수집 실패를 덮었다 → 오류 문구에 토스 실패를 함께 싣는다.

외부 API는 부르지 않는다 — httpx.MockTransport·monkeypatch만 쓴다.
"""

import asyncio
import time

import httpx
import pytest
from fastapi import HTTPException

from app import api_common
from app.routes import process_fruit, process_goguma
from app.coupang import client as coupang_mod
from app.coupang.client import CoupangApiError, CoupangClient
from app.toss import client as toss_mod
from app.toss.client import TossApiError, TossClient


@pytest.fixture(autouse=True)
def no_retry_sleep(monkeypatch):
    """재시도 대기(1·2·4초)를 0초로 — 기다리려던 초만 기록한다."""
    waits: list[float] = []

    async def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return waits


def _coupang(handler) -> CoupangClient:
    client = CoupangClient("A00000000", "test-access", "test-secret", account_label="test")
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


def _toss(handler) -> TossClient:
    client = TossClient()
    client.access_key, client.secret_key = "test-access", "test-secret"
    client._token, client._token_expires_at = "test-token", time.time() + 3600   # OAuth 호출 없이
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


def test_brief_error_names_point_to_same_classes():
    assert coupang_mod.CoupangAPIError is CoupangApiError
    assert toss_mod.TossAPIError is TossApiError


# ── 1) 재시도 소진 → 예외 (None/[] 아님) ──

def test_coupang_5xx_three_times_raises_not_none():
    seen: list[str] = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(503, text="<html>upstream-body-secret</html>")

    client = _coupang(handler)
    with pytest.raises(CoupangApiError) as exc:
        asyncio.run(client.get_order_sheets(
            created_at_from="2026-11-10", created_at_to="2026-11-16", order_status="ACCEPT",
        ))

    assert len(seen) == coupang_mod.MAX_RETRIES
    assert exc.value.status_code == 503
    assert "HTTP 503" in str(exc.value) and "재시도" in str(exc.value)
    assert "upstream-body-secret" not in str(exc.value)   # 응답 본문은 메시지에 넣지 않는다


def test_coupang_429_three_times_raises():
    client = _coupang(lambda request: httpx.Response(429, json={"message": "Too Many Requests"}))
    with pytest.raises(CoupangApiError) as exc:
        asyncio.run(client.get_online_inquiries("2026-11-10", "2026-11-16"))
    assert exc.value.status_code == 429


def test_coupang_recovers_after_one_5xx(no_retry_sleep):
    responses = [httpx.Response(502), httpx.Response(200, json={"code": 200, "data": []})]
    client = _coupang(lambda request: responses.pop(0))
    assert asyncio.run(client.get_order_sheets(order_status="INSTRUCT")) == {"code": 200, "data": []}
    assert no_retry_sleep == [1]


def test_toss_5xx_three_times_raises_not_empty_list():
    seen: list[str] = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(500, text="upstream-body-secret")

    client = _toss(handler)
    with pytest.raises(TossApiError) as exc:
        asyncio.run(client.get_orders("2026-11-10", "2026-11-16"))

    assert len(seen) == toss_mod.MAX_RETRIES
    assert exc.value.status_code == 500
    assert "HTTP 500" in str(exc.value) and "재시도" in str(exc.value)
    assert "upstream-body-secret" not in str(exc.value)


def test_toss_429_three_times_raises():
    client = _toss(lambda request: httpx.Response(429))
    with pytest.raises(TossApiError) as exc:
        asyncio.run(client.get_claims("2026-11-10", "2026-11-16"))
    assert exc.value.status_code == 429


def test_toss_no_orders_is_still_empty_list():
    """정상적인 '주문 없음'은 예외가 아니다."""
    ok = {"resultType": "SUCCESS", "success": {"results": [], "nextCursor": None}}
    client = _toss(lambda request: httpx.Response(200, json=ok))
    assert asyncio.run(client.get_orders("2026-11-10", "2026-11-16")) == []


def test_toss_register_tracking_5xx_raises_without_status_change():
    seen: list[tuple[str, str]] = []

    def handler(request):
        seen.append((request.method, request.url.path))
        return httpx.Response(503)

    client = _toss(handler)
    with pytest.raises(TossApiError) as exc:
        asyncio.run(client.register_tracking(111, "롯데택배", "2345-6789-0123"))

    assert exc.value.status_code == 503
    # 서버 오류는 '상품준비중 아님'이 아니다 — 주문 상태 변경(confirm) 후 재등록으로 새지 않는다
    assert seen == [("PUT", "/api/v3/shopping-fep/orders/products/delivery")] * toss_mod.MAX_RETRIES


# ── 2) 토스 클레임 승인/거부: resultType=FAIL → 예외 → 502 ──

FAIL_ENVELOPE = {
    "resultType": "FAIL",
    "success": None,
    "error": {"errorCode": "INVALID_REQUEST", "reason": "이미 처리된 클레임입니다"},
}

CLAIM_CALLS = [
    ("approve_cancel", (11,)),
    ("reject_cancel", (11, "재고 있음")),
    ("approve_exchange", (11,)),
    ("reject_exchange", (11, "재고 있음")),
    ("approve_return", (11,)),
    ("reject_return", (11, "재고 있음")),
]


@pytest.mark.parametrize("method,args", CLAIM_CALLS)
def test_toss_claim_fail_envelope_raises(method, args):
    client = _toss(lambda request: httpx.Response(200, json=FAIL_ENVELOPE))
    with pytest.raises(TossApiError) as exc:
        asyncio.run(getattr(client, method)(*args))
    assert "이미 처리된 클레임" in str(exc.value)


@pytest.mark.parametrize("method,args", CLAIM_CALLS)
def test_toss_claim_success_returns_result(method, args):
    ok = {"resultType": "SUCCESS", "success": {"orderProductId": 11}}
    client = _toss(lambda request: httpx.Response(200, json=ok))
    assert asyncio.run(getattr(client, method)(*args)) == ok


def test_toss_claim_empty_body_is_not_success():
    """본문이 비면(null) 처리됐는지 알 수 없다 — 성공으로 넘기지 않는다."""
    client = _toss(lambda request: httpx.Response(
        200, content=b"null", headers={"Content-Type": "application/json"},
    ))
    with pytest.raises(TossApiError):
        asyncio.run(client.approve_cancel(11))


@pytest.mark.parametrize("endpoint,reason", [
    ("approve_cancel", ""),
    ("reject_cancel", "재고 있음"),
    ("approve_exchange", ""),
    ("reject_exchange", "재고 있음"),
    ("approve_return", ""),
    ("reject_return", "재고 있음"),
])
def test_claim_endpoint_reports_fail_not_ok(monkeypatch, endpoint, reason):
    from app.routes import toss as toss_routes

    async def fake_request(method, path, params=None, json_body=None):
        return FAIL_ENVELOPE

    monkeypatch.setattr(toss_routes.toss_client, "_request", fake_request)
    req = toss_routes.ClaimActionRequest(order_product_id=11, reason=reason)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(getattr(toss_routes, endpoint)(req, _token={}))
    assert exc.value.status_code == 502
    assert "이미 처리된 클레임" in exc.value.detail


def test_toss_watermelon_tracking_endpoint_api_error_is_502(monkeypatch):
    from io import BytesIO

    from fastapi import UploadFile


    async def failing(_reply_bytes):
        raise TossApiError(
            "토스 서버 오류(HTTP 503) — 3회 재시도 실패, 잠시 뒤 다시 시도해 주세요", status_code=503,
        )

    monkeypatch.setattr(process_fruit.tomato_tracking, "process_toss_watermelon_tracking", failing)
    upload = UploadFile(file=BytesIO(b"reply"), filename="reply.xlsx")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(process_fruit.process_toss_watermelon_tracking(tomato_reply_file=upload, _token={}))
    assert exc.value.status_code == 502
    assert "HTTP 503" in exc.value.detail


def test_claim_endpoint_5xx_is_502_with_retry_hint(monkeypatch):
    from app.routes import toss as toss_routes

    monkeypatch.setattr(toss_routes, "toss_client", _toss(lambda request: httpx.Response(503)))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(toss_routes.approve_return(toss_routes.ClaimActionRequest(order_product_id=11), _token={}))
    assert exc.value.status_code == 502
    assert "HTTP 503" in exc.value.detail and "잠시 뒤 다시 시도" in exc.value.detail


# ── 3) 쿠팡 CS: 미답변 조회 실패 → '답변완료'로 바꾸지 않고 오류 ──

INQUIRY = {"inquiryId": 501, "content": "언제 배송되나요?", "inquiryAt": "2026-11-15 10:00:00", "orderIds": [7001]}


def _cs_handler(noanswer_status: int):
    def handler(request):
        page = {"content": [], "pagination": {"totalPages": 1}}
        if request.url.path.endswith("/callCenterInquiries"):
            return httpx.Response(200, json={"code": 200, "data": page})
        if request.url.params.get("answeredType") == "NOANSWER" and noanswer_status != 200:
            return httpx.Response(noanswer_status)
        return httpx.Response(200, json={"code": 200, "data": {**page, "content": [INQUIRY]}})
    return handler


def test_cs_unanswered_fetch_failure_is_error_not_all_answered(monkeypatch):
    from app.processors import goguma_cs

    monkeypatch.setattr(goguma_cs, "coupang_goguma_client", _coupang(_cs_handler(503)))
    with pytest.raises(CoupangApiError) as exc:
        asyncio.run(goguma_cs.list_inquiries(days=7))
    assert exc.value.status_code == 503
    assert "미답변 조회 실패" in str(exc.value)


def test_cs_endpoint_shows_unanswered_failure(monkeypatch):
    from app.processors import goguma_cs

    monkeypatch.setattr(api_common, "_goguma_proxy_enabled", lambda: False)
    monkeypatch.setattr(goguma_cs, "coupang_goguma_client", _coupang(_cs_handler(429)))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(process_goguma.get_goguma_cs_inquiries(days=7, _token={}))
    assert exc.value.status_code == 502
    assert "미답변 조회 실패" in exc.value.detail


def test_cs_normal_unanswered_still_shown(monkeypatch):
    from app.processors import goguma_cs

    monkeypatch.setattr(goguma_cs, "coupang_goguma_client", _coupang(_cs_handler(200)))
    res = asyncio.run(goguma_cs.list_inquiries(days=7))
    assert res["unanswered"] == 1
    assert res["inquiries"][0]["answered"] is False
    assert "needs_check" not in res   # 조회가 다 됐으면 경고 없음


def test_cs_call_center_failure_is_flagged_not_silent(monkeypatch):
    """고객센터(v5) 문의 조회가 5xx로 끝나면 로그만 남기고 '답변필요' 문의가 조용히 사라졌다 → 확인 필요로 알린다."""
    from app.processors import goguma_cs

    def handler(request):
        if request.url.path.endswith("/callCenterInquiries"):
            return httpx.Response(503, text="upstream-body-secret")
        return _cs_handler(200)(request)

    monkeypatch.setattr(goguma_cs, "coupang_goguma_client", _coupang(handler))
    res = asyncio.run(goguma_cs.list_inquiries(days=7))

    assert res["total"] == 1 and res["unanswered"] == 1   # 상품문의 목록은 그대로
    notes = res["needs_check"]
    assert len(notes) == 2   # 답변필요·확인필요 상태별로 한 줄씩
    assert any("고객센터 문의(답변필요) 조회 실패" in n for n in notes)
    assert any("고객센터 문의(확인필요) 조회 실패" in n for n in notes)
    assert all("HTTP 503" in n and "upstream-body-secret" not in n for n in notes)


def test_cs_reply_5xx_is_error_not_sent(monkeypatch):
    from app import config
    from app.processors import goguma_cs

    monkeypatch.setattr(config, "COUPANG_GOGUMA_WING_ID", "wing-test")
    monkeypatch.setattr(goguma_cs, "coupang_goguma_client", _coupang(lambda request: httpx.Response(500)))
    with pytest.raises(CoupangApiError):
        asyncio.run(goguma_cs.send_reply(501, "안녕하세요 고객님\n확인 후 안내드리겠습니다. 감사합니다"))


# ── 쿠팡 고구마 주문 수집: 5xx면 '주문 없음'이 아니라 오류 ──

def test_goguma_auto_coupang_5xx_is_error_not_no_orders(monkeypatch):
    from app.processors import goguma_auto

    monkeypatch.setattr(goguma_auto, "coupang_goguma_client", _coupang(lambda request: httpx.Response(503)))
    with pytest.raises(CoupangApiError):
        asyncio.run(goguma_auto.collect_orders("2026-11-15", "2026-11-16"))


def test_goguma_auto_no_orders_is_empty_list(monkeypatch):
    from app.processors import goguma_auto

    ok = {"code": 200, "message": "OK", "data": [], "nextToken": ""}
    monkeypatch.setattr(goguma_auto, "coupang_goguma_client", _coupang(lambda request: httpx.Response(200, json=ok)))
    assert asyncio.run(goguma_auto.collect_orders("2026-11-15", "2026-11-16")) == []


# ── 송장 등록 호출부: API 실패가 '등록 성공'으로 집계되지 않는다 (호출부 모듈은 그대로 사용) ──

def test_coupang_invoice_upload_5xx_counts_as_fail(monkeypatch):
    from app.processors import goguma_tracking_api as gta

    uploads: list[str] = []

    def handler(request):
        uploads.append(request.url.path)
        return httpx.Response(503)

    monkeypatch.setattr(gta, "coupang_goguma_client", _coupang(handler))
    monkeypatch.setattr(gta, "parse_haedal_file", lambda _b: [{
        "name": "김등록", "phone": "01011112222", "address": "", "tracking": "699011112222",
        "delivery_company_code": "HANJIN", "option_keys": set(),
    }])

    async def fake_fetch():
        return [{
            "shipment_box_id": 101, "order_id": 1010, "vendor_item_id": 10100,
            "name": "김등록", "phone": "01011112222", "address": "주소101", "name_display": "김등록",
            "order_status": "INSTRUCT", "option_keys": set(),
        }]

    monkeypatch.setattr(gta, "fetch_pending_orders", fake_fetch)
    result = asyncio.run(gta.process_tracking_api(b"fake"))

    assert result["success"] == 0 and result["fail"] == 1, result
    assert "HTTP 503" in result["results"][0]["message"]
    assert len(uploads) == coupang_mod.MAX_RETRIES   # '상태 전이 의심' 재시도로 새지 않는다


def test_toss_register_5xx_counts_as_fail(monkeypatch):
    from app.processors import toss_auto

    order = {
        "orderProductId": 9001, "orderId": "T-9001", "productName": "해남 황금 꿀고구마", "optionName": "3kg 중상",
        "receiverName": "김토스", "receiverRealPhone": "050212345678", "address": "서울시 테스트로 1",
        "detailAddress": "", "orderProductStatus": "PREPARING_PRODUCT", "shippingTrackingNumber": None,
    }
    puts: list[str] = []

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={
                "resultType": "SUCCESS", "success": {"results": [order], "nextCursor": None},
            })
        puts.append(request.url.path)
        return httpx.Response(503)

    monkeypatch.setattr(toss_auto, "toss_client", _toss(handler))
    monkeypatch.setattr(toss_auto, "parse_haedal_file", lambda _b: [{
        "name": "김토스", "phone": "050212345678", "address": "서울시테스트로1",
        "tracking": "463300001111", "courier": "한진택배", "option_keys": set(),
    }])
    result = asyncio.run(toss_auto.process_toss_tracking(b"fake"))

    assert result["success"] == 0 and result["fail"] == 1, result
    assert len(puts) == toss_mod.MAX_RETRIES


# ── 5) 쿠팡·DeliveryList 0건 + 토스 실패: '주문 없음'이 토스 실패를 덮지 않는다 ──

def _xlsx_header_only() -> bytes:
    """주문 행이 없는 DeliveryList(헤더만)."""
    from io import BytesIO

    from openpyxl import Workbook

    wb = Workbook()
    wb.active.append([f"H{i}" for i in range(1, 32)])
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


def _upload(data: bytes, filename: str = "DeliveryList(2026-11-16).xlsx"):
    from io import BytesIO

    from fastapi import UploadFile

    return UploadFile(file=BytesIO(data), filename=filename)


def _no_issued_history(monkeypatch, main):
    """발주 이력·판매 기록 DB를 건드리지 않는다 — 이전 발주분 없음."""

    async def no_exclusions(section, flag, reissue_stale=True):
        return set()

    async def no_dates(section, flag):
        return {}

    async def no_stale(section, flag, issued_dates=None):
        return set()

    async def no_sales(*_args, **_kwargs):
        return None

    monkeypatch.setattr(api_common, "_issued_exclusions", no_exclusions)
    monkeypatch.setattr(api_common, "_issued_exclusion_dates", no_dates)
    monkeypatch.setattr(api_common, "_issued_stale_keys", no_stale)
    monkeypatch.setattr(api_common, "_goguma_proxy_enabled", lambda: False)
    monkeypatch.setattr(api_common, "record_sales_from_process_stats", no_sales)


def _toss_always_503(monkeypatch) -> list[str]:
    """토스가 503만 돌려준다. 실제로 토스를 불렀는지 보려고 부른 경로를 기록한다."""
    calls: list[str] = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(503, text="upstream-body-secret")

    monkeypatch.setattr(toss_mod, "toss_client", _toss(handler))
    return calls


EMPTY_COUPANG_ORDERS = {"code": 200, "message": "OK", "data": [], "nextToken": ""}


def _run_goguma_auto(main):
    return asyncio.run(process_goguma.process_goguma_auto(
        from_date="2026-11-16", to_date="2026-11-16", include_toss="true", send_email="false",
        exclude_issued="true", alwayz_file=None, temu_file=None, winners_file=None, user={"user_id": 1},
    ))


def test_goguma_auto_zero_coupang_toss_fail_is_not_just_no_orders(monkeypatch):
    from app import main
    from app.processors import goguma_auto

    _no_issued_history(monkeypatch, main)
    toss_calls = _toss_always_503(monkeypatch)
    monkeypatch.setattr(goguma_auto, "coupang_goguma_client", _coupang(
        lambda request: httpx.Response(200, json=EMPTY_COUPANG_ORDERS)))

    with pytest.raises(HTTPException) as exc:
        _run_goguma_auto(main)

    assert len(toss_calls) == toss_mod.MAX_RETRIES
    assert "토스 주문 수집 실패" in exc.value.detail and "HTTP 503" in exc.value.detail
    assert "upstream-body-secret" not in exc.value.detail


def test_goguma_auto_zero_orders_without_toss_failure_unchanged(monkeypatch):
    """토스가 정상인데 둘 다 0건이면 예전 문구 그대로(정상 회귀)."""
    from app import main
    from app.processors import goguma_auto

    _no_issued_history(monkeypatch, main)
    monkeypatch.setattr(toss_mod, "toss_client", _toss(lambda request: httpx.Response(200, json={
        "resultType": "SUCCESS", "success": {"results": [], "nextCursor": None},
    })))
    monkeypatch.setattr(goguma_auto, "coupang_goguma_client", _coupang(
        lambda request: httpx.Response(200, json=EMPTY_COUPANG_ORDERS)))

    with pytest.raises(HTTPException) as exc:
        _run_goguma_auto(main)
    assert exc.value.status_code == 404
    assert exc.value.detail == "해당 기간에 고구마 주문이 없습니다."


def test_goguma_auto_all_duplicates_toss_fail_keeps_toss_note(monkeypatch):
    """쿠팡분이 전부 이전 발주분으로 빠지고 토스는 실패 — '신규 주문 없음'에도 토스 실패를 싣는다."""
    from app.processors import goguma_auto, issued_orders

    async def one_coupang_order(_from, _to):
        return [{"order_id": "1010", "product": "꿀고구마 3Kg (중상)", "option": "3kg 중상", "name": "김중복"}]

    async def toss_fails(_from, _to):
        raise TossApiError("토스 서버 오류(HTTP 503) — 3회 재시도 실패, 잠시 뒤 다시 시도해 주세요", status_code=503)

    def all_duplicates(entries, _excluded, **_kwargs):
        return [], len(entries)

    monkeypatch.setattr(goguma_auto, "collect_orders", one_coupang_order)
    monkeypatch.setattr(goguma_auto.goguma_order, "collect_toss_orders", toss_fails)
    monkeypatch.setattr(issued_orders, "filter_entries_by_issued", all_duplicates)

    with pytest.raises(ValueError) as exc:
        asyncio.run(goguma_auto.process_from_api(
            "2026-11-16", "2026-11-16", include_toss=True, exclude_order_ids={"1010|3kg 중상"},
        ))
    assert "이전 발주분 1건 자동 제외" in str(exc.value)
    assert "토스 주문 수집 실패" in str(exc.value) and "HTTP 503" in str(exc.value)


def test_tomato_order_no_jbt_items_toss_fail_shows_toss_failure(monkeypatch):
    from app import main

    _no_issued_history(monkeypatch, main)
    toss_calls = _toss_always_503(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(process_fruit.process_tomato_order(
            delivery_file=_upload(_xlsx_header_only()), toss_from_date="2026-11-16", toss_to_date="2026-11-16",
            include_toss="", exclude_issued="true", user={"user_id": 1},
        ))

    assert len(toss_calls) == toss_mod.MAX_RETRIES
    assert exc.value.status_code == 400 and "찾지 못했습니다" in exc.value.detail
    assert "토스 신비복숭아 수집 실패" in exc.value.detail and "HTTP 503" in exc.value.detail


def test_kolrabi_order_no_items_toss_fail_shows_toss_failure(monkeypatch):
    from app import main

    _no_issued_history(monkeypatch, main)
    toss_calls = _toss_always_503(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(process_fruit.process_kolrabi_order(
            delivery_file=_upload(_xlsx_header_only()), toss_from_date="2026-11-16", toss_to_date="2026-11-16",
            include_toss="", exclude_issued="true", user={"user_id": 1},
        ))

    assert len(toss_calls) == toss_mod.MAX_RETRIES
    assert exc.value.status_code == 400 and "찾지 못했습니다" in exc.value.detail
    assert "토스 수집 실패" in exc.value.detail and "HTTP 503" in exc.value.detail


def test_hobak_goguma_all_duplicates_toss_fail_shows_toss_failure(monkeypatch):
    """쿠팡분이 전부 이전 발주분으로 빠진 경우의 '신규 주문 없음' 문구도 토스 실패를 덮지 않는다."""
    from app import main

    _no_issued_history(monkeypatch, main)
    toss_calls = _toss_always_503(monkeypatch)

    def one_duplicate(delivery_bytes, _excluded, skipped_names=None, skipped_keys=None, **_kwargs):
        if skipped_names is not None:
            skipped_names.append("김중복")
        if skipped_keys is not None:
            skipped_keys.append("1010|호박고구마 3kg")
        return delivery_bytes, 1

    monkeypatch.setattr(api_common.issued_orders, "filter_delivery_by_issued", one_duplicate)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(process_goguma.process_hobak_goguma_order(
            delivery_file=_upload(_xlsx_header_only()), winners_file=None,
            toss_from_date="2026-11-16", toss_to_date="2026-11-16", exclude_issued="true", user={"user_id": 1},
        ))

    assert len(toss_calls) == toss_mod.MAX_RETRIES
    assert exc.value.status_code == 400 and "이전 발주분 1건 자동 제외" in exc.value.detail
    assert "토스 수집 실패" in exc.value.detail and "HTTP 503" in exc.value.detail


# ── 4) 서버 시작: 쿠팡이 5xx를 끝까지 돌려줘도(이제 예외) 기동은 계속된다 ──

def test_startup_survives_coupang_5xx(monkeypatch):
    """실제 refresh_products·refresh_orders를 그대로 부른다 — 둘 다 예외를 삼켜(로그만) 기동이 멈추지 않는다."""
    from app import main, rules_engine, scheduler

    coupang_calls: list[str] = []

    def handler(request):
        coupang_calls.append(request.url.path)
        return httpx.Response(503)

    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(main.database, "init_db", noop)
    monkeypatch.setattr(main.database, "close_db", noop)
    monkeypatch.setattr(rules_engine, "refresh_rules", noop)
    monkeypatch.setattr(main, "start_scheduler", lambda: None)
    monkeypatch.setattr(main, "stop_scheduler", lambda: None)
    monkeypatch.setattr(scheduler.coupang_client, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(scheduler.db, "cache_products", noop)
    monkeypatch.setattr(scheduler.db, "cache_orders", noop)
    served: list[str] = []

    async def run():
        async with main.lifespan(main.app):
            served.append("serving")

    asyncio.run(run())
    assert served == ["serving"]
    # 상품 조회와 주문 조회 둘 다 실제로 쿠팡을 불렀다(각각 재시도 소진 → 예외 → 로그만)
    assert len(coupang_calls) == coupang_mod.MAX_RETRIES * 2
