"""한 주문(묶음배송번호 하나)에 상품이 여러 개 — 거래처가 상품마다 박스·송장을 따로 보내도 송장 하나로 통일.

2026-11-02 파소향: 꿀고구마 3kg(중상)+5kg(특상)을 한 주문으로 받아 해달이 송장 2개 회신 →
같은 묶음에 서로 다른 송장 2개를 올려 쿠팡이 거부, 송장이 하나도 안 들어갔다.
사용자 지시: "송장 2개 중에 하나만 입력" → 묶음의 첫 송장으로 모든 상품 줄을 채운다.
"""

import asyncio
from io import BytesIO

import pytest
from openpyxl import Workbook, load_workbook

from app.processors import goguma_tracking, goguma_tracking_api as gta, hobak_goguma, myeongi_tracking, tracking_input

BOX = "749224152907812"
T1, T2 = "463654701296", "463654701300"
PHONE = "0502-4663-2343"
ADDR = "경기도 파주시 아침노을길 21-3"


def _delivery(rows: list[dict]) -> bytes:
    """쿠팡 DeliveryList: B 묶음배송번호·C 주문번호·D 택배사·E 운송장·K 상품명·L 옵션·AA 이름·AB 전화·AD 주소."""
    wb = Workbook()
    ws = wb.active
    ws.append(["헤더"] * 31)
    for r in rows:
        row = [""] * 31
        row[1], row[2] = r.get("box", BOX), r.get("order_no", "20103995210525")
        row[3], row[4] = r.get("courier", ""), r.get("tracking", "")
        row[10], row[11] = r["product"], r["option"]
        row[26], row[27], row[29] = r.get("name", "파소향"), r.get("phone", PHONE), r.get("address", ADDR)
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _cells(output: bytes) -> list[tuple]:
    ws = load_workbook(BytesIO(output)).active
    return [(ws.cell(r, 4).value, ws.cell(r, 5).value) for r in range(2, ws.max_row + 1)]


def _haedal_reply(rows: list[tuple[str, str]]) -> bytes:
    """해달 한진양식 회신(받으시는 분·전화·총주소·품목명·출고번호=송장)."""
    headers = ["받으시는 분", "받으시는 분 전화", "받는분담당자(선택)", "받는분핸드폰(선택)", "받는분우편번호(선택)",
               "받는분총주소", "보내시는 분", "보내시는 분 전화", "보내는분담당자(선택)", "보내는분담당자HP(선택)",
               "보내는분우편번호(선택)", "보내는분총주소", "수량", "품목명", "운임Type", "지불조건", "출고번호", "특기사항"]
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for product, tracking in rows:
        row = [""] * len(headers)
        row[0], row[1], row[4], row[5] = "파소향", PHONE, "10880", ADDR
        row[6], row[7], row[12], row[13] = "식품애착", "010-5700-7756", 1, product
        row[15], row[16] = "선불", tracking
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


GOGUMA = "[해남직송] 재구매1위 고당도 선별 해남 꿀고구마 베니하루카"


def test_goguma_excel_one_box_two_items_gets_one_tracking():
    delivery = _delivery([
        {"product": GOGUMA, "option": "1박스 황금 꿀고구마 3Kg (중상)"},
        {"product": GOGUMA, "option": "1박스 황금 꿀고구마 5Kg (특상)"},
    ])
    reply = _haedal_reply([("꿀고구마 3Kg (중상)", T1), ("꿀고구마 5Kg (특상)", T2)])
    out, _fn, stats = goguma_tracking.process(reply, delivery)
    assert [t for _c, t in _cells(out)] == [T1, T1]
    assert stats["filled"] == 2 and "파소향" in stats["한주문송장통일"]


def test_hobak_excel_one_box_two_items_gets_one_tracking():
    product = "해남 햇 호박고구마"
    delivery = _delivery([
        {"product": product, "option": "1박스 3kg (중상)", "courier": "롯데택배"},
        {"product": product, "option": "1박스 5kg (특상)", "courier": "롯데택배"},
    ])
    reply = _haedal_reply([("호박고구마 3kg (중상)", T1), ("호박고구마 5kg (특상)", T2)])
    out, _fn, stats = hobak_goguma.process_tracking(reply, delivery)
    cells = _cells(out)
    assert [t for _c, t in cells] == [T1, T1] and cells[0][0] == cells[1][0]
    assert "파소향" in stats["한주문송장통일"]


def _jeju_reply(rows: list[tuple[str, str]]) -> bytes:
    """제주다팜 회신 실제 양식(E 상품명·K 수령인·M 연락처·O 주소·Q 택배사·R 운송장)."""
    wb = Workbook()
    ws = wb.active
    ws.append(["헤더"] * 22)
    for product, tracking in rows:
        row = [""] * 22
        row[4], row[6], row[7], row[8] = product, 1, "식품애착", "010-5700-7756"
        row[10], row[12], row[14], row[16], row[17] = "파소향", PHONE, ADDR, "롯데택배", tracking
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


SHINANO = "시나노 골드 사과 노란사과 황금사과 경북 가정용 상등급"


