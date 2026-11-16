"""토스 송장 자동등록 — 이름만 같으면 남의 주문에 송장을 넣던 문제 (2026-11-16 리뷰 2순위).

과일(tomato_tracking.process_toss_watermelon_tracking)·꿀/호박고구마(toss_auto.process_toss_tracking) 모두
품목·전화(숫자만)·주소·옵션으로 같은 주문인지 확인한 뒤에만 등록하고, 아니면 사유를 남기고 건너뛴다.
실제 고객 대신 가짜 이름·번호를 쓰고, 토스 API는 가짜 클라이언트로 바꾼다(실제 호출 없음).
"""

import asyncio
from io import BytesIO

import pytest
from openpyxl import Workbook

from app.processors import tomato_tracking as tt
from app.processors import toss_auto


class _FakeToss:
    """get_orders는 주어진 목록(또는 None·예외), register_tracking은 기록. fail[opid]=None이면 응답 없음, 예외면 던짐."""

    def __init__(self, orders, fail=None):
        self._orders = orders
        self.fail = fail or {}
        self.attempted = []
        self.registered = []

    async def get_orders(self, start_date=None, end_date=None, status=None):
        if isinstance(self._orders, Exception):
            raise self._orders
        return self._orders

    async def register_tracking(self, order_product_id, delivery_company, tracking_number):
        self.attempted.append(order_product_id)
        if order_product_id in self.fail:
            outcome = self.fail[order_product_id]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        self.registered.append((order_product_id, delivery_company, tracking_number))
        return {"resultType": "SUCCESS"}


def _toss(opid, name, product, option, phone, address, tracking=None, status="PAID"):
    return {
        "orderProductId": opid, "orderId": f"T-{opid}", "productName": product, "optionName": option,
        "receiverName": name, "receiverRealPhone": phone, "address": address, "detailAddress": "",
        "orderProductStatus": status, "shippingTrackingNumber": tracking,
    }


# ── 과일: 쥬얼리·제주다팜 orderlist 회신 ──
_ORDERLIST_HEADERS = [
    "주문일자", "어드민플러스주문번호", "상품주문번호", "거래처주문번호", "상품명", "옵션",
    "수량", "주문자", "주문자연락처1", "주문자연락처2", "수령인", "수령인연락처2",
    "수령인연락처1", "우편번호", "주소", "배송메모", "택배사", "운송장번호", "공급가", "배송비",
]


