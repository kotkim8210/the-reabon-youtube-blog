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
