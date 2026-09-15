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
    """메이크샵 발주용 양식: 1~3행 헤더 유지, 4행부터 상품번호·수량·주문자·수취인."""
    payload = _delivery([
        {"option": "800g 4개", "name": "김철수", "qty": 1, "zipcode": "06236"},
        {"option": "800g 2개", "name": "이영희", "qty": 2, "memo": "부재시 경비실"},
    ])
    out, filename, stats = biseller_order.process(payload)
    assert stats["total"] == 2
    assert filename.startswith("LA한입갈비(") and filename.endswith(").xlsx")
    ws = load_workbook(BytesIO(out)).active
    assert ws.title == "발주용 양식"
    assert [ws.cell(1, c).value for c in (1, 2, 5, 9, 12, 14)] == ["순서", "상품번호", "옵션번호", "수량", "수취인 성명", "우편번호"]
    assert ws.cell(2, 2).value == "goods_no" and ws.cell(3, 2).value == "필수 입력값"
    # 4행: 4세트 → 상품번호 6121
    assert ws.cell(4, 1).value == 1
    assert ws.cell(4, 2).value == 6121 and ws.cell(4, 3).value == "PL0006033"
    assert ws.cell(4, 4).value == "양념LA한입갈비 800g+800g+800g+800g (800G*4세트)"
    assert ws.cell(4, 5).value == 0 and ws.cell(4, 7).value == "무료배송" and ws.cell(4, 8).value == 37800
    assert ws.cell(4, 9).value == 1
    assert ws.cell(4, 10).value == "(주)아이티소프트" and ws.cell(4, 11).value == "010-5700-7756"
    assert ws.cell(4, 12).value == "김철수" and ws.cell(4, 14).value == "06236"
    # 5행: 2세트 → 상품번호 6120, 수량 2, 배송메시지
    assert ws.cell(5, 2).value == 6120 and ws.cell(5, 8).value == 20480
    assert ws.cell(5, 9).value == 2 and ws.cell(5, 12).value == "이영희"
    assert ws.cell(5, 16).value == "부재시 경비실"


