"""상품 레지스트리 — 상품 하나를 레지스트리에 넣으면 발주·토스수집·라우팅·이벤트·송장 경로가 다 따라오는지."""

import asyncio

import pytest

from app import product_registry as reg
from app.processors import kolrabi_order


def test_registry_entries_are_wired():
    keys = [p.key for p in reg.JEJU_PRODUCTS]
    assert len(keys) == len(set(keys))
    families = [p.family for p in reg.JEJU_PRODUCTS if p.family]
    assert len(families) == len(set(families))
    for product in reg.JEJU_PRODUCTS:
        assert callable(getattr(kolrabi_order, product.builder)), product.key
        if product.event_rank is not None or product.routing:
            assert callable(product.converter()), product.key
        if product.toss:
            assert product.toss.tag.startswith("toss-"), product.key
            # 토스로 파는 상품은 토스 운송장 자동등록 낱말에도 걸려야 한다(홍로 2026-09-11 사고)
            assert product.family_match, product.key


def test_toss_tracking_keywords_cover_toss_products():
    from app.processors.tomato_tracking import _TOSS_TRACKING_KEYWORDS

    for product in reg.TOSS_PRODUCTS:
        assert product.toss_tracking_keywords, product.key
        assert set(product.toss_tracking_keywords) <= set(_TOSS_TRACKING_KEYWORDS)


def test_process_outputs_toss_entries_dict_and_legacy_kwargs_same():
    """새 호출(toss_entries={key: [...]})과 옛 호출(toss_<key>_entries=)이 같은 발주서를 낸다."""
    from tests.test_gamhong_jeju import _delivery

    data = _delivery([{"product": "[산지직송] 고당도 경북 문경 감홍사과 가정용 A등급", "option": "1박스 3kg (중과)"}])
    toss = [{"name": "토스손님", "phone": "010-1111-2222", "zipcode": "12345", "address": "부산", "qty": "1",
             "product_name": "감홍사과", "option": "", "product": "감홍사과(가정용 A등급) 대과 5kg(8-14과내외)",
             "memo": "", "order_id": "T1"}]
    new = kolrabi_order.process_outputs(data, toss_entries={"gamhong": toss})
    old = kolrabi_order.process_outputs(data, toss_gamhong_entries=toss)
    assert [(f, st["total"]) for _b, f, st in new] == [(f, st["total"]) for _b, f, st in old]
    assert next(st for _b, _f, st in new if st["product"] == "감홍사과(제주다팜)")["total"] == 2


def test_process_outputs_kwargs_compat():
    with pytest.raises(TypeError):
        kolrabi_order.process_outputs(b"", toss_nothing_entries=[])


def test_collect_returns_all_toss_keys(monkeypatch):
    import app.toss.client as toss_module
    from app.processors import tomato_order

    class _Fake:
        async def get_orders(self, **_kwargs):
            return []

    monkeypatch.setattr(toss_module, "toss_client", _Fake(), raising=False)
    result = asyncio.run(tomato_order.collect_toss_jejudapam_orders("2026-11-01", "2026-11-02"))
    assert set(result) == {p.key for p in reg.TOSS_PRODUCTS}
