"""비셀러 LA한입갈비 발주 (2026-09 신규)."""

from io import BytesIO

from openpyxl import Workbook, load_workbook

from app.processors import biseller_order

COUPANG_PRODUCT = "한입 LA갈비 양념갈비 구매 1회 특급쉐프소스 양념소갈비"


def _delivery(rows: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    for i, r in enumerate(rows):
        row = i + 2
        ws.cell(row, 3, r.get("order_no", f"OID{i}"))
        ws.cell(row, 11, r.get("product", COUPANG_PRODUCT))
        ws.cell(row, 12, r["option"])
        ws.cell(row, 23, r.get("qty", 1))
        ws.cell(row, 27, r.get("name", f"수취인{i}"))
        ws.cell(row, 28, "010-1234-5678")
        ws.cell(row, 29, r.get("zipcode", "12345"))
        ws.cell(row, 30, "서울시 어딘가 1-2")
        ws.cell(row, 31, r.get("memo", "문 앞"))
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_option_to_biseller_product_name():
    """사용자 샘플 발주서의 실측 표기와 정확히 일치해야 한다."""
    assert (
        biseller_order.convert_galbi_option(COUPANG_PRODUCT, "800g 4개")
        == "양념LA한입갈비 800g+800g+800g+800g (800G*4세트)"
    )
    assert (
        biseller_order.convert_galbi_option(COUPANG_PRODUCT, "800g 2개")
        == "양념LA한입갈비 800g+800g (800G*2세트)"
    )


def test_non_galbi_orders_are_ignored():
    assert biseller_order.convert_galbi_option("콜라비(정품) 3kg", "1박스 3kg") is None
    assert biseller_order.convert_galbi_option("게걸무씨앗기름", "2개 180ml") is None
    assert not biseller_order.is_biseller_galbi_order("2026 햇 안동 홍로사과", "1박스 소과 3kg")


def test_process_fills_template():
    payload = _delivery([
        {"option": "800g 4개", "name": "김철수", "qty": 1, "zipcode": "06236"},
        {"option": "800g 2개", "name": "이영희", "qty": 2, "memo": "부재시 경비실"},
    ])
    out, filename, stats = biseller_order.process(payload)
    assert stats["total"] == 2
    assert filename.startswith("아이티소프트_비셀러발주서_")
    ws = load_workbook(BytesIO(out)).active

    assert ws.cell(1, 7).value == "상품명 (비셀러 상품명)"
    assert ws.cell(2, 1).value == 1 and ws.cell(3, 1).value == 2
    assert ws.cell(2, 3).value == "김철수"
    assert ws.cell(2, 5).value == "06236"
    assert ws.cell(2, 7).value == "양념LA한입갈비 800g+800g+800g+800g (800G*4세트)"
    assert ws.cell(2, 8).value == 1
    assert ws.cell(2, 10).value == "(주)아이티소프트"
    assert ws.cell(2, 11).value == "010-5700-7756"
    assert ws.cell(3, 7).value == "양념LA한입갈비 800g+800g (800G*2세트)"
    assert ws.cell(3, 8).value == 2
    assert ws.cell(3, 9).value == "부재시 경비실"
    # 택배사·송장번호는 거래처가 채우는 칸 → 비어 있어야 한다
    assert ws.cell(2, 12).value in (None, "")
    assert ws.cell(2, 13).value in (None, "")


def test_sum_formula_follows_row_count():
    payload = _delivery([{"option": "800g 4개"} for _ in range(40)])
    out, _fn, stats = biseller_order.process(payload)
    assert stats["total"] == 40
    ws = load_workbook(BytesIO(out)).active
    total_row = next(r for r in range(2, ws.max_row + 1) if ws.cell(r, 7).value == "합계")
    assert total_row == 42  # 2행부터 40건 + 합계
    assert ws.cell(total_row, 8).value == "=SUM(H2:H41)"
    assert ws.cell(41, 7).value == "양념LA한입갈비 800g+800g+800g+800g (800G*4세트)"


def test_unreadable_quantity_is_reported():
    """개수 표기를 못 읽는 갈비 주문이 조용히 사라지면 안 된다."""
    payload = _delivery([
        {"option": "800g 4개", "name": "정상건"},
        {"option": "특대사이즈", "name": "표기이상"},
    ])
    _out, _fn, stats = biseller_order.process(payload)
    assert stats["total"] == 1
    assert len(stats["needs_check"]) == 1 and "표기이상" in stats["needs_check"][0]


# ── 라이브 이벤트 당첨자 CSV → 비셀러 발주서 (2026-09-07) ──
_WINNERS_HEADER = "경품명,별명,개인 식별 정보 확인,이름,연락처,주소,주문 아이디,구매 금액,환불/취소 금액,환불/날짜/시간"


def _winners_csv(rows: list[str]) -> bytes:
    return (chr(10).join([_WINNERS_HEADER] + rows) + chr(10)).encode("utf-8-sig")


def test_event_prize_pack_notation_converts():
    """경품명은 '800g 1팩' 표기 — 쿠팡 '800g N개'와 같은 규칙으로 읽어야 한다."""
    assert (
        biseller_order.convert_galbi_option("LA한입갈비 800g 1팩", "")
        == "양념LA한입갈비 800g (800G*1세트)"
    )
    assert (
        biseller_order.convert_galbi_option("LA한입갈비 800g 2팩", "")
        == "양념LA한입갈비 800g+800g (800G*2세트)"
    )


def test_winners_csv_only_makes_order_sheet():
    data = _winners_csv([
        "LA한입갈비 800g 1팩,투지니맘,2026/09/05 21:03,제원희,010-6724-0907,강원도 양구군 양구읍 관공서로16번길 5-12,5102761902313,55800,0,",
        "LA한입갈비 800g 1팩,김*정,2026/09/05 21:03,김이정,010-6232-6348,서울특별시 성북구 길음로 118 411-103,7102761791873,30800,0,",
    ])
    out, filename, stats = biseller_order.process(winners_bytes=data)
    assert stats["total"] == 2 and stats["event"] == 2 and stats["coupang"] == 0
    assert filename.startswith("아이티소프트_비셀러발주서_")
    ws = load_workbook(BytesIO(out)).active
    assert ws.cell(2, 3).value == "제원희"
    assert ws.cell(2, 7).value == "양념LA한입갈비 800g (800G*1세트)"
    assert ws.cell(2, 8).value == 1
    assert ws.cell(2, 10).value == "(주)아이티소프트"
    assert ws.cell(3, 3).value == "김이정"


def test_winners_merge_with_coupang_orders_into_one_sheet():
    delivery = _delivery([{"option": "800g 4개", "name": "쿠팡손님"}])
    winners = _winners_csv([
        "LA한입갈비 800g 1팩,닉,2026/09/05 21:03,이벤트손님,010-1111-2222,서울시 어딘가,5102761902313,55800,0,",
    ])
    out, _fn, stats = biseller_order.process(delivery, winners)
    assert stats["total"] == 2 and stats["coupang"] == 1 and stats["event"] == 1
    ws = load_workbook(BytesIO(out)).active
    assert [ws.cell(r, 3).value for r in (2, 3)] == ["쿠팡손님", "이벤트손님"]
    assert [ws.cell(r, 1).value for r in (2, 3)] == [1, 2]


def test_refunded_and_other_prizes_are_reported_not_dropped():
    winners = _winners_csv([
        "LA한입갈비 800g 1팩,닉,2026/09/05 21:03,정상건,010-1111-2222,서울시 어딘가,510276,55800,0,",
        "LA한입갈비 800g 1팩,닉,2026/09/05 21:03,환불건,010-3333-4444,서울시 어딘가,510277,55800,55800,2026/09/06 10:00",
        "미니밤호박 1kg,닉,2026/09/05 21:03,다른품목,010-5555-6666,서울시 어딘가,510278,20000,0,",
    ])
    _out, _fn, stats = biseller_order.process(winners_bytes=winners)
    assert stats["total"] == 1
    notes = " / ".join(stats["needs_check"])
    assert "환불" in notes and "다른품목" in notes


def test_requires_at_least_one_file():
    try:
        biseller_order.process()
    except ValueError as exc:
        assert "하나는 올려야" in str(exc)
    else:
        raise AssertionError("파일 없이 처리되면 안 된다")
