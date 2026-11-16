"""꿀고구마 발주(goguma-auto)에 라이브 이벤트 당첨자 CSV를 합친다 (2026-11-16 사용자 요청).

고구마 발주 화면의 테무 칸(테무 주문 끊김)을 당첨자 칸으로 바꾸고, 호박고구마처럼 같은 해달 발주서 한 장에 넣는다.
- 경품명 '꿀고구마 중상 2kg' → 해달 품목명 '꿀고구마 2Kg (중상)'
- 호박고구마·다른 상품 경품은 빼고 '확인 필요'로 알림, 환불/취소 건 제외
- 당첨 이력은 goguma_event 섹션에 따로 영구 기록 → 같은 명단을 다시 올려도 중복 발송 없음
- 쿠팡·토스 주문이 0건이어도 당첨자만으로 발주서가 나와야 한다
"""

import asyncio
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile
from openpyxl import load_workbook

from app import main
from app import api_common
from app.routes import process_goguma
from app.processors import goguma_auto, goguma_order, issued_orders

HEADER = "경품명,별명,개인 식별 정보 확인,이름,연락처,주소,주문 아이디,구매 금액,환불/취소 금액,환불/날짜/시간"
ROW_KKUL = "꿀고구마 중상 2kg,홍*동,2026/11/15 14:01,홍길동,010-1111-2222,제주특별자치도 제주시 테스트로 1,30100000000001,13700,0,"
ROW_HOBAK = "호박고구마 특상 3kg,김*수,2026/11/15 14:02,김철수,010-3333-4444,서울시 테스트구 2,30100000000002,13700,0,"
ROW_REFUND = "꿀고구마 특상 3kg,이*희,2026/11/15 14:03,이영희,010-5555-6666,부산시 테스트구 3,30100000000003,13700,13700,2026/11/15 15:00"
ROW_KKUL_5 = "꿀고구마 특상 5kg,박*민,2026/11/15 14:04,박민수,010-7777-8888,대구시 테스트구 4,30100000000004,13700,0,"


def _csv(*rows: str) -> bytes:
    return ("\n".join((HEADER,) + rows) + "\n").encode("utf-8-sig")


def _haedal_rows(xlsx_bytes: bytes) -> list[tuple]:
    ws = load_workbook(BytesIO(xlsx_bytes)).worksheets[0]
    return [
        (ws.cell(r, 1).value, ws.cell(r, 14).value, ws.cell(r, 13).value)
        for r in range(2, ws.max_row + 1)
        if ws.cell(r, 1).value not in (None, "")
    ]


# ── 당첨자 CSV → 해달 entries ────────────────────────────────────────
def test_prepare_event_entries_maps_kkul_goguma_and_filters_others():
    entries, info = goguma_order.prepare_event_entries(_csv(ROW_KKUL, ROW_HOBAK, ROW_REFUND))

    assert [e["name"] for e in entries] == ["홍길동"]
    e = entries[0]
    assert e["product"] == "꿀고구마 2Kg (중상)"
    assert e["qty"] == "1" and e["zipcode"] == "" and e["phone"] == "010-1111-2222"
    assert e["order_id"] == "30100000000001"
    assert info["refund_skipped"] == 1
    assert len(info["others"]) == 1 and "김철수" in info["others"][0]   # 호박고구마는 호박고구마 페이지에서
    assert info["dup"] == 0 and info["unreadable"] == []


def test_prepare_event_entries_skips_already_issued_winner():
    issued = {issued_orders.make_order_key("30100000000001", "꿀고구마 2Kg (중상)")}
    names: list[str] = []
    entries, info = goguma_order.prepare_event_entries(
        _csv(ROW_KKUL, ROW_KKUL_5), exclude_keys=issued, skipped_names=names
    )
    assert [e["name"] for e in entries] == ["박민수"]
    assert entries[0]["product"] == "꿀고구마 5Kg (특상)"
    assert info["dup"] == 1 and names == ["홍길동"]


# ── process_from_api: 당첨자만 있는 날도 빈 발주서 생성 ────────────────
def _no_orders(monkeypatch):
    async def fake_collect(_from, _to):
        return []
    monkeypatch.setattr(goguma_auto, "collect_orders", fake_collect)


def test_process_from_api_empty_still_raises_without_winners(monkeypatch):
    _no_orders(monkeypatch)
    with pytest.raises(ValueError):
        asyncio.run(goguma_auto.process_from_api("2026-11-16", "2026-11-16"))


