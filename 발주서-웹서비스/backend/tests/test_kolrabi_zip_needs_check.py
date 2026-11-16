"""제주다팜 발주서가 여러 파일(zip)로 나와도 '거래처 판매옵션에 없음' 경고가 화면에 보여야 한다 — 2026-11-16 리뷰 1순위.

종전엔 zip 응답 stats가 {'files','total'}뿐이라, 파일별 needs_check(새 옵션 주문이 발주서에서 빠졌다는 경고)가
사라져 그 주문이 아무 표시 없이 누락됐다(단일 파일일 때만 보였다).
"""

import asyncio
import json
from io import BytesIO

import pytest
from fastapi import UploadFile
from openpyxl import Workbook

from app import main

BUSA = "경북 부사사과 정품 실중량"


def _delivery(rows: list[tuple[str, str, str, str]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    for i, (order_no, product, option, name) in enumerate(rows):
        r = i + 2
        ws.cell(r, 3, order_no)
        ws.cell(r, 11, product)
        ws.cell(r, 12, option)
        ws.cell(r, 23, 1)
        ws.cell(r, 27, name)
        ws.cell(r, 28, "010-0000-0000")
        ws.cell(r, 30, "서울시 어딘가")
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_merge_needs_check_labels_each_file():
    results = [
        (b"", "a.xlsx", {"product": "콜라비", "total": 1}),
        (b"", "b.xlsx", {"product": "부사사과(제주다팜)", "total": 0, "needs_check": ["김부사(1박스 3kg (중대과)) — 거래처 판매옵션에 없음"]}),
        (b"", "c.xlsx", {"needs_check": "문자열 경고"}),
    ]
    assert main._merge_needs_check(results) == [
        "부사사과(제주다팜): 김부사(1박스 3kg (중대과)) — 거래처 판매옵션에 없음",
        "문자열 경고",
    ]


@pytest.fixture
def run_kolrabi(monkeypatch):
    async def fake_exclusions(section, flag, reissue_stale=True):
        return set()

    async def fake_dates(section, flag):
        return {}

    async def fake_stale(section, flag, issued_dates=None):
        return set()

    async def fake_sales(*_a, **_k):
        return None

    async def fake_record(*_a, **_k):
        return None

    monkeypatch.setattr(main, "_issued_exclusions", fake_exclusions)
    monkeypatch.setattr(main, "_issued_exclusion_dates", fake_dates)
    monkeypatch.setattr(main, "_issued_stale_keys", fake_stale)
    monkeypatch.setattr(main, "record_sales_from_process_stats", fake_sales)
    monkeypatch.setattr(main.database, "record_issued_orders", fake_record)

    def run(delivery: bytes):
        upload = UploadFile(file=BytesIO(delivery), filename="DeliveryList(2026-11-16)_(0).xlsx")
        return asyncio.run(main.process_kolrabi_order(
            delivery_file=upload, toss_from_date="", toss_to_date="", include_toss="",
            exclude_issued="true", user={"user_id": 1},
        ))

    return run


def test_zip_response_keeps_unmatched_option_warning(run_kolrabi):
    response = run_kolrabi(_delivery([
        ("K1", "콜라비 정품", "3kg", "콜라비고객"),
        ("B1", BUSA, "1박스 3kg (중대과)", "김부사"),   # 제주다팜 판매옵션에 없는 등급 → 발주서에 못 넣음
    ]))
    assert response.media_type == "application/zip"
    stats = json.loads(response.headers["x-stats"])
    assert stats["files"] == 2
    assert any("김부사" in n and "거래처 판매옵션에 없음" in n for n in stats["needs_check"])
