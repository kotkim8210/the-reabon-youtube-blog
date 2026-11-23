"""고구마·호박고구마 화면 — 개인정보 미기재 당첨자를 주문번호로 채운다 (2026-11-23 사용자 요청).

- 꿀고구마(goguma-auto)는 DeliveryList 없이 쿠팡 API로 주문을 모은다 → 쿠팡 발주서 단건 조회(orderId)로 받는 사람·주소를 찾는다.
  실측: 배송완료 주문도 조회되고, 당첨자 CSV '구매 금액' = 품목 orderPrice 합. 다른 계정 주문은 HTTP 400
  '다른 판매자의 주문을 조회할 수 없습니다.'(쿠팡 API 키가 꿀고구마 계정뿐).
- 호박고구마(itsoft001)는 API 키가 없어 같이 올린 DeliveryList에서 찾는다(이전 발주분 제외 전 원본으로).
- 같은 사람 판정은 과일 이벤트 카드와 같다: 이름/별명 70%↑ 또는 구매 금액 = 결제액.
실제 당첨자 개인정보 대신 가짜 데이터를 쓴다.
"""

import asyncio
from io import BytesIO

import httpx
import pytest
from fastapi import UploadFile
from openpyxl import Workbook, load_workbook

from app import api_common, main
from app.coupang import client as coupang_client_module
from app.processors import event_order, goguma_auto, goguma_order, hobak_goguma
from app.routes import process_goguma

HEADER = "경품명,별명,개인 식별 정보 확인,이름,연락처,주소,주문 아이디,구매 금액,환불/취소 금액,환불/날짜/시간"
OID_MISSING = "31100000000011"     # 꿀고구마 당첨 · 개인정보 미기재(별명이 가려진 이름)
OID_NICK = "31100000000012"        # 꿀고구마 당첨 · 별명이 이름과 무관 → 금액으로 판정
OID_OK = "31100000000013"          # 꿀고구마 당첨 · 개인정보 있음 → 조회 안 함
OID_HOBAK = "31100000000014"       # 호박고구마 당첨 · 미기재 → 꿀고구마 화면에선 조회 안 함
ROW_MISSING = f"꿀고구마 중상 2kg,윤**,,,,,{OID_MISSING},13700,0,"
ROW_NICK = f"꿀고구마 특상 3kg,제타로스,,,,,{OID_NICK},17600,0,"
ROW_OK = f"꿀고구마 중상 2kg,홍*동,2026/11/22 14:01,홍길동,010-1111-2222,제주시 테스트로 1,{OID_OK},13700,0,"
ROW_HOBAK = f"호박고구마 중상 2kg,김**,,,,,{OID_HOBAK},12800,0,"


def _csv(*rows: str) -> bytes:
    return ("\n".join((HEADER,) + rows) + "\n").encode("utf-8-sig")


def _sheet(name: str, *, buyer: str | None = None, amount: int = 13700, canceled: bool = False) -> dict:
    """쿠팡 발주서 단건 조회 응답의 묶음배송 1개(실측 키 이름 그대로)."""
    return {
        "shipmentBoxId": 1, "orderId": 0, "status": "FINAL_DELIVERY",
        "orderer": {"name": buyer or name},
        "receiver": {"name": name, "safeNumber": "0504-1234-5678", "addr1": "서울특별시 테스트구 테스트로 7", "addr2": "101호",
                     "postCode": "06236"},
        "parcelPrintMessage": "경비실에 맡겨주세요",
        "orderItems": [{"vendorItemName": "꿀고구마", "orderPrice": amount, "discountPrice": 1000, "canceled": canceled}],
    }


def _other_seller_error() -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://api-gateway.coupang.com/x")
    response = httpx.Response(400, json={"code": 400, "message": "다른 판매자의 주문을 조회할 수 없습니다."}, request=request)
    return httpx.HTTPStatusError("400 Bad Request", request=request, response=response)


