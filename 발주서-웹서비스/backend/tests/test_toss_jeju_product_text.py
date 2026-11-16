"""토스 제주다팜 수집은 상품명+옵션만 보고 품목을 판정한다 (2026-11-16 리뷰 jeju_wiring-6·7, other_suppliers-4).

종전엔 수령인 이름·주소·배송메모까지 합친 주문 텍스트로 품목 분기·강제 변환을 해서
 - 이름에 '백도'가 든 손님(백도현)의 황금향·시나노 주문이 백도 분기로 빠져 통째로 누락되고
 - 배송메모에 '콜라비'가 든 시나노 주문이 '콜라비 정품 3kg'으로 둔갑했다.
"""
import asyncio

from app.processors import tomato_order

HWANGGEUM = "[재구매1위] 제주 황금향 정품 하우스 고당도 평균16brix 산지직송 맛보장"
SHINANO = "시나노 골드 사과 노란사과 황금사과 경북 가정용 상등급"


class _FakeTossClient:
    def __init__(self, orders):
        self._orders = orders

    async def get_orders(self, start_date=None, end_date=None, status=None):
        return self._orders


def _item(product_name, option, name="토스손님", memo="", address="서울시 어딘가 1-2", detail=""):
    return {
        "productName": product_name,
        "optionName": option,
        "quantity": 1,
        "receiverName": name,
        "receiverPhone": "010-1111-2222",
        "address": address,
        "detailAddress": detail,
        "shippingNote": memo,
        "orderProductStatus": "PAY_DONE",
    }


def _collect(monkeypatch, orders):
    import app.toss.client as toss_module

    monkeypatch.setattr(toss_module, "toss_client", _FakeTossClient(orders), raising=False)
    return asyncio.run(tomato_order.collect_toss_jejudapam_orders("2026-11-16", "2026-11-16"))


def _products(result, key):
    return [(e["name"], e["product"]) for e in result[key]]


def test_receiver_named_baekdo_is_not_dropped(monkeypatch):
    """이름에 '백도'가 있어도 황금향·시나노 주문은 그대로 수집된다(백도 분기로 새서 누락되면 안 됨)."""
    result = _collect(monkeypatch, [
        _item(HWANGGEUM, "1박스 3kg (중)", name="백도현"),
        _item(SHINANO, "중과, 3kg, 1박스", name="백도현"),
    ])
    assert _products(result, "hwanggeum") == [("백도현", "하우스 정품 황금향 중과(150~220g) 3kg")]
    assert _products(result, "shinano") == [("백도현", "시나노골드(가정용) 중과 3kg(9-12과내외)")]
    assert result["baekdo"] == []


def test_memo_with_kolrabi_does_not_turn_order_into_kolrabi(monkeypatch):
    """배송메모의 '콜라비'로 시나노 주문이 콜라비로 둔갑하거나, 고구마 주문이 콜라비로 발주되면 안 된다."""
    result = _collect(monkeypatch, [
        _item(SHINANO, "중과, 3kg, 1박스", name="시나노손님", memo="지난번 콜라비도 맛있었어요"),
        _item("해남 꿀고구마 베니하루카", "특상 3kg", name="고구마손님", memo="콜라비랑 같이 보내주세요"),
    ])
    assert _products(result, "shinano") == [("시나노손님", "시나노골드(가정용) 중과 3kg(9-12과내외)")]
    assert result["colrabi"] == []
    assert sum(len(v) for v in result.values()) == 1   # 고구마 주문은 제주다팜 수집 대상이 아니다


def test_product_words_in_address_are_ignored(monkeypatch):
    """주소에 품목 낱말(홍감자·밤호박·백도)이 있어도 판정에 영향이 없다."""
    result = _collect(monkeypatch, [
        _item(HWANGGEUM, "1박스 2kg (소)", name="주소손님",
              address="경기도 화성시 홍감자길 7", detail="밤호박빌라 백도동 101호"),
    ])
    assert _products(result, "hwanggeum") == [("주소손님", "하우스 정품 황금향 소과(100g~150g) 2kg")]
    assert result["potato"] == [] and result["bamhobak"] == [] and result["baekdo"] == []


def test_real_product_orders_still_collected(monkeypatch):
    """상품명·옵션에 품목이 있으면 종전처럼 수집(콜라비·백도·홍감자)."""
    result = _collect(monkeypatch, [
        _item("[제주직송] 고당도 100% 제주 콜라비", "정품 3kg", name="콜라비손님"),
        _item("백도 딱딱이복숭아", "대과 2kg", name="백도손님"),
        _item("햇 홍감자", "1박스 3kg(대)", name="감자손님"),
    ])
    assert _products(result, "colrabi") == [("콜라비손님", "콜라비 정품 3kg")]
    assert _products(result, "baekdo") == [("백도손님", "딱딱이 복숭아 대과 2kg")]
    assert _products(result, "potato") == [("감자손님", "홍감자 특 3kg")]
