"""고구마 운송장 등록 시 결제완료 주문 확인(상품준비중 전환) 범위 테스트.

회귀 방지: 예전에는 매칭 여부와 무관하게 결제완료(ACCEPT) 주문 전부를
confirm 처리해서, 송장 0건 등록인데도 주문이 다음 단계로 넘어갔다 (2026-07-19 보고).
지금은 해달 운송장과 매칭된 주문만 confirm한다.
"""

import asyncio

import pytest

from app.processors import goguma_tracking_api as gta


def _order(box_id, name, phone, status):
    return {
        "shipment_box_id": box_id,
        "order_id": box_id * 10,
        "vendor_item_id": box_id * 100,
        "name": name,
        "phone": phone,
        "address": f"주소{box_id}",
        "name_display": name,
        "order_status": status,
        "option_keys": set(),
    }


def _entry(name, phone, tracking):
    return {
        "name": name,
        "phone": phone,
        "address": "",
        "tracking": tracking,
        "delivery_company_code": "HANJIN",
        "option_keys": set(),
    }


class FakeClient:
    def __init__(self):
        self.confirm_calls: list[list[int]] = []
        self.upload_calls: list[list[dict]] = []

    async def confirm_orders(self, shipment_box_ids):
        self.confirm_calls.append(sorted(shipment_box_ids))
        return {"code": 200}

    async def upload_invoices(self, dtos):
        self.upload_calls.append(dtos)
        return {"code": 200, "data": {"responseList": []}}


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(gta, "coupang_goguma_client", client)
    monkeypatch.setattr(gta.asyncio, "sleep", _no_sleep)
    return client


async def _no_sleep(_seconds):
    return None


def test_confirm_only_matched_accept_orders(monkeypatch, fake_client):
    """매칭된 ACCEPT만 confirm — 매칭 안 된 ACCEPT는 결제완료에 그대로 남긴다."""
    monkeypatch.setattr(gta, "parse_haedal_file", lambda _b: [_entry("김매칭", "01011112222", "699011112222")])

    async def fake_fetch():
        return [
            _order(101, "김매칭", "01011112222", "ACCEPT"),   # 해달과 매칭됨
            _order(202, "박스킵", "01033334444", "ACCEPT"),   # 매칭 안 됨 → 건드리면 안 됨
            _order(303, "이스킵", "01055556666", "INSTRUCT"), # 매칭 안 됨
        ]
    monkeypatch.setattr(gta, "fetch_pending_orders", fake_fetch)

    result = asyncio.run(gta.process_tracking_api(b"fake"))

    assert result["success"] == 1
    assert result["skip"] == 2
    # confirm은 딱 한 번, 매칭된 101번 박스만
    assert fake_client.confirm_calls == [[101]]


def test_no_confirm_when_nothing_matches(monkeypatch, fake_client):
    """매칭 0건이면 confirm 호출 자체가 없어야 한다 (기존 버그 재현 방지)."""
    monkeypatch.setattr(gta, "parse_haedal_file", lambda _b: [_entry("없는사람", "01099998888", "699099998888")])

    async def fake_fetch():
        return [
            _order(201, "고은미", "01012121212", "ACCEPT"),
            _order(202, "홍동환", "01023232323", "ACCEPT"),
            _order(203, "박경숙", "01034343434", "ACCEPT"),
        ]
    monkeypatch.setattr(gta, "fetch_pending_orders", fake_fetch)

    result = asyncio.run(gta.process_tracking_api(b"fake"))

    assert result["success"] == 0
    assert result["skip"] == 3
    assert fake_client.confirm_calls == []      # 결제완료 주문이 하나도 안 넘어감
    assert fake_client.upload_calls == []


def test_matched_instruct_needs_no_confirm(monkeypatch, fake_client):
    """상품준비중(INSTRUCT) 매칭 건은 confirm 없이 바로 송장 등록."""
    monkeypatch.setattr(gta, "parse_haedal_file", lambda _b: [_entry("김준비", "01011112222", "699011113333")])

    async def fake_fetch():
        return [_order(301, "김준비", "01011112222", "INSTRUCT")]
    monkeypatch.setattr(gta, "fetch_pending_orders", fake_fetch)

    result = asyncio.run(gta.process_tracking_api(b"fake"))

    assert result["success"] == 1
    assert fake_client.confirm_calls == []
    assert len(fake_client.upload_calls) == 1


def test_fetch_pending_orders_never_confirms(monkeypatch, fake_client):
    """조회 함수는 상태 변경(confirm) 없이 조회만 한다."""
    async def fake_by_status(order_status, _f, _t):
        if order_status == "ACCEPT":
            return [_order(401, "결제완료", "01000000000", "ACCEPT")]
        return [_order(402, "준비중", "01011111111", "INSTRUCT")]
    monkeypatch.setattr(gta, "_fetch_orders_by_status", fake_by_status)

    orders = asyncio.run(gta.fetch_pending_orders())

    assert {o["shipment_box_id"] for o in orders} == {401, 402}
    assert fake_client.confirm_calls == []