class FakeCoupang:
    """get_order_sheets_by_order_id만 흉내 — 주문번호별 응답(묶음 목록) 또는 예외."""

    def __init__(self, orders: dict):
        self.orders = orders
        self.calls: list[str] = []

    async def get_order_sheets_by_order_id(self, order_id: str) -> dict:
        self.calls.append(order_id)
        found = self.orders.get(order_id)
        if isinstance(found, Exception):
            raise found
        return {"code": 200, "message": "OK", "data": found or []}


# ── 쿠팡 응답 → 받는 사람 정보 ─────────────────────────────────────────
def test_coupang_lookup_maps_receiver_phone_zip_memo_amount():
    fake = FakeCoupang({OID_MISSING: [_sheet("윤재호", buyer="윤재호")]})
    lookup = asyncio.run(event_order.lookup_orders_from_coupang([OID_MISSING, OID_MISSING, ""], fake))
    assert fake.calls == [OID_MISSING]                    # 같은 주문번호는 한 번만, 빈 값은 안 묻는다
    assert lookup[OID_MISSING] == {
        "buyer": "윤재호", "receiver": "윤재호", "phone": "0504-1234-5678", "zipcode": "06236",
        "address": "서울특별시 테스트구 테스트로 7 101호", "memo": "경비실에 맡겨주세요", "amount": 13700,
        "source": "쿠팡 주문조회",
    }


def test_coupang_lookup_other_seller_and_canceled_and_empty_become_reasons():
    fake = FakeCoupang({
        "A1": _other_seller_error(),
        "A2": [_sheet("취소손님", canceled=True)],
        "A3": [],
    })
    lookup = asyncio.run(event_order.lookup_orders_from_coupang(["A1", "A2", "A3"], fake))
    assert lookup["A1"]["error"] == "다른 판매자의 주문을 조회할 수 없습니다."
    assert lookup["A2"]["error"] == "취소된 주문"
    assert lookup["A3"]["error"] == "주문 정보 없음"


# ── 꿀고구마: 조회 대상은 미기재 꿀고구마 당첨자만 ─────────────────────────
def test_event_lookup_queries_only_missing_kkul_goguma_winners():
    fake = FakeCoupang({OID_MISSING: [_sheet("윤재호")]})
    lookup = asyncio.run(goguma_order.coupang_event_lookup(_csv(ROW_OK, ROW_MISSING, ROW_HOBAK), client=fake))
    assert fake.calls == [OID_MISSING]                    # 개인정보 있는 당첨자·호박고구마는 묻지 않는다
    assert lookup[OID_MISSING]["receiver"] == "윤재호"
    assert lookup[OID_HOBAK]["error"] == "꿀고구마 경품이 아니라 조회 안 함"


def test_event_lookup_skips_api_when_nobody_is_missing():
    fake = FakeCoupang({})
    assert asyncio.run(goguma_order.coupang_event_lookup(_csv(ROW_OK), client=fake)) is None
    assert fake.calls == []


def test_prepare_fills_masked_nickname_and_amount_match_and_flags_mismatch():
    csv_bytes = _csv(ROW_MISSING, ROW_NICK, "꿀고구마 중상 2kg,여니망,,,,,31100000000015,9900,0,")
    fake = FakeCoupang({
        OID_MISSING: [_sheet("윤재호")],                          # 윤** ↔ 윤재호 → 이름 일치
        OID_NICK: [_sheet("최강유", amount=17600)],              # 별명 무관 + 금액 17,600 같음 → 채움
        "31100000000015": [_sheet("박주현", amount=32900)],      # 별명 무관 + 금액 다름 → 확인 필요
    })
    lookup = asyncio.run(goguma_order.coupang_event_lookup(csv_bytes, client=fake))
    entries, info = goguma_order.prepare_event_entries(csv_bytes, delivery_lookup=lookup)

    assert [(e["name"], e["product"], e["phone"], e["zipcode"], e["memo"]) for e in entries] == [
        ("윤재호", "꿀고구마 2Kg (중상)", "0504-1234-5678", "06236", "경비실에 맡겨주세요"),
        ("최강유", "꿀고구마 3Kg (특상)", "0504-1234-5678", "06236", "경비실에 맡겨주세요"),
    ]
    assert entries[0]["address"] == "서울특별시 테스트구 테스트로 7 101호"
    assert len(info["filled"]) == 2 and all("쿠팡 주문조회" in f for f in info["filled"])
    assert "이름 100% 일치" in info["filled"][0] and "결제액 일치" in info["filled"][1]
    assert len(info["incomplete"]) == 1
    assert "여니망" in info["incomplete"][0] and "쿠팡 주문조회 주문번호는 있으나" in info["incomplete"][0]


