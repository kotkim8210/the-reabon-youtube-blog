"""tracking_input 매칭 — 전화 최우선·동일인 다건·동명이인·침묵 skip 금지 (2026-07-14 사고 회귀 방지)."""

from io import BytesIO

from openpyxl import Workbook, load_workbook

from app.processors.tracking_input import process


def _orderlist(rows):
    """rows: [(name, phone, address, courier, tracking)] → orderlist bytes.
    열: K=이름, M=전화, O=주소, Q=택배사, R=운송장 (옵션 열은 비움 — 제주다팜 회신에 옵션 없던 케이스)."""
    wb = Workbook()
    ws = wb.active
    ws.append(["헤더"] * 18)
    for name, phone, addr, courier, tracking in rows:
        row = [""] * 18
        row[10], row[12], row[14], row[16], row[17] = name, phone, addr, courier, tracking
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _delivery(rows):
    """rows: [(name, phone, address, product, option)] → DeliveryList bytes.
    열: AA=이름, AB=전화, AD=주소, K=상품명, L=옵션, E=운송장(비움)."""
    wb = Workbook()
    ws = wb.active
    ws.append(["헤더"] * 31)
    for name, phone, addr, product, option in rows:
        row = [""] * 31
        row[26], row[27], row[29], row[10], row[11] = name, phone, addr, product, option
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _e_column(output_bytes):
    ws = load_workbook(BytesIO(output_bytes)).active
    return [ws.cell(r, 5).value for r in range(2, ws.max_row + 1)]


def test_same_person_multiple_orders_all_filled():
    """동일인 N건(전화 동일, 회신에 옵션정보 없음) → N건 전부 순차 입력.
    옵션 가드가 전화 매칭보다 먼저 걸러 전부 skip되던 2026-07-14 사고의 회귀 테스트."""
    ol = _orderlist([
        ("이현경", "010-1111-2222", "서울 A", "롯데", "255200000001"),
        ("이현경", "010-1111-2222", "서울 A", "롯데", "255200000002"),
        ("이현경", "010-1111-2222", "서울 A", "롯데", "255200000003"),
    ])
    dl = _delivery([
        ("이현경", "01011112222", "서울A", "콜라비", "3kg 1박스"),   # 하이픈 유무 차이
        ("이현경", "01011112222", "서울A", "콜라비", "3kg 1박스"),
        ("이현경", "01011112222", "서울A", "콜라비", "3kg 1박스"),
    ])
    out, _, stats = process(ol, dl)
    assert stats["filled"] == 3 and stats["skipped"] == 0, stats
    assert set(_e_column(out)) == {"255200000001", "255200000002", "255200000003"}


def test_namesake_split_by_phone():
    """동명이인은 전화번호로 정확 분리 — 운송장 뒤바뀜 금지."""
    ol = _orderlist([
        ("김철수", "010-1111-0001", "서울", "롯데", "255200000011"),
        ("김철수", "010-2222-0002", "부산", "롯데", "255200000022"),
    ])
    dl = _delivery([
        ("김철수", "01022220002", "부산", "콜라비", "5kg"),
        ("김철수", "01011110001", "서울", "콜라비", "3kg"),
    ])
    out, _, stats = process(ol, dl)
    assert stats["filled"] == 2, stats
    assert _e_column(out) == ["255200000022", "255200000011"]


def test_namesake_unresolvable_skips_with_names():
    """전화·주소·옵션 어느 것으로도 못 가르면 오배정 대신 미입력 + 이름 표시(침묵 금지)."""
    ol = _orderlist([
        ("박영희", "010-3333-0001", "대구", "롯데", "255200000031"),
        ("박영희", "010-3333-0002", "광주", "롯데", "255200000032"),
    ])
    dl = _delivery([
        ("박영희", "01099999999", "인천", "콜라비", "3kg"),
        ("박영희", "01088888888", "울산", "콜라비", "3kg"),
    ])
    _, _, stats = process(ol, dl)
    assert stats["skipped"] == 2, stats
    assert "박영희" in stats.get("skipped_names", ""), stats


# ── 택배사 표기: 쿠팡은 '우체국'만 인식 (2026-07-27 제주다팜 백도 송장 건) ──
def test_epost_written_as_ucheguk_in_delivery_d_column():
    ol = _orderlist([
        ("김우체", "010-3333-4444", "서울 B", "우체국택배", "6890157378528"),
        ("박씨제", "010-5555-6666", "서울 C", "CJ대한통운", "123456789012"),
        ("최롯데", "010-7777-8888", "서울 D", "롯데택배", "255200000009"),
    ])
    dl = _delivery([
        ("김우체", "01033334444", "서울B", "백도 딱딱이복숭아", "1박스 중과 4kg"),
        ("박씨제", "01055556666", "서울C", "콜라비", "3kg"),
        ("최롯데", "01077778888", "서울D", "콜라비", "3kg"),
    ])
    out, _fn, _stats = process(ol, dl)
    ws = load_workbook(BytesIO(out)).active
    couriers = [ws.cell(r, 4).value for r in range(2, ws.max_row + 1)]
    assert couriers == ["우체국", "CJ 대한통운", "롯데택배"]


def test_coupang_courier_name_variants():
    from app.processors.tracking_match import coupang_courier_name, normalize_courier_name

    for raw in ("우체국택배", "우체국 택배", "우체국등기", "EPOST", "epost", "우체국"):
        assert coupang_courier_name(raw) == "우체국", raw
    assert coupang_courier_name("CJ대한통운") == "CJ 대한통운"
    assert coupang_courier_name("롯데택배") == "롯데택배"
    assert coupang_courier_name(None, "롯데택배") == "롯데택배"
    # 올웨이즈·토스용 공용 정규화는 그대로(그쪽은 '우체국택배' 표기를 씀)
    assert normalize_courier_name("우체국택배") == "우체국택배"


