"""토스 홍로사과 주문이 제주다팜 발주서에 들어가야 한다 (2026-09-09 실사고).

토스에 홍로사과 주문이 들어왔는데 수집 대상에 홍로가 없어 발주서에서 통째로 빠졌다.
"""
import asyncio

import pytest

from app.processors import tomato_order


class _FakeTossClient:
    def __init__(self, orders):
        self._orders = orders

    async def get_orders(self, start_date=None, end_date=None, status=None):
        return self._orders


def _toss_item(product_name, option, qty=1, name="홍길동"):
    return {
        "productName": product_name,
        "optionName": option,
        "quantity": qty,
        "receiverName": name,
        "receiverPhone": "010-1111-2222",
        "receiverAddress": "서울시 어딘가 1-2",
        "orderProductStatus": "PAY_DONE",
    }


def _collect(monkeypatch, orders):
    import app.toss.client as toss_module

    monkeypatch.setattr(toss_module, "toss_client", _FakeTossClient(orders), raising=False)
    return asyncio.run(tomato_order.collect_toss_jejudapam_orders("2026-09-09", "2026-09-09"))


def test_toss_hongro_order_is_collected(monkeypatch):
    """실제 토스 주문 표기: 상품명에 '홍로사과', 옵션에 등급·kg."""
    orders = [_toss_item(
        "2026 햇 안동 고당도 홍로사과 아삭한 꿀사과 산지직송 제철 햇사과",
        "대과, 5kg, 1박스",
        name="김광은",
    )]
    result = _collect(monkeypatch, orders)
    hongro = result["hongro"]
    assert len(hongro) == 1, result
    assert hongro[0]["name"] == "김광은"
    assert hongro[0]["product"] == "가을햇사과(홍사과) 가정용 대과 포장재포함 5kg(16-18과)"


def test_toss_cheongsagwa_is_not_collected_as_hongro(monkeypatch):
    """청사과(아오리)는 제이비티 발주 — 제주다팜 홍로로 새면 안 된다."""
    orders = [_toss_item(
        "[핫딜] 새콤아삭 고당도선별 아오리사과 여름 청사과 풋사과",
        "가정용 대과 2kg",
    )]
    result = _collect(monkeypatch, orders)
    assert result["hongro"] == []


def test_toss_kolrabi_still_collected(monkeypatch):
    """기존 콜라비 수집이 홍로 추가로 깨지면 안 된다."""
    orders = [_toss_item("[제주직송] 고당도 100% 제주 콜라비", "정품 3kg")]
    result = _collect(monkeypatch, orders)
    assert len(result["colrabi"]) == 1