def test_missing_info_winners_lists_every_missing_row():
    # 회귀: 미기재 당첨자 목록 변수를 '이름·주소' 문구가 덮어써 두 번째 미기재 줄에서 멈추던 문제
    rows = event_order.missing_info_winners(_csv(ROW_MISSING, ROW_OK, ROW_HOBAK, ROW_NICK))
    assert rows == [
        {"order_id": OID_MISSING, "prize": "꿀고구마 중상 2kg"},
        {"order_id": OID_HOBAK, "prize": "호박고구마 중상 2kg"},
        {"order_id": OID_NICK, "prize": "꿀고구마 특상 3kg"},
    ]


def test_prepare_without_lookup_keeps_old_behavior():
    entries, info = goguma_order.prepare_event_entries(_csv(ROW_OK, ROW_MISSING))
    assert [e["name"] for e in entries] == ["홍길동"] and entries[0]["zipcode"] == ""
    assert info["filled"] == [] and len(info["incomplete"]) == 1 and "이름·주소 없음" in info["incomplete"][0]


# ── /api/process/goguma-auto ─────────────────────────────────────────
@pytest.fixture
def patched_db(monkeypatch):
    """DB·매출 기록을 가로챈다. 반환: 기록된 발주 이력 목록."""
    recorded: list[dict] = []

    async def fake_exclusions(section, flag, reissue_stale=True):
        return set()

    async def fake_dates(section, flag):
        return {}

    async def fake_stale(section, flag, issued_dates=None):
        return set()

    async def fake_sales(*_a, **_k):
        return None

    async def fake_record(section, order_ids, filename, ymd):
        recorded.append({"section": section, "ids": list(order_ids)})

    monkeypatch.setattr(api_common, "_issued_exclusions", fake_exclusions)
    monkeypatch.setattr(api_common, "_issued_exclusion_dates", fake_dates)
    monkeypatch.setattr(api_common, "_issued_stale_keys", fake_stale)
    monkeypatch.setattr(api_common, "_goguma_proxy_enabled", lambda: False)
    monkeypatch.setattr(api_common, "record_sales_from_process_stats", fake_sales)
    monkeypatch.setattr(main.database, "record_issued_orders", fake_record)
    monkeypatch.setattr(api_common, "make_excel_response", lambda b, f, s=None: (b, f, s))
    return recorded


def _haedal_rows(xlsx_bytes: bytes) -> list[tuple]:
    ws = load_workbook(BytesIO(xlsx_bytes)).worksheets[0]
    return [
        (ws.cell(r, 1).value, ws.cell(r, 5).value or None, ws.cell(r, 14).value)
        for r in range(2, ws.max_row + 1)
        if ws.cell(r, 1).value not in (None, "")
    ]