def test_many_rows_are_written_sequentially():
    payload = _delivery([{"option": "800g 4개"} for _ in range(60)])
    out, _fn, stats = biseller_order.process(payload)
    assert stats["total"] == 60
    ws = load_workbook(BytesIO(out)).active
    assert ws.cell(4 + 59, 1).value == 60 and ws.cell(4 + 59, 2).value == 6121


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
    # 이벤트 당첨자만 1팩 -> 2세트 승급(비셀러에 1세트 상품이 없다, 2026-09-07)
    assert (
        biseller_order.convert_galbi_option("LA한입갈비 800g 1팩", "", promote_single=True)
        == "양념LA한입갈비 800g+800g (800G*2세트)"
    )
    # 2팩 이상은 승급 대상이 아니다
    assert (
        biseller_order.convert_galbi_option("LA한입갈비 800g 2팩", "", promote_single=True)
        == "양념LA한입갈비 800g+800g (800G*2세트)"
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
    assert filename.startswith("LA한입갈비(") and filename.endswith(").xlsx")
    ws = load_workbook(BytesIO(out)).active
    # 당첨 1팩 → 2세트(상품번호 6120)
    assert ws.cell(4, 12).value == "제원희" and ws.cell(4, 2).value == 6120
    assert ws.cell(4, 4).value == "양념LA한입갈비 800g+800g (800G*2세트)"
    assert ws.cell(4, 9).value == 1 and ws.cell(4, 10).value == "(주)아이티소프트"
    assert ws.cell(5, 12).value == "김이정"
    # 당첨자 CSV엔 우편번호가 없다 → 메이크샵 필수값이라 확인 필요로 알린다
    notes = " / ".join(stats["needs_check"])
    assert "우편번호 없음" in notes and "제원희" in notes


def test_winners_merge_with_coupang_orders_into_one_sheet():
    delivery = _delivery([{"option": "800g 4개", "name": "쿠팡손님"}])
    winners = _winners_csv([
        "LA한입갈비 800g 1팩,닉,2026/09/05 21:03,이벤트손님,010-1111-2222,서울시 어딘가,5102761902313,55800,0,",
    ])
    out, _fn, stats = biseller_order.process(delivery, winners)
    assert stats["total"] == 2 and stats["coupang"] == 1 and stats["event"] == 1
    ws = load_workbook(BytesIO(out)).active
    assert [ws.cell(r, 12).value for r in (4, 5)] == ["쿠팡손님", "이벤트손님"]
    assert [ws.cell(r, 1).value for r in (4, 5)] == [1, 2]


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


def test_coupang_single_pack_is_not_promoted():
    """승급은 이벤트 경로에만 — 쿠팡 1개 주문은 2세트로 늘리지 않고, 상품번호가 없으니 확인 필요로 알린다."""
    payload = _delivery([{"option": "800g 1개", "name": "쿠팡손님"}])
    _out, _fn, stats = biseller_order.process(payload)
    assert stats["total"] == 0
    assert any("쿠팡손님" in m and "1세트" in m for m in stats["needs_check"])


def test_issued_keys_block_coupang_rerun():
    """어제 발주한 쿠팡 주문은 오늘 발주서에서 빠져야 한다."""
    from app.processors import issued_orders

    payload = _delivery([
        {"option": "800g 4개", "name": "어제손님", "order_no": "1111"},
        {"option": "800g 2개", "name": "오늘손님", "order_no": "2222"},
    ])
    _out, _fn, stats = biseller_order.process(payload)
    assert stats["total"] == 2

    # 발주 이력에 기록되는 키(주문번호|옵션)
    keys = set(issued_orders.order_ids_from_stats(stats))
    yesterday = {k for k in keys if k.startswith("1111")}
    names: list[str] = []
    filtered, dropped = issued_orders.filter_delivery_by_issued(payload, yesterday, skipped_names=names)
    assert dropped == 1 and names == ["어제손님"]

    _out2, _fn2, stats2 = biseller_order.process(filtered)
    assert stats2["total"] == 1
    assert stats2["options"][0]["orders"][0]["order_id"] == "2222"


def test_issued_keys_block_winner_rerun():
    """같은 당첨자 CSV를 다시 올려도 이미 발주된 건은 빠진다."""
    from app.processors import issued_orders

    winners = _winners_csv([
        "LA한입갈비 800g 1팩,닉,2026/09/05 21:03,제원희,010-1111-2222,강원도 양구군 어딘가,5102761902313,55800,0,",
        "LA한입갈비 800g 1팩,닉,2026/09/05 21:03,김이정,010-3333-4444,서울시 성북구 어딘가,7102761791873,30800,0,",
    ])
    _out, _fn, stats = biseller_order.process(winners_bytes=winners)
    assert stats["total"] == 2

    keys = set(issued_orders.order_ids_from_stats(stats))
    names: list[str] = []
    _out2, _fn2, stats2 = biseller_order.process(
        winners_bytes=winners, issued_keys=keys, duplicate_names=names
    )
    assert stats2["total"] == 0
    assert stats2["duplicate_skipped"] == 2
    assert sorted(names) == ["김이정", "제원희"]


def test_issued_keys_do_not_block_new_winner():
    from app.processors import issued_orders

    first = _winners_csv([
        "LA한입갈비 800g 1팩,닉,2026/09/05 21:03,제원희,010-1111-2222,강원도 양구군 어딘가,5102761902313,55800,0,",
    ])
    second = _winners_csv([
        "LA한입갈비 800g 1팩,닉,2026/09/05 21:03,제원희,010-1111-2222,강원도 양구군 어딘가,5102761902313,55800,0,",
        "LA한입갈비 800g 2팩,닉,2026/09/06 21:03,새당첨자,010-5555-6666,부산시 어딘가,8102761791999,30800,0,",
    ])
    _out, _fn, stats = biseller_order.process(winners_bytes=first)
    keys = set(issued_orders.order_ids_from_stats(stats))
    _out2, _fn2, stats2 = biseller_order.process(winners_bytes=second, issued_keys=keys)
    assert stats2["total"] == 1 and stats2["duplicate_skipped"] == 1
    assert stats2["options"][0]["orders"][0]["order_id"] == "8102761791999"


# ── 발주 파일명·이메일 (2026-09-07) ──
def test_filename_is_product_name_plus_date():
    """파일명 = 상품명 + 날짜 (2026-09-09 사용자 요청): LA한입갈비(YYYYMMDD).xlsx"""
    import re

    payload = _delivery([{"option": "800g 4개", "name": "김철수"}])
    _out, filename, _stats = biseller_order.process(payload)
    assert re.fullmatch(r"LA한입갈비\(\d{8}\)\.xlsx", filename), filename


def test_biseller_email_target():
    """비셀러 발주 메일은 naeun_order@naver.com."""
    from app import email_service

    target = email_service.ORDER_EMAIL_TARGETS["biseller"]
    assert target["to"] == "naeun_order@naver.com"
    assert "비셀러 상품명" in target["body"]
    # 해달 기본값은 그대로
    assert email_service.ORDER_EMAIL_TARGETS["haedal"]["to"] == "farmers2022@naver.com"
