"""부사사과 제주다팜 발주 (2026-11-16 추가, 쿠팡 DeliveryList만).

쿠팡 '경북 부사사과 정품 실중량' 옵션 '1박스 2kg (중과)' → 제주다팜 판매옵션 '부사 정품 중과 실중량 2kg(8-9과)'
(adminplus pcode 10001479 실측 20종).
"""

from io import BytesIO

import pytest
from openpyxl import Workbook, load_workbook

from app.processors import kolrabi_order

PRODUCT = "경북 부사사과 정품 실중량"


@pytest.mark.parametrize(
    "option, expected",
    [
        ("1박스 2kg (소과)", "부사 정품 소과 실중량 2kg(11-13과)"),
        ("1박스 2kg (중과)", "부사 정품 중과 실중량 2kg(8-9과)"),
        ("1박스 2kg (대과)", "부사 정품 대과 실중량 2kg(5-7과)"),
        ("1박스 3kg (중과)", "부사 정품 중과 실중량 3kg(11-12과)"),
        ("1박스 3kg (대과)", "부사 정품 대과 실중량 3kg(7-9과)"),
        ("1박스 5kg (중과)", "부사 정품 중과 실중량 5kg(18-19과)"),
        ("1박스 5kg (대과)", "부사 정품 대과 실중량 5kg(12-16과)"),
        ("1박스 3kg (중소과)", "부사 정품 중소과 실중량 3kg(13-14과)"),
    ],
)
def test_convert_busa_option(option, expected):
    assert kolrabi_order.convert_busa_option(PRODUCT, option) == expected


def test_busa_unknown_grade_or_other_product_is_not_converted():
    assert kolrabi_order.convert_busa_option(PRODUCT, "1박스 3kg (중대과)") is None  # 제주다팜에 없는 등급
    assert kolrabi_order.convert_busa_option(PRODUCT, "1박스 7kg (중과)") is None
    assert kolrabi_order.convert_busa_option("시나노 골드 사과", "1박스 중과 3kg(9~12과)") is None


