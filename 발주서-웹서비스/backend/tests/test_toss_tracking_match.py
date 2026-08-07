"""토스 운송장 자동등록 매칭 회귀 (2026-08-07 윤석찬 2건 미등록 사고).

같은 사람이 2건을 주문하면 동명이인 가드가 걸리는데,
 - 회신(제주다팜 orderlist) 상품명 '딱딱이 복숭아 중과 2kg'
 - 토스 옵션 '2kg, 1박스, 중과'
가 문자열로는 안 겹쳐 옵션 매칭이 실패하고, 안심번호도 '0508-7759-7034'(회신) vs
'050877597034'(토스 API)로 표기가 달라 전화 매칭까지 실패 → 2건 모두 skip 됐다.
"""

from io import BytesIO

from openpyxl import Workbook

from app.processors import tomato_tracking as tt

_HEADERS = [
    "주문일자", "어드민플러스주문번호", "상품주문번호", "거래처주문번호", "상품명", "옵션",
    "수량", "주문자", "주문자연락처1", "주문자연락처2", "수령인", "수령인연락처2",
    "수령인연락처1", "우편번호", "주소", "배송메모", "택배사", "운송장번호", "공급가", "배송비",
]


def _orderlist(rows: list[dict]) -> bytes:
    """제주다팜 orderlist(거래처 회신) 형식."""
    wb = Workbook()
    ws = wb.active
    ws.append(_HEADERS)
    for r in rows:
        row = [""] * 20
        row[0] = "2026-08-06"
        row[4] = r["product"]
        row[6] = 1
        row[10] = r["name"]
        row[12] = r["phone"]
        row[14] = r["address"]
        row[16] = r.get("courier", "CJ대한통운")
        row[17] = r["tracking"]
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_reply_entry_has_phone_digits_and_semantic_keys():
    data = _orderlist([
        {"product": "딱딱이 복숭아 중과 2kg", "name": "윤석찬", "phone": "0508-7759-7034",
         "address": "경기도 화성시 동탄지성로 256", "tracking": "699504232636"},
    ])
    entry = tt.parse_reply_file(data)[0]
    assert entry["phone_digits"] == "050877597034"
    assert "baekdo:중과:2kg" in entry["option_keys"]


def test_same_person_two_orders_match_by_option_and_phone(monkeypatch):
    """윤석찬 2건: 등급·kg 의미키와 안심번호로 각각 올바른 송장이 등록된다."""
    data = _orderlist([
        {"product": "딱딱이 복숭아 중과 2kg", "name": "윤석찬", "phone": "0508-7759-7034",
         "address": "경기도 화성시 동탄지성로 256", "tracking": "699504232636", "courier": "CJ대한통운"},
        {"product": "딱딱이 복숭아 대과 4kg", "name": "윤석찬", "phone": "0508-7761-3619",
         "address": "경기도 화성시 동탄지성로 256", "tracking": "44906174810", "courier": "로젠택배"},
    ])

    toss_items = [
        {
            "orderProductId": f"OP{i}",
            "orderId": f"OID{i}",
            "productName": "고당도 햇 백도 딱딱이복숭아 국내산 산지직송",
            "optionName": opt,
            "receiverName": "윤석찬",
            "receiverRealPhone": phone,
            "address": "경기도 화성시 동탄지성로 256",
            "detailAddress": "",
            "orderProductStatus": "PAID",
            "shippingTrackingNumber": None,
        }
        for i, (opt, phone) in enumerate([
            ("2kg, 1박스, 중과", "050877597034"),
            ("4kg, 1박스, 대과", "050877613619"),
        ])
    ]

    async def fake_get_orders(**_kwargs):
        return toss_items

    registered: list[tuple] = []

    async def fake_register(order_product_id, delivery_company, tracking_number):
        registered.append((order_product_id, delivery_company, tracking_number))
        return {"ok": True}

    monkeypatch.setattr(tt.toss_client, "get_orders", fake_get_orders)
    monkeypatch.setattr(tt.toss_client, "register_tracking", fake_register)

    import asyncio

    stats = asyncio.run(tt.process_toss_watermelon_tracking(data))

    assert stats["toss_success"] == 2, stats
    assert stats["toss_skip"] == 0
    assert stats["toss_fail"] == 0
    # 중과 2kg → CJ, 대과 4kg → 로젠 (회신 택배사 그대로)
    assert ("OP0", "CJ대한통운", "699504232636") in registered
    assert ("OP1", "로젠택배", "44906174810") in registered


def test_option_mismatch_still_skips_when_phone_differs(monkeypatch):
    """옵션도 전화도 안 맞으면 잘못 등록하지 말고 건너뛴다(오등록 방지)."""
    data = _orderlist([
        {"product": "딱딱이 복숭아 중과 2kg", "name": "윤석찬", "phone": "0508-1111-1111",
         "address": "경기도 화성시 동탄지성로 256", "tracking": "699504232636"},
        {"product": "딱딱이 복숭아 대과 4kg", "name": "윤석찬", "phone": "0508-2222-2222",
         "address": "경기도 화성시 동탄지성로 256", "tracking": "44906174810"},
    ])
    toss_items = [{
        "orderProductId": "OPX",
        "orderId": "OIDX",
        "productName": "고당도 햇 백도 딱딱이복숭아 국내산 산지직송",
        "optionName": "1kg, 1박스, 소과",   # 회신에 없는 옵션
        "receiverName": "윤석찬",
        "receiverRealPhone": "050899999999",  # 회신에 없는 번호
        "address": "경기도 화성시 동탄지성로 256",
        "detailAddress": "",
        "orderProductStatus": "PAID",
        "shippingTrackingNumber": None,
    }]

    async def fake_get_orders(**_kwargs):
        return toss_items

    async def fake_register(**_kwargs):
        raise AssertionError("등록되면 안 됨")

    monkeypatch.setattr(tt.toss_client, "get_orders", fake_get_orders)
    monkeypatch.setattr(tt.toss_client, "register_tracking", fake_register)

    import asyncio

    stats = asyncio.run(tt.process_toss_watermelon_tracking(data))
    assert stats["toss_success"] == 0
    assert stats["toss_skip"] == 1