def test_goguma_auto_fills_missing_winner_via_coupang(monkeypatch, patched_db):
    async def no_orders(_from, _to):
        return []

    fake = FakeCoupang({OID_MISSING: [_sheet("윤재호")]})
    monkeypatch.setattr(goguma_auto, "collect_orders", no_orders)
    monkeypatch.setattr(coupang_client_module.coupang_goguma_client, "get_order_sheets_by_order_id",
                        fake.get_order_sheets_by_order_id)

    xlsx, _filename, stats = asyncio.run(process_goguma.process_goguma_auto(
        from_date="2026-11-23", to_date="2026-11-23", include_toss="false", send_email="false",
        exclude_issued="true", alwayz_file=None, temu_file=None,
        winners_file=UploadFile(file=BytesIO(_csv(ROW_OK, ROW_MISSING)), filename="winners_raw.csv"),
        user={"user_id": 1},
    ))

    assert fake.calls == [OID_MISSING]
    assert _haedal_rows(xlsx) == [
        ("홍길동", None, "꿀고구마 2Kg (중상)"),
        ("윤재호", "06236", "꿀고구마 2Kg (중상)"),
    ]
    assert stats["event"] == 2 and stats["total"] == 2
    assert len(stats["filled_from_delivery"]) == 1 and "윤재호" in stats["filled_from_delivery"][0]
    assert not stats.get("needs_check")
    event_rec = [r for r in patched_db if r["section"] == goguma_order.EVENT_SECTION]
    assert sorted(event_rec[0]["ids"]) == sorted([f"{OID_OK}|꿀고구마2Kg(중상)", f"{OID_MISSING}|꿀고구마2Kg(중상)"])


# ── /api/process/hobak-goguma-order: 같이 올린 DeliveryList에서 찾는다 ──────
HOBAK_PRODUCT = "국내산 해남 황토밭 햇 호풍미 호박고구마 판매1위"
HOBAK_OPTION = "1박스 2kg (중상)"


def _delivery(rows: list[dict]) -> bytes:
    """쿠팡 itsoft001 DeliveryList — 표준 열(C 주문번호, S 결제액, Y 구매자, AA~AE 수취인)."""
    wb = Workbook()
    ws = wb.active
    ws.append(["헤더"] * 41)
    for r in rows:
        row = [""] * 41
        row[2], row[3], row[10], row[11] = r["order_no"], "롯데택배", HOBAK_PRODUCT, HOBAK_OPTION
        row[18], row[22], row[24] = r.get("amount", 12800), 1, r["name"]
        row[26], row[27], row[28], row[29], row[30] = r["name"], "0504-9999-0000", "13303", "경기도 성남시 테스트로 9", "문 앞"
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _run_hobak(dl_bytes: bytes | None, csv_bytes: bytes):
    return asyncio.run(process_goguma.process_hobak_goguma_order(
        delivery_file=UploadFile(file=BytesIO(dl_bytes), filename="DeliveryList.xlsx") if dl_bytes else None,
        winners_file=UploadFile(file=BytesIO(csv_bytes), filename="winners_raw.csv"),
        toss_from_date="", toss_to_date="", exclude_issued="true", user={"user_id": 1},
    ))


def test_hobak_order_fills_winner_from_delivery_list_even_if_row_was_issued(monkeypatch, patched_db):
    # 당첨 주문은 이미 발송돼 일반 주문으로는 이전 발주분 — 그래도 받는 사람 찾기엔 원본 DeliveryList를 쓴다
    issued_row_key = f"{OID_HOBAK}|1박스2kg(중상)"

    async def exclusions(section, flag, reissue_stale=True):
        return {issued_row_key} if section == hobak_goguma.SECTION else set()

    monkeypatch.setattr(api_common, "_issued_exclusions", exclusions)
    dl = _delivery([{"order_no": OID_HOBAK, "name": "김민지"}])

    xlsx, _filename, stats = _run_hobak(dl, _csv(ROW_HOBAK))

    assert _haedal_rows(xlsx) == [("김민지", "13303", "호박고구마 2Kg (중상)")]
    assert stats["event"] == 1 and stats["total"] == 1
    assert len(stats["filled_from_delivery"]) == 1 and "이름" in stats["filled_from_delivery"][0]
    assert "쿠팡 주문조회" not in stats["filled_from_delivery"][0]


def test_hobak_order_without_delivery_list_shows_hint(monkeypatch, patched_db):
    _xlsx, _filename, stats = _run_hobak(
        None, _csv("호박고구마 중상 2kg,정*수,2026/11/22,정민수,010-2,서울 2,31100000000016,12800,0,", ROW_HOBAK)
    )
    assert stats["event"] == 1
    assert any("김**" in n and "이름·주소 없음" in n for n in stats["needs_check"])
    assert any("DeliveryList(itsoft001)를 같이 올리면" in n for n in stats["needs_check"])