def _delivery(rows: list[tuple[str, str, str]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["헤더"] * 31)
    for order_id, product, option in rows:
        row = [""] * 31
        row[2], row[10], row[11], row[22], row[26] = order_id, product, option, 1, "테스트"
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_process_outputs_includes_busa_order_file():
    data = _delivery([
        ("B1", PRODUCT, "1박스 2kg (중과)"),
        ("B2", PRODUCT, "1박스 5kg (대과)"),
        ("S1", "시나노 골드 사과 노란사과 황금사과 경북 가정용 상등급", "1박스 중과 3kg(9~12과)"),
    ])
    outputs = {fn: (b, st) for b, fn, st in kolrabi_order.process_outputs(data)}
    busa = [fn for fn in outputs if "부사사과발주" in fn]
    assert len(busa) == 1
    xlsx, stats = outputs[busa[0]]
    assert stats["total"] == 2
    ws = load_workbook(BytesIO(xlsx)).worksheets[0]
    names = [ws.cell(r, c).value for r in range(2, ws.max_row + 1) for c in range(1, ws.max_column + 1)]
    assert "부사 정품 중과 실중량 2kg(8-9과)" in names and "부사 정품 대과 실중량 5kg(12-16과)" in names
    assert not any("시나노" in str(v) for v in names if v)


@pytest.mark.parametrize(
    "prize, expected",
    [
        ("부사 사과2kg(소과)", "부사 정품 소과 실중량 2kg(11-13과)"),  # 2026-11-16 실제 경품명(원문 그대로 나가던 사고)
        ("부사사과 3kg", "부사 정품 중과 실중량 3kg(11-12과)"),       # 등급 없으면 중과
    ],
)
def test_event_winner_busa_prize_uses_jejudapam_option(prize, expected):
    from app.processors import event_order

    assert event_order.event_product_name(prize) == expected
    assert event_order.event_supplier(prize) == "jejudapam"
    assert event_order._labels_for([expected]) == ["부사사과"]


# ── 부사 운송장 입력(tracking_input) — 2026-11-16 리뷰 1순위: 품목군·의미키 배선 ─────────────
SHINANO = "시나노 골드 사과 노란사과 황금사과 경북 가정용 상등급"


def _tracking_delivery(rows: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    for i, r in enumerate(rows):
        row = i + 2
        ws.cell(row, 3, r.get("order_no", f"OID{i}"))
        ws.cell(row, 11, r["product"])
        ws.cell(row, 12, r["option"])
        ws.cell(row, 23, 1)
        ws.cell(row, 27, r["name"])
        ws.cell(row, 28, r.get("phone", "010-0000-0000"))
        ws.cell(row, 29, "12345")
        ws.cell(row, 30, r.get("address", "서울시 어딘가"))
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _reply(rows: list[tuple[str, str, str, str, str]]) -> bytes:
    """제주다팜 회신(orderlist): (발주명, 받는분, 전화, 주소, 송장)."""
    wb = Workbook()
    ws = wb.active
    for i, (product, name, phone, address, tracking) in enumerate(rows):
        r = i + 2
        ws.cell(r, 5, product)
        ws.cell(r, 11, name)
        ws.cell(r, 13, phone)
        ws.cell(r, 15, address)
        ws.cell(r, 17, "롯데택배")
        ws.cell(r, 18, tracking)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _filled(xlsx: bytes, rows: int) -> list:
    ws = load_workbook(BytesIO(xlsx)).active
    return [ws.cell(r, 5).value for r in range(2, rows + 2)]


def test_busa_semantic_keys_and_family():
    from app.processors.tracking_input import _product_families, _semantic_option_keys

    assert "busa:중과:2kg" in _semantic_option_keys("부사 정품 중과 실중량 2kg(8-9과)", "")
    assert "busa:중과:2kg" in _semantic_option_keys(PRODUCT, "1박스 2kg (중과)")
    assert "busa:소과:2.5kg" in _semantic_option_keys("부사 정품 소과 실중량 2.5kg(13-16과)", "")
    assert "busa" in _product_families(PRODUCT, "1박스 2kg (중과)")
    assert "busa" not in _product_families(SHINANO, "1박스 중과 3kg(9~12과)")


def test_busa_same_person_two_boxes_both_filled():
    from app.processors import tracking_input

    delivery = _tracking_delivery([
        {"product": PRODUCT, "option": "1박스 2kg (중과)", "name": "김부사"},
        {"product": PRODUCT, "option": "1박스 3kg (대과)", "name": "김부사"},
    ])
    reply = _reply([   # 회신 순서는 DeliveryList와 반대
        ("부사 정품 대과 실중량 3kg(7-9과)", "김부사", "010-0000-0000", "서울시 어딘가", "B3"),
        ("부사 정품 중과 실중량 2kg(8-9과)", "김부사", "010-0000-0000", "서울시 어딘가", "B2"),
    ])
    out, _fn, stats = tracking_input.process(reply, delivery)
    assert _filled(out, 2) == ["B2", "B3"]
    assert stats["filled"] == 2


def test_busa_with_other_product_same_person_both_filled():
    from app.processors import tracking_input

    delivery = _tracking_delivery([
        {"product": PRODUCT, "option": "1박스 2kg (중과)", "name": "김부사", "phone": "0504-1111-0001"},
        {"product": SHINANO, "option": "1박스 중과 3kg(9~12과)", "name": "김부사", "phone": "0504-1111-0002"},
    ])
    reply = _reply([
        ("시나노골드(가정용) 중과 3kg(9-12과)", "김부사", "0504-1111-0002", "서울시 어딘가", "S3"),
        ("부사 정품 중과 실중량 2kg(8-9과)", "김부사", "0504-1111-0001", "서울시 어딘가", "B2"),
    ])
    out, _fn, stats = tracking_input.process(reply, delivery)
    assert _filled(out, 2) == ["B2", "S3"]
    assert stats["filled"] == 2


def test_event_busa_tracking_does_not_land_on_same_name_other_product():
    """회신에 섞인 이벤트 부사 당첨자 송장이 이름만 같은 다른 사람의 햇밤 줄에 들어가면 안 된다."""
    from app.processors import tracking_input

    delivery = _tracking_delivery([
        {"product": "햇밤 대 1kg 경북", "option": "1박스 1kg", "name": "김영희", "phone": "0504-2222-0001", "address": "부산시 어딘가"},
    ])
    reply = _reply([
        ("부사 정품 소과 실중량 2kg(11-13과)", "김영희", "010-4444-5555", "서울시 다른곳", "EV1"),
    ])
    out, _fn, stats = tracking_input.process(reply, delivery)
    assert _filled(out, 1) == [None]
    assert stats["filled"] == 0