def _fruit_reply(rows: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(_ORDERLIST_HEADERS)
    for r in rows:
        row = [""] * 20
        row[0] = "2026-11-16"
        row[4] = r["product"]
        row[6] = 1
        row[10] = r["name"]
        row[12] = r["phone"]
        row[14] = r["address"]
        row[16] = r.get("courier", "")
        row[17] = r["tracking"]
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _run_fruit(monkeypatch, reply_rows, toss_items, fail=None):
    fake = _FakeToss(toss_items, fail)
    monkeypatch.setattr(tt, "toss_client", fake)
    stats = asyncio.run(tt.process_toss_watermelon_tracking(_fruit_reply(reply_rows)))
    return fake, stats


KOLRABI = "제주 콜라비 산지직송"
HWANGGEUM = "[재구매1위] 제주 황금향 정품 하우스 고당도 평균16brix 산지직송 맛보장"
SHINANO = "시나노 골드 사과 노란사과 황금사과 경북 가정용 상등급"


def test_fruit_families_jewelry_items_and_chestnut_vs_bamhobak():
    """쥬얼리 품목도 품목군을 안다. '햇 밤호박'은 햇밤이 아니다."""
    assert tt._fruit_families("가정용 수박 7kg 내외") == {"watermelon"}
    assert tt._fruit_families("햇밤 대 2kg") == {"chestnut"}
    assert tt._fruit_families("2026 햇 밤호박 보우짱", "1kg") == {"bamhobak"}
    assert tt._fruit_families("하우스 정품 황금향 소과(100g~150g) 2kg") == {"hwanggeum"}
    assert tt._fruit_families("", None) == set()


def test_fruit_other_customer_same_name_other_product_not_registered(monkeypatch):
    """(1) 쥬얼리 회신의 쿠팡 고객 이수진(수박) 송장이 토스의 다른 이수진(콜라비) 주문에 들어가면 안 된다."""
    fake, stats = _run_fruit(monkeypatch, [
        {"product": "가정용 수박 7kg 내외", "name": "이수진", "phone": "0504-2222-3333",
         "address": "광주광역시 북구 테스트로 1", "courier": "롯데택배", "tracking": "261700000001"},
    ], [
        _toss("OP-KOL-1", "이수진", KOLRABI, "3kg", "01077778888", "인천광역시 남동구 테스트로 2"),
    ])
    assert fake.registered == []
    assert stats["toss_success"] == 0 and stats["toss_skip"] == 1, stats
    assert stats["토스 미등록 사유"] == "이수진(다른 상품 송장뿐 — 이 회신에 없음)"


def test_fruit_same_person_kolrabi_and_watermelon_only_watermelon_gets_it(monkeypatch):
    """(2) 박토스가 토스로 콜라비+수박, 쥬얼리 회신엔 수박만 → 수박 주문에만 등록, 콜라비는 건너뜀."""
    phone, addr = "050810002000", "서울특별시 강서구 테스트로 3"
    fake, stats = _run_fruit(monkeypatch, [
        {"product": "가정용 수박 7kg 내외", "name": "박토스", "phone": "0508-1000-2000",
         "address": addr, "courier": "롯데택배", "tracking": "261700000002"},
    ], [
        _toss("OP-KOL-2", "박토스", KOLRABI, "3kg", phone, addr),
        _toss("OP-WM-2", "박토스", "고당도 수박 7kg", "7kg", phone, addr),
    ])
    assert fake.registered == [("OP-WM-2", "롯데택배", "261700000002")]
    assert stats["toss_success"] == 1 and stats["toss_skip"] == 1, stats


def test_fruit_same_person_hwanggeum_and_shinano_not_swapped(monkeypatch):
    """(3) 박토스 황금향+시나노, 제주다팜 회신 2줄(시나노 먼저) → 각 주문에 자기 송장·택배사."""
    phone, addr = "050830004000", "서울특별시 마포구 테스트로 4"
    fake, stats = _run_fruit(monkeypatch, [
        {"product": "시나노골드(가정용) 소과 2kg(10-13과내외)", "name": "박토스", "phone": "0508-3000-4000",
         "address": addr, "courier": "롯데택배", "tracking": "254000000003"},
        {"product": "하우스 정품 황금향 소과(100g~150g) 2kg", "name": "박토스", "phone": "0508-3000-4000",
         "address": addr, "courier": "한진택배", "tracking": "512000000003"},
    ], [
        _toss("OP-HG-3", "박토스", HWANGGEUM, "1박스 2kg (소)", phone, addr),
        _toss("OP-SN-3", "박토스", SHINANO, "1박스 소과 2kg 10~13과(한입)", phone, addr),
    ])
    assert sorted(fake.registered) == [
        ("OP-HG-3", "한진택배", "512000000003"),
        ("OP-SN-3", "롯데택배", "254000000003"),
    ]
    assert stats["toss_success"] == 2 and not stats.get("toss_courier_warnings"), stats


def test_fruit_namesake_chestnut_not_on_kolrabi(monkeypatch):
    """(4) 토스 김철수(서울) 콜라비 ↔ 쥬얼리 회신의 다른 김철수(부산) 햇밤 송장 → 등록하지 않고 사유를 남긴다."""
    fake, stats = _run_fruit(monkeypatch, [
        {"product": "햇밤 대 2kg", "name": "김철수", "phone": "0507-9999-0000",
         "address": "부산광역시 해운대구 테스트로 5", "courier": "CJ대한통운", "tracking": "561000000004"},
    ], [
        _toss(9001, "김철수", KOLRABI, "3kg", "050812345678", "서울특별시 종로구 테스트로 6"),
    ])
    assert fake.registered == []
    assert stats["toss_skip"] == 1 and "김철수(" in stats["토스 미등록 사유"], stats


def test_fruit_name_only_same_product_skips_with_reason(monkeypatch):
    """같은 상품이어도 전화·주소·옵션이 하나도 안 맞으면(이름만 같음) 등록하지 않는다."""
    fake, stats = _run_fruit(monkeypatch, [
        {"product": "콜라비 정품 3kg", "name": "최동명", "phone": "0504-1212-3434",
         "address": "대전광역시 서구 테스트로 7", "courier": "롯데택배", "tracking": "261700000005"},
    ], [
        _toss("OP-KOL-5", "최동명", KOLRABI, "5kg", "01056567878", "대구광역시 중구 테스트로 8"),
    ])
    assert fake.registered == []
    assert stats["토스 미등록 사유"] == "최동명(이름만 같음(전화·주소·옵션 다름) — 수동 확인)"


def test_fruit_normal_match_still_registers(monkeypatch):
    """같은 이름·같은 전화(하이픈 차이)·같은 상품은 그대로 등록된다."""
    fake, stats = _run_fruit(monkeypatch, [
        {"product": "콜라비 정품 3kg", "name": "정상인", "phone": "0508-2222-1111",
         "address": "서울특별시 성동구 테스트로 10", "courier": "롯데택배", "tracking": "261700000010"},
    ], [
        _toss("OP-KOL-10", "정상인", KOLRABI, "3kg", "050822221111", "서울특별시 성동구 테스트로 10"),
    ])
    assert fake.registered == [("OP-KOL-10", "롯데택배", "261700000010")]
    assert stats["toss_success"] == 1 and stats["toss_skip"] == 0 and "토스 미등록 사유" not in stats


def test_fruit_blank_courier_defaults_by_product(monkeypatch):
    """회신 택배사 칸이 비면 품목별 기본값: 햇밤=CJ대한통운, 황금향=한진택배, 나머지=롯데택배."""
    fake, stats = _run_fruit(monkeypatch, [
        {"product": "햇밤 대 2kg", "name": "정햇밤", "phone": "0508-5555-6666",
         "address": "경기도 수원시 테스트로 9", "tracking": "561000000007"},
        {"product": "하우스 정품 황금향 소과(100g~150g) 2kg", "name": "한황금", "phone": "0508-5555-7777",
         "address": "제주특별자치도 제주시 테스트로 10", "tracking": "512000000008"},
        {"product": "콜라비 정품 3kg", "name": "노콜라", "phone": "0508-5555-8888",
         "address": "서울특별시 중구 테스트로 11", "tracking": "261700000009"},
    ], [
        _toss("OP-CN", "정햇밤", "햇밤 국내산 알밤 산지직송", "2kg 대", "050855556666", "경기도 수원시 테스트로 9"),
        _toss("OP-HG", "한황금", HWANGGEUM, "1박스 2kg (소)", "050855557777", "제주특별자치도 제주시 테스트로 10"),
        _toss("OP-KO", "노콜라", KOLRABI, "3kg", "050855558888", "서울특별시 중구 테스트로 11"),
    ])
    assert sorted(fake.registered) == [
        ("OP-CN", "CJ대한통운", "561000000007"),
        ("OP-HG", "한진택배", "512000000008"),
        ("OP-KO", "롯데택배", "261700000009"),
    ]
    assert not stats.get("toss_courier_warnings"), stats


def test_fruit_register_none_or_error_counts_as_fail_and_continues(monkeypatch):
    """등록 응답 없음(None)·예외는 실패(사유 포함)로 세고 다음 건을 계속 등록한다."""
    rows, items = [], []
    for i, name in enumerate(("가응답", "나예외", "다정상")):
        phone = f"0508-7000-000{i}"
        rows.append({"product": "콜라비 정품 3kg", "name": name, "phone": phone,
                     "address": f"서울특별시 테스트로 {i}", "courier": "롯데택배", "tracking": f"26170000010{i}"})
        items.append(_toss(f"OP-{i}", name, KOLRABI, "3kg", phone.replace("-", ""), f"서울특별시 테스트로 {i}"))
    fake, stats = _run_fruit(monkeypatch, rows, items, fail={"OP-0": None, "OP-1": RuntimeError("연결 끊김")})
    assert fake.attempted == ["OP-0", "OP-1", "OP-2"]
    assert fake.registered == [("OP-2", "롯데택배", "261700000102")]
    assert stats["toss_success"] == 1 and stats["toss_fail"] == 2, stats
    detail = stats["토스 등록 실패"]
    assert "가응답 261700000100(토스 응답 없음" in detail and "나예외 261700000101(연결 끊김)" in detail


@pytest.mark.parametrize("outcome, needle", [(None, "응답 없음"), (RuntimeError("점검 중"), "점검 중")])
def test_fruit_order_lookup_failure_raises(monkeypatch, outcome, needle):
    """주문 목록 조회가 None·예외면 '대상 없음'으로 넘기지 말고 오류로 멈춘다."""
    fake = _FakeToss(outcome)
    monkeypatch.setattr(tt, "toss_client", fake)
    reply = _fruit_reply([{"product": "콜라비 정품 3kg", "name": "아무개", "phone": "0508-0000-0001",
                           "address": "서울", "tracking": "261700000011"}])
    with pytest.raises(ValueError, match="토스 주문 조회 실패") as err:
        asyncio.run(tt.process_toss_watermelon_tracking(reply))
    assert needle in str(err.value)
    assert fake.attempted == []


def test_fruit_counts_without_double_skip(monkeypatch):
    """toss_orders = 성공+실패+건너뜀 (매칭 단계 건너뜀을 두 번 세지 않는다)."""
    fake, stats = _run_fruit(monkeypatch, [
        {"product": "콜라비 정품 3kg", "name": "홍길동", "phone": "0508-1111-0000",
         "address": "서울특별시 테스트로 12", "courier": "롯데택배", "tracking": "261700000012"},
    ], [
        _toss("OP-M", "홍길동", KOLRABI, "3kg", "050811110000", "서울특별시 테스트로 12"),
        _toss("OP-N", "김없음", KOLRABI, "5kg", "050811119999", "부산광역시 테스트로 13"),
        _toss("OP-T", "이미송장", KOLRABI, "3kg", "050811118888", "대구광역시 테스트로 14", tracking="261799999999"),
    ])
    assert fake.registered == [("OP-M", "롯데택배", "261700000012")]
    assert (stats["toss_orders"], stats["toss_success"], stats["toss_fail"], stats["toss_skip"]) == (3, 1, 0, 2)


# ── 꿀·호박고구마: 해달 회신 ──
_HANJIN_HEADERS = [
    "받으시는 분", "받으시는 분 전화", "받는분담당자(선택)", "받는분핸드폰(선택)",
    "받는분우편번호(선택)", "받는분총주소", "보내시는 분", "보내시는 분 전화",
    "보내는분담당자(선택)", "보내는분담당자HP(선택)", "보내는분우편번호(선택)", "보내는분총주소",
    "수량", "품목명", "운임Type", "지불조건", "출고번호", "특기사항", "메모1", "메모2", "메모3", "메모4",
]


def _haedal_reply(rows: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(_HANJIN_HEADERS)
    for r in rows:
        row = [""] * 22
        row[0] = r["name"]
        row[1] = r["phone"]
        row[5] = r["address"]
        row[6] = "식품애착"
        row[12] = 1
        row[13] = r["product"]
        row[15] = "선불"
        row[16] = r["tracking"]
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


KKUL = "해남 황금 꿀고구마"


def _run_goguma(monkeypatch, reply_rows, toss_items, fail=None):
    fake = _FakeToss(toss_items, fail)
    monkeypatch.setattr(toss_auto, "toss_client", fake)
    result = asyncio.run(toss_auto.process_toss_tracking(_haedal_reply(reply_rows)))
    return fake, result


def _messages(result: dict, status: str) -> dict:
    return {r["name"]: r["message"] for r in result["results"] if r["status"] == status}


def test_goguma_hyphen_phone_pairs_each_box(monkeypatch):
    """회신 '0508-1111-2222'와 토스 '050811112222'는 같은 번호 — 같은 사람 두 박스가 각자 송장을 받는다."""
    addr = "서울특별시 송파구 테스트로 1"
    fake, result = _run_goguma(monkeypatch, [
        {"name": "박고구마", "phone": "0508-3333-4444", "address": addr, "product": "꿀고구마 3Kg (중상)", "tracking": "463300000002"},
        {"name": "박고구마", "phone": "0508-1111-2222", "address": addr, "product": "꿀고구마 3Kg (중상)", "tracking": "463300000001"},
    ], [
        _toss("OP-A", "박고구마", KKUL, "3kg 중상", "050811112222", addr),
        _toss("OP-B", "박고구마", KKUL, "3kg 중상", "050833334444", addr),
    ])
    assert sorted(fake.registered) == [("OP-A", "한진택배", "463300000001"), ("OP-B", "한진택배", "463300000002")]
    assert result["success"] == 2 and result["skip"] == 0, result


def test_goguma_namesake_name_only_skips_with_reason(monkeypatch):
    """동명이인: 이름만 같고 전화·옵션이 다르면 등록하지 않는다."""
    fake, result = _run_goguma(monkeypatch, [
        {"name": "이고구마", "phone": "0504-5555-6666", "address": "부산광역시 테스트로 2",
         "product": "꿀고구마 5Kg (특상)", "tracking": "463300000003"},
    ], [
        _toss("OP-C", "이고구마", KKUL, "3kg 중상", "01011112222", "서울특별시 테스트로 3"),
    ])
    assert fake.registered == []
    assert result["skip"] == 1 and result["success"] == 0, result
    assert _messages(result, "skip") == {"이고구마": "이름만 같음(전화·옵션 다름) — 수동 확인"}


def test_goguma_same_person_two_boxes_coupang_line_not_used(monkeypatch):
    """같은 사람이 같은 주소로 쿠팡(3kg)·토스(3kg+5kg) 주문 — 토스 박스 송장만 옵션별로 1:1."""
    addr = "대구광역시 테스트로 4"
    fake, result = _run_goguma(monkeypatch, [
        {"name": "최고구마", "phone": "0504-7777-8888", "address": addr, "product": "꿀고구마 3Kg (중상)", "tracking": "463300000004"},
        {"name": "최고구마", "phone": "010-2222-3333", "address": addr, "product": "꿀고구마 5Kg (특상)", "tracking": "463300000005"},
        {"name": "최고구마", "phone": "010-2222-3333", "address": addr, "product": "꿀고구마 3Kg (중상)", "tracking": "463300000006"},
    ], [
        _toss("OP-D", "최고구마", KKUL, "3kg 중상", "01022223333", addr),
        _toss("OP-E", "최고구마", KKUL, "5kg 특상", "01022223333", addr),
    ])
    assert sorted(fake.registered) == [("OP-D", "한진택배", "463300000006"), ("OP-E", "한진택배", "463300000005")]


def test_goguma_kkul_order_not_given_hobak_box(monkeypatch):
    """같은 사람·같은 번호라도 호박고구마 박스 송장을 꿀고구마 주문에 넣지 않는다."""
    addr = "경기도 평택시 테스트로 5"
    fake, result = _run_goguma(monkeypatch, [
        {"name": "문고구마", "phone": "0502-1546-0000", "address": addr, "product": "호박고구마 2Kg (한입)", "tracking": "463300000007"},
    ], [
        _toss("OP-K", "문고구마", KKUL, "2kg 한입", "050215460000", addr),
    ])
    assert fake.registered == []
    assert _messages(result, "skip") == {"문고구마": "다른 상품 송장뿐 — 이 회신에 없음"}


def test_goguma_register_none_or_error_counts_as_fail_and_continues(monkeypatch):
    rows, items = [], []
    for i, name in enumerate(("가고구마", "나고구마", "다고구마")):
        rows.append({"name": name, "phone": f"010-4000-000{i}", "address": f"서울 {i}",
                     "product": "꿀고구마 3Kg (중상)", "tracking": f"46330000010{i}"})
        items.append(_toss(f"OP-{i}", name, KKUL, "3kg 중상", f"0104000000{i}", f"서울 {i}"))
    fake, result = _run_goguma(monkeypatch, rows, items, fail={"OP-0": None, "OP-1": RuntimeError("연결 끊김")})
    assert fake.attempted == ["OP-0", "OP-1", "OP-2"]
    assert fake.registered == [("OP-2", "한진택배", "463300000102")]
    assert result["success"] == 1 and result["fail"] == 2, result
    fails = _messages(result, "fail")
    assert "응답 없음" in fails["가고구마"] and "연결 끊김" in fails["나고구마"]


def test_goguma_order_lookup_none_raises(monkeypatch):
    fake = _FakeToss(None)
    monkeypatch.setattr(toss_auto, "toss_client", fake)
    reply = _haedal_reply([{"name": "아무개", "phone": "010-0000-0001", "address": "서울",
                            "product": "꿀고구마 3Kg (중상)", "tracking": "463300000011"}])
    with pytest.raises(ValueError, match="토스 API 조회 실패"):
        asyncio.run(toss_auto.process_toss_tracking(reply))
    assert fake.attempted == []


# ── 검토 지적 보완 (2026-11-16): 품목군 세분화·같은 회신 재업로드·배송메모 택배사·kg 다른 옵션·전화 다른 동명이인 ──
def test_fruit_same_person_kolrabi_and_geobando_only_geobando_gets_it(monkeypatch):
    """거반도 발주명엔 '복숭아'가 없어도 품목을 안다 — 콜라비+거반도 주문에 거반도 송장이 콜라비로 가지 않는다."""
    phone, addr = "050810003000", "서울특별시 강동구 테스트로 21"
    fake, stats = _run_fruit(monkeypatch, [
        {"product": "거반도 1kg (4~10과 내외)", "name": "박복숭", "phone": "0508-1000-3000",
         "address": addr, "courier": "롯데택배", "tracking": "261700000311"},
    ], [
        _toss("OP-KOL-21", "박복숭", KOLRABI, "3kg", phone, addr),
        _toss("OP-GB-21", "박복숭", "거반도 납작복숭아 산지직송", "1kg", phone, addr),
    ])
    assert fake.registered == [("OP-GB-21", "롯데택배", "261700000311")]


def test_fruit_shinbi_and_baekdo_same_order_not_swapped_across_two_uploads(monkeypatch):
    """한 주문에 신비(쥬얼리)+백도(제주다팜) — 쥬얼리 회신은 신비에, 이어 올린 제주다팜 회신은 백도에만 들어간다."""
    phone, addr = "050810004000", "경기도 용인시 테스트로 22"
    shinbi = ("OP-SB-22", "박복숭", "신비복숭아 산지직송", "1kg, 1박스, 중소과", phone, addr)
    baekdo = ("OP-BD-22", "박복숭", "백도 딱딱이 복숭아 산지직송", "2kg 중과", phone, addr)
    # 토스 목록에 백도가 먼저 와도(예전엔 둘 다 '복숭아' 한 군이라 앞 주문이 가져갔다) 각자 자기 송장만
    fake, _ = _run_fruit(monkeypatch, [
        {"product": "신비복숭아 1kg", "name": "박복숭", "phone": "0508-1000-4000",
         "address": addr, "courier": "롯데택배", "tracking": "261700000401"},
    ], [_toss(*baekdo), _toss(*shinbi)])
    assert fake.registered == [("OP-SB-22", "롯데택배", "261700000401")]
    fake, _ = _run_fruit(monkeypatch, [
        {"product": "딱딱이 복숭아 중과 2kg", "name": "박복숭", "phone": "0508-1000-4000",
         "address": addr, "courier": "롯데택배", "tracking": "254000000402"},
    ], [_toss(*baekdo), _toss(*shinbi, tracking="261700000401")])
    assert fake.registered == [("OP-BD-22", "롯데택배", "254000000402")]


def test_fruit_watermelon_and_mango_watermelon_kept_apart(monkeypatch):
    """수박·망고수박은 다른 상품 — 회신에 망고수박 줄만 있으면 망고수박 주문에만 등록."""
    phone, addr = "050810005000", "충청남도 천안시 테스트로 23"
    fake, _ = _run_fruit(monkeypatch, [
        {"product": "블랙망고수박 2.5kg", "name": "박수박", "phone": "0508-1000-5000",
         "address": addr, "courier": "롯데택배", "tracking": "261700000501"},
    ], [
        _toss("OP-WM-23", "박수박", "고당도 수박 7kg", "7kg", phone, addr),
        _toss("OP-MW-23", "박수박", "블랙망고수박 산지직송", "1통(내외)", phone, addr),
    ])
    assert fake.registered == [("OP-MW-23", "롯데택배", "261700000501")]


def test_fruit_rerun_same_reply_does_not_reuse_registered_tracking(monkeypatch):
    """같은 사람 콜라비 3kg+5kg, 회신엔 3kg만 — 같은 회신을 다시 올려도 3kg 송장이 5kg 주문에 들어가지 않는다."""
    phone, addr = "050810006000", "서울특별시 노원구 테스트로 24"
    reply = [{"product": "콜라비 정품 3kg", "name": "재시도", "phone": "0508-1000-6000",
              "address": addr, "courier": "롯데택배", "tracking": "261700000601"}]
    k3 = ("OP-K3-24", "재시도", KOLRABI, "3kg", phone, addr)
    k5 = ("OP-K5-24", "재시도", KOLRABI, "5kg", phone, addr)
    fake, _ = _run_fruit(monkeypatch, reply, [_toss(*k3), _toss(*k5)])
    assert fake.registered == [("OP-K3-24", "롯데택배", "261700000601")]
    fake, stats = _run_fruit(monkeypatch, reply, [_toss(*k3, tracking="261700000601"), _toss(*k5)])
    assert fake.registered == [] and stats["toss_success"] == 0, stats


def test_fruit_blank_courier_ignores_delivery_memo_words(monkeypatch):
    """배송메모에 '햇밤'이 있어도 콜라비 주문은 롯데택배(상품명·옵션으로만 판정)."""
    item = _toss("OP-KO-25", "메모씨", KOLRABI, "3kg", "050810007000", "서울특별시 중랑구 테스트로 25")
    item["deliveryMemo"] = "햇밤 주문도 같이 보내주세요"
    fake, stats = _run_fruit(monkeypatch, [
        {"product": "콜라비 정품 3kg", "name": "메모씨", "phone": "0508-1000-7000",
         "address": "서울특별시 중랑구 테스트로 25", "tracking": "261700000701"},
    ], [item])
    assert fake.registered == [("OP-KO-25", "롯데택배", "261700000701")]


def test_fruit_option_substring_with_different_kg_is_not_a_match(monkeypatch):
    """토스 '콜라비 정품' 5kg ↔ 회신 '콜라비 정품 3kg'(전화 빈칸): 상품명 부분 일치만으로 넣지 않는다."""
    fake, stats = _run_fruit(monkeypatch, [
        {"product": "콜라비 정품 3kg", "name": "박부분", "phone": "",
         "address": "부산광역시 동래구 테스트로 26", "courier": "롯데택배", "tracking": "261700000801"},
    ], [
        _toss("OP-KO-26", "박부분", "콜라비 정품", "5kg", "01012120000", "대구광역시 수성구 테스트로 27"),
    ])
    assert fake.registered == [] and stats["toss_skip"] == 1, stats


def test_fruit_same_option_but_different_phones_needs_address(monkeypatch):
    """같은 상품·같은 옵션이어도 양쪽 전화가 다르면 다른 주문일 수 있다 — 주소가 다르면 넣지 않고, 같으면 넣는다."""
    fake, stats = _run_fruit(monkeypatch, [
        {"product": "콜라비 정품 3kg", "name": "홍동명", "phone": "0504-1111-2222",
         "address": "부산광역시 사하구 테스트로 28", "courier": "롯데택배", "tracking": "261700000901"},
    ], [
        _toss("OP-KO-28", "홍동명", KOLRABI, "3kg", "050899990000", "서울특별시 은평구 테스트로 29"),
    ])
    assert fake.registered == []
    assert stats["토스 미등록 사유"] == "홍동명(전화 다름(옵션만 같음) — 수동 확인)"
    fake, _ = _run_fruit(monkeypatch, [
        {"product": "콜라비 정품 3kg", "name": "홍동명", "phone": "0504-1111-2222",
         "address": "서울특별시 은평구 테스트로 29", "courier": "롯데택배", "tracking": "261700000902"},
    ], [
        _toss("OP-KO-29", "홍동명", KOLRABI, "3kg", "050899990000", "서울특별시 은평구 테스트로 29"),
    ])
    assert fake.registered == [("OP-KO-29", "롯데택배", "261700000902")]


def test_fruit_phone_with_dropped_leading_zero_still_matches(monkeypatch):
    """엑셀이 전화 앞자리 0을 떨궈도('50855551234') 같은 번호로 본다."""
    fake, _ = _run_fruit(monkeypatch, [
        {"product": "콜라비 정품 3kg", "name": "영빠짐", "phone": "50855551234",
         "address": "인천광역시 부평구 테스트로 30", "courier": "롯데택배", "tracking": "261700001001"},
    ], [
        _toss("OP-KO-30", "영빠짐", KOLRABI, "5kg", "050855551234", "인천광역시 부평구 테스트로 30-1"),
        _toss("OP-KO-31", "영빠짐", KOLRABI, "3kg", "050855551234", "인천광역시 부평구 테스트로 30-1"),
    ])
    assert fake.registered == [("OP-KO-31", "롯데택배", "261700001001")]


def test_goguma_rerun_same_reply_does_not_reuse_registered_tracking(monkeypatch):
    """같은 사람 3kg+5kg, 해달 회신엔 3kg만 — 같은 파일을 다시 올려도 3kg 송장이 5kg 박스에 들어가지 않는다."""
    addr = "광주광역시 테스트로 31"
    reply = [{"name": "재고구", "phone": "010-3333-0000", "address": addr,
              "product": "꿀고구마 3Kg (중상)", "tracking": "463300001001"}]
    g3 = ("OP-G3", "재고구", KKUL, "3kg 중상", "01033330000", addr)
    g5 = ("OP-G5", "재고구", KKUL, "5kg 특상", "01033330000", addr)
    fake, _ = _run_goguma(monkeypatch, reply, [_toss(*g3), _toss(*g5)])
    assert fake.registered == [("OP-G3", "한진택배", "463300001001")]
    fake, result = _run_goguma(monkeypatch, reply, [_toss(*g3, tracking="463300001001"), _toss(*g5)])
    assert fake.registered == [] and result["success"] == 0, result


def test_goguma_same_option_but_different_phones_needs_address(monkeypatch):
    """같은 옵션이어도 양쪽 전화가 다르고 주소도 다르면(동명이인 쿠팡 고객 줄) 등록하지 않는다."""
    fake, result = _run_goguma(monkeypatch, [
        {"name": "이고구", "phone": "0504-5555-0000", "address": "부산광역시 테스트로 32",
         "product": "꿀고구마 3Kg (중상)", "tracking": "463300001101"},
    ], [
        _toss("OP-G6", "이고구", KKUL, "3kg 중상", "01099990000", "서울특별시 테스트로 33"),
    ])
    assert fake.registered == []
    assert _messages(result, "skip") == {"이고구": "전화 다름(옵션만 같음) — 수동 확인"}