def test_jejudapam_one_box_two_items_gets_one_tracking():
    delivery = _delivery([
        {"product": SHINANO, "option": "1박스 중과 5kg(15~20과)"},
        {"product": SHINANO, "option": "1박스 소과 2kg 10~13과(한입)"},
    ])
    reply = _jeju_reply([("시나노골드(가정용) 중과 5kg(15-20과내외) 포장재포함", T1),
                         ("시나노골드(가정용) 소과 2kg(10-13과내외) 포장재포함", T2)])
    out, _fn, stats = tracking_input.process(reply, delivery)
    assert _cells(out) == [("롯데택배", T1), ("롯데택배", T1)]
    assert stats["filled"] == 2 and "파소향" in stats["한주문송장통일"]


def test_prefilled_row_of_same_box_is_not_overwritten():
    """다른 거래처 회신으로 이미 채운 줄은 건드리지 않는다 — 이번에 채운 줄끼리만 통일."""
    delivery = _delivery([
        {"product": "국내산 햇밤 생알밤 군밤 찐밤용", "option": "5kg 1박스", "courier": "CJ 대한통운", "tracking": "601227536343"},
        {"product": SHINANO, "option": "1박스 중과 5kg(15~20과)"},
    ])
    reply = _jeju_reply([("시나노골드(가정용) 중과 5kg(15-20과내외) 포장재포함", T1)])
    out, _fn, stats = tracking_input.process(reply, delivery)
    assert _cells(out) == [("CJ 대한통운", "601227536343"), ("롯데택배", T1)]
    assert "한주문송장통일" not in stats


def test_jewelry_one_box_two_items_gets_one_tracking():
    chestnut = "국내산 햇밤 생알밤 군밤 찐밤용"
    delivery = _delivery([
        {"product": chestnut, "option": "1kg 1박스", "order_no": "18103968297988"},
        {"product": chestnut, "option": "2kg 1박스", "order_no": "18103968297988"},
    ])
    wb = Workbook()
    ws = wb.active
    for i, (product, tracking) in enumerate((("햇밤 대 1kg", T1), ("햇밤 대 2kg", T2)), start=2):
        ws.cell(i, 4, "18103968297988")   # D 거래처주문번호
        ws.cell(i, 7, product)            # G 상품명
        ws.cell(i, 11, "파소향")           # K 수령인
        ws.cell(i, 13, PHONE)             # M 연락처
        ws.cell(i, 15, ADDR)              # O 주소
        ws.cell(i, 17, "CJ대한통운")        # Q 택배사
        ws.cell(i, 18, tracking)          # R 운송장
    buf = BytesIO()
    wb.save(buf)
    out, _fn, stats = myeongi_tracking.process(buf.getvalue(), delivery)
    assert [t for _c, t in _cells(out)] == [T1, T1]
    assert "파소향" in stats["한주문송장통일"]


class _FakeClient:
    def __init__(self):
        self.upload_calls: list[list[dict]] = []

    async def confirm_orders(self, shipment_box_ids):
        return {"code": 200}

    async def upload_invoices(self, dtos):
        self.upload_calls.append(dtos)
        return {"code": 200, "data": {"responseList": []}}


async def _no_sleep(_seconds):
    return None


def test_coupang_api_one_box_two_items_registers_one_invoice(monkeypatch):
    """쿠팡 API로 등록할 때도 같은 묶음(shipmentBoxId)은 송장 하나 — 상품 2개 모두 첫 송장으로."""
    client = _FakeClient()
    monkeypatch.setattr(gta, "coupang_goguma_client", client)
    monkeypatch.setattr(gta.asyncio, "sleep", _no_sleep)

    def order(item_id, option):
        return {"shipment_box_id": int(BOX), "order_id": 20103995210525, "vendor_item_id": item_id,
                "name": "파소향", "phone": "050246632343", "address": "경기도파주시아침노을길21-3",
                "name_display": "파소향", "order_status": "INSTRUCT", "option_keys": {option}}

    def entry(option, tracking):
        return {"name": "파소향", "phone": "050246632343", "address": "", "tracking": tracking,
                "delivery_company_code": "HANJIN", "option_keys": {option}}

    monkeypatch.setattr(gta, "parse_haedal_file", lambda _b: [entry("꿀고구마3Kg(중상)", T1), entry("꿀고구마5Kg(특상)", T2)])

    async def fake_fetch():
        return [order(94707754634, "[해남직송]…황금꿀고구마3Kg(중상)"), order(94707754635, "[해남직송]…황금꿀고구마5Kg(특상)")]
    monkeypatch.setattr(gta, "fetch_pending_orders", fake_fetch)

    result = asyncio.run(gta.process_tracking_api(b"fake"))
    dtos = client.upload_calls[0]
    assert [(d["vendorItemId"], d["invoiceNumber"]) for d in dtos] == [(94707754634, T1), (94707754635, T1)]
    assert result["success"] == 2 and result["fail"] == 0
    assert all(T2 in r["message"] and "하나로" in r["message"] for r in result["results"])
