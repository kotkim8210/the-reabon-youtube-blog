"""고구마 화면 '토스만' 버튼(/api/process/toss-order) 중복발주 방지 — 2026-11-16 리뷰 1순위.

종전엔 발주 이력을 조회도 기록도 안 해 '토스만'과 '전체 수집'(goguma-auto)을 섞어 쓰면 같은 토스 꿀고구마가
해달에 이중 발주됐다. 이제 '전체 수집'과 같은 goguma 이력·같은 키(주문번호|해달 품목명)로 빼고 기록한다.
"""

import asyncio
from io import BytesIO

import pytest
from fastapi import HTTPException
from openpyxl import load_workbook

from app import main
from app import api_common
from app.routes import process_goguma
from app.processors import goguma_order, issued_orders, toss_auto


def _item(order_no: str, name: str, option: str) -> dict:
    return {
        "orderNo": order_no, "productName": "해남 황금 꿀고구마", "optionName": option,
        "receiverName": name, "receiverRealPhone": "010-1234-0000", "address": "서울시 테스트구",
        "detailAddress": "1층", "zipCode": "12345", "quantity": 1, "shippingNote": "",
    }


ITEMS = [_item("T-1001", "토스하나", "꿀고구마 3kg 중상"), _item("T-1002", "토스둘", "꿀고구마 5kg 특상")]


def _key(item: dict) -> str:
    product = goguma_order.transform_toss_option(item["productName"], item["optionName"])
    return issued_orders.make_order_key(item["orderNo"], product)


def _names(xlsx: bytes) -> list[str]:
    ws = load_workbook(BytesIO(xlsx)).worksheets[0]
    return [ws.cell(r, 1).value for r in range(2, ws.max_row + 1) if ws.cell(r, 1).value]


@pytest.fixture
def endpoint(monkeypatch):
    recorded: list[dict] = []
    issued: set[str] = set()

    class FakeToss:
        async def get_orders(self, start_date, end_date, status):
            return [dict(i) for i in ITEMS]

    async def fake_exclusions(section, flag, reissue_stale=True):
        assert section == "goguma"                       # '전체 수집'과 같은 이력
        return set(issued) if api_common._exclude_issued_enabled(flag) else set()

    async def fake_dates(section, flag):
        return {}

    async def fake_stale(section, flag, issued_dates=None):
        return set()

    async def fake_sales(*_a, **_k):
        return None

    async def fake_record(section, order_ids, filename, ymd):
        recorded.append({"section": section, "ids": list(order_ids)})

    monkeypatch.setattr(toss_auto, "toss_client", FakeToss())
    monkeypatch.setattr(api_common, "_goguma_proxy_enabled", lambda: False)
    monkeypatch.setattr(api_common, "_issued_exclusions", fake_exclusions)
    monkeypatch.setattr(api_common, "_issued_exclusion_dates", fake_dates)
    monkeypatch.setattr(api_common, "_issued_stale_keys", fake_stale)
    monkeypatch.setattr(api_common, "record_sales_from_process_stats", fake_sales)
    monkeypatch.setattr(main.database, "record_issued_orders", fake_record)
    monkeypatch.setattr(api_common, "make_excel_response", lambda b, f, s=None: (b, f, s))

    def run(exclude_issued: bool = True):
        req = process_goguma.TossAutoRequest(from_date="2026-11-15", to_date="2026-11-16", exclude_issued=exclude_issued)
        return asyncio.run(process_goguma.process_toss_order(req=req, user={"user_id": 1}))

    run.issued = issued
    return run, recorded


def test_toss_only_records_issued_keys_like_collect_all(endpoint):
    run, recorded = endpoint
    xlsx, _filename, stats = run()
    assert _names(xlsx) == ["토스하나", "토스둘"]
    assert recorded == [{"section": "goguma", "ids": sorted(_key(i) for i in ITEMS)}]
    assert "duplicate_skipped" not in stats


def test_toss_only_skips_orders_already_issued_by_collect_all(endpoint):
    run, recorded = endpoint
    run.issued.add(_key(ITEMS[0]))
    xlsx, _filename, stats = run()
    assert _names(xlsx) == ["토스둘"]
    assert stats["duplicate_skipped"] == 1 and "토스하나" in stats["duplicate_skipped_names"]
    assert recorded[0]["ids"] == [_key(ITEMS[1])]


def test_toss_only_all_issued_says_why(endpoint):
    run, recorded = endpoint
    run.issued.update(_key(i) for i in ITEMS)
    with pytest.raises(HTTPException) as exc:
        run()
    assert "이전 발주분 2건" in exc.value.detail and "토스하나" in exc.value.detail
    assert recorded == []


def test_toss_only_unchecked_box_issues_again(endpoint):
    run, _recorded = endpoint
    run.issued.add(_key(ITEMS[0]))
    xlsx, _filename, _stats = run(exclude_issued=False)
    assert _names(xlsx) == ["토스하나", "토스둘"]


def test_request_without_flag_defaults_to_exclude():
    """다른 화면(토스 자동 페이지)은 플래그 없이 보낸다 → 기본은 제외(중복 방지)."""
    req = process_goguma.TossAutoRequest(from_date="2026-11-16", to_date="2026-11-16")
    assert req.exclude_issued is True
