"""토스 홍로사과 주문에 제주다팜 회신 송장이 등록돼야 한다 (2026-09-11 실사고).

토스 운송장 자동등록의 상품 필터에 '사과'가 없어 홍로 주문 2건이 걸러졌다.
"""
import asyncio
from io import BytesIO

from openpyxl import Workbook

from app.processors import tomato_tracking

_ORDERLIST_HEADERS = [
    "주문일자", "어드민플러스주문번호", "상품주문번호", "거래처주문번호", "상품명", "옵션", "수량",
    "주문자", "주문자연락처1", "주문자연락처2", "수령인", "수령인연락처2", "수령인연락처1",
    "우편번호", "주소", "배송메모", "택배사", "운송장번호", "공급가", "배송비",
]


def _reply(rows):
    wb = Workbook()
    ws = wb.active
    ws.append(_ORDERLIST_HEADERS)
    for r in rows:
        row = [""] * 20
        row[4] = r["product"]; row[6] = 1; row[7] = "식품애착"; row[8] = "010-5700-7756"
        row[10] = r["name"]; row[12] = r.get("phone", "0508-0000-0000"); row[14] = r.get("address", "서울시 어딘가")
        row[16] = r.get("courier", "롯데택배"); row[17] = r["tracking"]
        ws.append(row)
    buf = BytesIO(); wb.save(buf); return buf.getvalue()


def _toss_order(opid, name, product, option, phone="0508-0000-0000"):
    return {
        "orderProductId": opid, "orderId": "T%d" % opid, "receiverName": name,
        "receiverPhone": phone, "receiverAddress1": "서울시 어딘가",
        "productName": product, "optionName": option, "orderProductStatus": "PAID",
    }


def test_hongro_toss_order_gets_tracking(monkeypatch):
    from app.toss import client as toss_mod

    orders = [
        _toss_order(307866136, "최영아", "2026 햇 안동 고당도 홍로사과 아삭한 꿀사과", "3kg, 1박스, 소과", "0508-7639-7375"),
        _toss_order(307469296, "이병모", "2026 햇 안동 고당도 홍로사과 아삭한 꿀사과", "5kg, 1박스, 대과", "0508-7795-5166"),
    ]
    registered = []

    async def fake_get_orders(**kwargs):
        return orders

    async def fake_register(**kwargs):
        registered.append(kwargs); return {"ok": True}

    monkeypatch.setattr(toss_mod.toss_client, "get_orders", fake_get_orders)
    monkeypatch.setattr(toss_mod.toss_client, "register_tracking", fake_register)

    reply = _reply([
        {"name": "최영아", "phone": "0508-7639-7375", "product": "가을햇사과(홍사과) 가정용 소과 포장재포함 3kg(17-20과내외)", "tracking": "261355948770"},
        {"name": "이병모", "phone": "0508-7795-5166", "product": "가을햇사과(홍사과) 가정용 대과 포장재포함 5kg(16-18과)", "tracking": "261355948744"},
    ])
    stats = asyncio.run(tomato_tracking.process_toss_watermelon_tracking(reply))
    assert stats["toss_orders"] == 2 and stats["toss_success"] == 2, stats
    got = {r["order_product_id"]: r["tracking_number"] for r in registered}
    assert got == {307866136: "261355948770", 307469296: "261355948744"}