def test_process_from_api_allow_empty_returns_template(monkeypatch):
    _no_orders(monkeypatch)
    xlsx, filename, stats = asyncio.run(
        goguma_auto.process_from_api("2026-11-16", "2026-11-16", allow_empty=True)
    )
    assert stats["total"] == 0 and filename.endswith(".xlsx")
    assert _haedal_rows(xlsx) == []


# ── /api/process/goguma-auto 엔드포인트 ──────────────────────────────
@pytest.fixture
def endpoint(monkeypatch):
    """DB·쿠팡 호출을 가로챈 goguma-auto 실행기. 반환: (run, recorded)."""
    recorded: list[dict] = []
    issued_event: set[str] = set()
    coupang_orders: list[dict] = []

    async def fake_exclusions(section, flag, reissue_stale=True):
        return set(issued_event) if section == goguma_order.EVENT_SECTION else set()

    async def fake_dates(section, flag):
        return {}

    async def fake_stale(section, flag, issued_dates=None):
        return set()

    async def fake_sales(*_a, **_k):
        return None

    async def fake_record(section, order_ids, filename, ymd):
        recorded.append({"section": section, "ids": list(order_ids)})

    async def fake_collect(_from, _to):
        return list(coupang_orders)

    monkeypatch.setattr(api_common, "_issued_exclusions", fake_exclusions)
    monkeypatch.setattr(api_common, "_issued_exclusion_dates", fake_dates)
    monkeypatch.setattr(api_common, "_issued_stale_keys", fake_stale)
    monkeypatch.setattr(api_common, "_goguma_proxy_enabled", lambda: False)
    monkeypatch.setattr(api_common, "record_sales_from_process_stats", fake_sales)
    monkeypatch.setattr(main.database, "record_issued_orders", fake_record)
    monkeypatch.setattr(api_common, "make_excel_response", lambda b, f, s=None: (b, f, s))
    monkeypatch.setattr(goguma_auto, "collect_orders", fake_collect)

    def run(csv_bytes: bytes | None):
        winners = UploadFile(file=BytesIO(csv_bytes), filename="winners_raw.csv") if csv_bytes else None
        return asyncio.run(process_goguma.process_goguma_auto(
            from_date="2026-11-16", to_date="2026-11-16", include_toss="false", send_email="false",
            exclude_issued="true", alwayz_file=None, temu_file=None, winners_file=winners,
            user={"user_id": 1},
        ))

    run.issued_event = issued_event
    run.coupang_orders = coupang_orders
    return run, recorded


def test_endpoint_winners_only_day_produces_order(endpoint):
    run, recorded = endpoint
    xlsx, _filename, stats = run(_csv(ROW_KKUL, ROW_HOBAK))

    assert _haedal_rows(xlsx) == [("홍길동", "꿀고구마 2Kg (중상)", "1")]
    assert stats["event"] == 1 and stats["total"] == 1
    assert any("김철수" in n for n in stats["needs_check"])
    event_rec = [r for r in recorded if r["section"] == goguma_order.EVENT_SECTION]
    assert event_rec and event_rec[0]["ids"] == ["30100000000001|꿀고구마2Kg(중상)"]
    goguma_rec = [r for r in recorded if r["section"] == "goguma"]
    assert goguma_rec and goguma_rec[0]["ids"] == []   # 당첨자는 일반 주문 이력과 섞지 않는다


def test_endpoint_merges_winners_after_coupang_orders(endpoint):
    run, recorded = endpoint
    run.coupang_orders.append({
        "name": "쿠팡고객", "phone": "0502-0000-0000", "zipcode": "12345", "address": "서울 어딘가",
        "quantity": 1, "product": "꿀고구마 3Kg (중상)", "option": "1박스 황금 꿀고구마 3Kg (중상)",
        "memo": "", "order_id": "C100",
    })
    xlsx, _filename, stats = run(_csv(ROW_KKUL))

    assert _haedal_rows(xlsx) == [
        ("쿠팡고객", "꿀고구마 3Kg (중상)", "1"),
        ("홍길동", "꿀고구마 2Kg (중상)", "1"),
    ]
    assert stats["total"] == 2 and stats["coupang"] == 1 and stats["event"] == 1


def test_endpoint_reupload_same_winners_is_blocked(endpoint):
    run, _recorded = endpoint
    run.issued_event.add("30100000000001|꿀고구마2Kg(중상)")
    with pytest.raises(HTTPException) as exc:
        run(_csv(ROW_KKUL))
    assert "이전 발주분 1건" in exc.value.detail and "홍길동" in exc.value.detail