# ── 같은 사람이 여러 상품을 주문 — 한 칸씩 밀려 엉뚱한 송장 (2026-11-02 강본아 사고) ──
_KANG_ADDR = "경기도 양평군 양평읍 남북로 53 102동 1502호 ( 한화 포레나 )"
_KANG_DL = {
    "햇밤": ("국내산 햇밤 생알밤 군밤 찐밤용", "5kg 1박스", "0504-4924-8403"),          # 쥬얼리 상품 — 이 회신에 없음
    "황금향": ("[재구매1위] 제주 황금향 정품 하우스 고당도 평균16brix 산지직송 맛보장", "1박스 2kg (중대)", "0504-3575-0455"),
    "감홍": ("[산지직송] 고당도 경북 문경 감홍사과 가정용 A등급", "1박스 5kg (중과)", "0502-4354-0077"),
    "시나노": ("시나노 골드 사과 노란사과 황금사과 경북 가정용 상등급", "1박스 중과 5kg(15~20과)", "0504-4921-0897"),
}


def _kang_reply():
    """실제 제주다팜 회신 양식(E 상품명·G 수량·H 주문자·I 주문자연락처·K 수령인·M 연락처·N 우편번호·O 주소·Q 택배사·R 운송장).
    이벤트 당첨 황금향 소과는 실제 전화번호·주소 끝 건물명 없음 — 쿠팡 DeliveryList에는 없는 건."""
    entries = [
        ("하우스 정품 황금향 중대과(220~300g) 2kg", "0504-3575-0455", "12561", _KANG_ADDR + " ", "한진택배", "463653260125"),
        ("하우스 정품 황금향 소과(100g~150g) 2kg", "010-3721-3673", None, "경기도 양평군 양평읍 남북로 53 102동 1502호 ", "한진택배", "463653260685"),
        ("감홍사과(가정용 A등급) 중과 5kg(15-20과내외) 포장재포함", "0502-4354-0077", "12561", _KANG_ADDR + " ", "롯데택배", "261706388123"),
        ("시나노골드(가정용) 중과 5kg(15-20과내외) 포장재포함", "0504-4921-0897", "12561", _KANG_ADDR + " ", "롯데택배", "261706388882"),
    ]
    wb = Workbook()
    ws = wb.active
    ws.append(["헤더"] * 22)
    for product, phone, zipcode, addr, courier, tracking in entries:
        row = [""] * 22
        row[4], row[6], row[7], row[8] = product, 1, "식품애착", "010-5700-7756"
        row[10], row[12], row[13], row[14], row[16], row[17] = "강본아", phone, zipcode, addr, courier, tracking
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _kang_delivery(order):
    return _delivery([("강본아", _KANG_DL[k][2], _KANG_ADDR, _KANG_DL[k][0], _KANG_DL[k][1]) for k in order])


def _filled(output_bytes, order):
    ws = load_workbook(BytesIO(output_bytes)).active
    return {k: (ws.cell(r, 4).value, ws.cell(r, 5).value) for r, k in enumerate(order, start=2)}


_KANG_EXPECTED = {
    "햇밤": (None, None),                              # 다른 거래처 상품 → 비워 둠(쥬얼리 송장이 들어갈 자리)
    "황금향": ("한진택배", "463653260125"),
    "감홍": ("롯데택배", "261706388123"),
    "시나노": ("롯데택배", "261706388882"),
}


def test_same_person_many_products_each_gets_own_tracking():
    """강본아(같은 주소)가 햇밤(쥬얼리)+황금향+감홍+시나노를 주문 — 앞 줄 햇밤이 주소만 보고 황금향 송장을 가져가
    황금향→감홍 송장, 감홍→시나노 송장으로 한 칸씩 밀리고 시나노는 비던 사고. 전화(안심번호)가 맞는 송장이 먼저다."""
    order = ["햇밤", "황금향", "감홍", "시나노"]
    out, _fn, stats = process(_kang_reply(), _kang_delivery(order))
    assert _filled(out, order) == _KANG_EXPECTED
    assert stats["filled"] == 3 and stats["skipped"] == 1, stats
    assert "강본아(같은 사람의 다른 상품 행" in stats["skipped_names"], stats


def test_same_person_many_products_any_row_order():
    """DeliveryList 줄 순서가 바뀌어도 결과는 같다(먼저 나온 줄이 송장을 가로채지 않음)."""
    for order in (["시나노", "감홍", "황금향", "햇밤"], ["감홍", "햇밤", "시나노", "황금향"]):
        out, _fn, stats = process(_kang_reply(), _kang_delivery(order))
        assert _filled(out, order) == _KANG_EXPECTED, order
        assert stats["filled"] == 3, (order, stats)


def test_reply_missing_one_product_never_shifts_others():
    """회신에 감홍이 아직 없으면 감홍 줄은 비우고(표시), 다른 상품 송장을 끌어오지 않는다."""
    wb = load_workbook(BytesIO(_kang_reply()))
    wb.active.delete_rows(4)                          # 감홍 회신 줄 제거
    buf = BytesIO()
    wb.save(buf)
    order = ["햇밤", "황금향", "감홍", "시나노"]
    out, _fn, stats = process(buf.getvalue(), _kang_delivery(order))
    got = _filled(out, order)
    assert got["감홍"][1] is None and got["햇밤"][1] is None
    assert got["황금향"] == _KANG_EXPECTED["황금향"] and got["시나노"] == _KANG_EXPECTED["시나노"]
    assert stats["filled"] == 2 and stats["skipped"] == 2, stats
