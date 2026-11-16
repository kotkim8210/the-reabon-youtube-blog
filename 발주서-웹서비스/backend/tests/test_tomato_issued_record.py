"""제이비티(토마토 메뉴) 발주 이력이 한 건도 기록되지 않던 문제 (2026-11-16 리뷰 issued_dedup-1·other_suppliers-3).

build_main_order_workbook stats에는 버킷이 품목별 sales_groups 안에만 있어
order_ids_from_stats가 키를 0개 돌려줬다 → 7/7 도입 이후 대저토마토·땅두릅·신비복숭아 3·4kg·청사과의
'이전 발주분 자동 제외'와 '미출고 재발주'가 한 번도 동작하지 않았다.
기록은 tomato_order.issued_record_stats로 편 기록용 stats로 하고, 응답 stats에는 주문 목록을 한 번만 싣는다.

기록 키(주문번호|옵션)는 다음 발주 때 대조하는 키와 같아야 한다:
  DeliveryList → filter_delivery_by_issued: C열 주문번호 | L열 옵션(비면 K열 상품명)
  토스 신비 3·4kg → filter_entries_by_issued: order_id | option
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile
from openpyxl import Workbook, load_workbook

from app import main
from app.processors import event_order, issued_orders, tomato_order

KST = timezone(timedelta(hours=9))
MON = datetime(2026, 11, 16, 9, 0, tzinfo=KST)   # 월요일
TUE = datetime(2026, 11, 17, 9, 0, tzinfo=KST)
THU = datetime(2026, 11, 19, 9, 0, tzinfo=KST)

TOMATO = {"order_no": "31100012345671", "product": "부산 대저토마토 짭짤이 산지직송",
          "option": "1박스 로얄과 2.5kg", "name": "토마토손님"}
DDUREUP = {"order_no": 31100012345672, "product": "남해 땅두릅 산지직송", "option": "특품 500g",
           "name": "두릅손님", "qty": 2}
APPLE = {"order_no": "31100012345673", "product": "[핫딜] 새콤아삭 고당도선별 아오리사과 여름 청사과 풋사과",
         "option": "1박스 가정용 소과 2kg", "name": "청사과손님"}
PEACH = {"order_no": "31100012345674", "product": "신비복숭아 산지직송 천도복숭아", "option": "중소과 3kg",
         "name": "복숭아손님"}
NO_OPTION = {"order_no": "31100012345675", "product": "대저토마토 짭짤이 로얄과 2.5kg", "option": None,
             "name": "옵션없음손님"}
NEW_TOMATO = {"order_no": "31100012345699", "product": "부산 대저토마토 짭짤이 산지직송",
              "option": "1박스 로얄과 2.5kg", "name": "새주문손님"}
KOLRABI = {"order_no": "31100012345680", "product": "제주 콜라비 산지직송", "option": "3kg",
           "name": "콜라비손님"}   # 제이비티 품목 아님

TOSS_PEACH_ITEM = {
    "productName": "신비복숭아 3kg 산지직송",
    "optionName": "3kg",
    "orderId": "T-PEACH-1",
    "quantity": 1,
    "receiverName": "토스복숭아손님",
    "receiverPhone": "010-2222-3333",
    "address": "서울시 테스트로 9",
    "orderProductStatus": "PAY_DONE",
}


def _delivery(rows: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    for i, r in enumerate(rows):
        row = i + 2
        ws.cell(row, 3, r["order_no"])
        ws.cell(row, 11, r["product"])
        ws.cell(row, 12, r["option"])
        ws.cell(row, 23, r.get("qty", 1))
        ws.cell(row, 27, r["name"])
        ws.cell(row, 28, "010-8244-8709")
        ws.cell(row, 29, "12345")
        ws.cell(row, 30, "부산 사상구 사상로 342번길 21")
        ws.cell(row, 31, "문 앞")
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _toss_entry() -> dict:
    return {"name": "토스복숭아손님", "phone": "010-2222-3333", "zipcode": "", "address": "서울시 테스트로 9",
            "qty": "1", "product_name": "신비복숭아 3kg 산지직송", "option": "3kg", "kg": 3, "memo": "",
            "order_id": "T-PEACH-1"}


def test_stats_keys_are_excluded_by_next_day_filters():
    """발주서 stats에서 뽑은 키로 다음 날 같은 DeliveryList·토스 주문이 전부 걸러져야 한다."""
    rows = [TOMATO, DDUREUP, APPLE, PEACH, NO_OPTION]
    data = _delivery(rows)
    toss = [_toss_entry()]
    results = tomato_order.process_outputs(data, toss_peach_entries=toss)
    assert len(results) == 1
    _bytes, _filename, stats = results[0]

    keys = set(issued_orders.order_ids_from_stats(tomato_order.issued_record_stats(stats)))
    assert keys == {
        "31100012345671|1박스로얄과2.5kg",
        "31100012345672|특품500g",
        "31100012345673|1박스가정용소과2kg",
        "31100012345674|중소과3kg",
        "31100012345675|대저토마토짭짤이로얄과2.5kg",   # 옵션(L)이 비면 상품명(K) — 대조 쪽과 같은 규칙
        "T-PEACH-1|3kg",
    }

    skipped: list[str] = []
    _left, removed = issued_orders.filter_delivery_by_issued(data, keys, skipped_names=skipped)
    assert removed == len(rows)
    assert sorted(skipped) == sorted(r["name"] for r in rows)

    kept, dropped = issued_orders.filter_entries_by_issued(toss, keys)
    assert kept == [] and dropped == 1


def test_response_stats_carry_orders_once():
    """응답 stats(X-Stats 헤더)에 sales_groups와 같은 주문 목록을 'options'로 한 번 더 싣지 않는다.

    두 번 실으면 헤더가 2배가 되고(크롬 한도 약 256KB) 화면에 'options: [object Object]' 줄이 생긴다.
    이벤트 제이비티(청사과 당첨자) 단일 파일 응답도 같은 build_main_order_workbook stats를 싣는다.
    """
    _bytes, _filename, stats = tomato_order.process_outputs(
        _delivery([TOMATO]), toss_peach_entries=[_toss_entry()])[0]
    assert "options" not in stats
    assert [group["product"] for group in stats["sales_groups"]] == ["대저토마토", "신비복숭아"]

    header = "경품명,별명,개인 식별 정보 확인,이름,연락처,주소,주문 아이디,구매 금액,환불/취소 금액,환불/날짜/시간"
    winner = "아오리사과  소과 (2kg),닉,Y,오윤영,010-2221-9527,서울특별시 송파구 문정동 136,3102630001234,18800,0,"
    (_b, _f, event_stats), = event_order.process("\n".join([header, winner]).encode("utf-8-sig"))
    assert event_stats["supplier"] == "제이비티"
    assert "options" not in event_stats


class _FakeTossClient:
    def __init__(self, orders):
        self._orders = orders

    async def get_orders(self, start_date=None, end_date=None, status=None):
        return [dict(o) for o in self._orders]


async def _body(response) -> bytes:
    return b"".join([chunk async for chunk in response.body_iterator])


def _endpoint(monkeypatch, tmp_path):
    """토마토 발주 엔드포인트를 날짜를 바꿔 가며 부르는 run(day, rows, with_toss).

    임시 SQLite(tmp_path)·가짜 토스 클라이언트만 쓴다(실제 API·운영 DB 없음).
    """
    import app.toss.client as toss_module

    class _Frozen(datetime):
        at = MON

        @classmethod
        def now(cls, tz=None):
            return cls.at.astimezone(tz) if tz else cls.at

    monkeypatch.setattr(main, "datetime", _Frozen)
    monkeypatch.setattr(main.database, "DATABASE_PATH", str(tmp_path / "issued.db"))
    monkeypatch.setattr(main.database, "_db", None)
    monkeypatch.setattr(toss_module, "toss_client", _FakeTossClient([TOSS_PEACH_ITEM]), raising=False)

    async def run(day: datetime, rows: list[dict], with_toss: bool):
        _Frozen.at = day
        ymd = day.strftime("%Y-%m-%d")
        upload = UploadFile(file=BytesIO(_delivery(rows)), filename=f"DeliveryList({ymd}).xlsx")
        response = await main.process_tomato_order(
            delivery_file=upload,
            toss_from_date=ymd if with_toss else "",
            toss_to_date=ymd if with_toss else "",
            include_toss="",
            exclude_issued="true",
            user={"user_id": 1},
        )
        ws = load_workbook(BytesIO(await _body(response))).active
        names = [ws.cell(r, 2).value for r in range(2, ws.max_row + 1)]
        return names, json.loads(response.headers["x-stats"])

    return run


def _scenario(steps) -> None:
    """임시 DB를 열고 steps()를 한 이벤트 루프 안에서 돌린 뒤 닫는다."""
    async def wrapped():
        await main.database.init_db()
        try:
            await steps()
        finally:
            await main.database.close_db()

    asyncio.run(wrapped())


def test_endpoint_records_then_skips_next_day_and_reissues_later(monkeypatch, tmp_path):
    """엔드포인트 그대로: 1일차 기록 → 2일차 같은 주문 제외(새 주문만) → 영업일 2일 뒤 미출고면 재발주."""
    run = _endpoint(monkeypatch, tmp_path)

    async def steps():
        # 1일차(월): 4건 + 토스 신비 3kg 1건 발주 → 5개 키 기록(응답 stats엔 주문 목록을 한 번만)
        names, stats = await run(MON, [TOMATO, DDUREUP, APPLE, PEACH], True)
        assert sorted(set(names)) == sorted(
            ["토마토손님", "두릅손님", "청사과손님", "복숭아손님", "토스복숭아손님"])
        assert "options" not in stats
        recorded = await main.database.issued_order_dates_before("tomato", "2026-11-17")
        assert recorded == {key: "2026-11-16" for key in (
            "31100012345671|1박스로얄과2.5kg",
            "31100012345672|특품500g",
            "31100012345673|1박스가정용소과2kg",
            "31100012345674|중소과3kg",
            "T-PEACH-1|3kg",
        )}

        # 2일차(화): 어제 주문이 아직 DeliveryList·토스에 남아 있어도 새 주문만 발주
        names, stats = await run(TUE, [TOMATO, DDUREUP, APPLE, PEACH, NEW_TOMATO], True)
        assert names == ["새주문손님"]
        assert stats["duplicate_skipped"] == 5
        for name in ("토마토손님", "두릅손님", "청사과손님", "복숭아손님", "토스복숭아손님"):
            assert name in stats["duplicate_skipped_names"]

        # 4일차(목): 월요일 발주분이 영업일 2일 지나도 미출고로 남아 있으면 자동 재발주
        names, stats = await run(THU, [TOMATO], False)
        assert names == ["토마토손님"]
        assert stats["reissued"] == 1
        assert "토마토손님(11/16 발주분)" in stats["reissued_names"]

    _scenario(steps)


def test_excluded_names_carry_issue_date(monkeypatch, tmp_path):
    """제외된 받는분 옆에 발주일을 붙인다(콜라비 등 다른 메뉴와 같은 표시) — 같은 날 동명이인 새 주문과 구분된다."""
    run = _endpoint(monkeypatch, tmp_path)
    same_name_new = {**NEW_TOMATO, "name": "토마토손님"}   # 어제 손님과 이름만 같은 새 주문

    async def steps():
        await run(MON, [TOMATO, DDUREUP], True)
        names, stats = await run(TUE, [TOMATO, DDUREUP, same_name_new], True)
        assert names == ["토마토손님"]   # 새 주문만 발주
        assert stats["duplicate_skipped"] == 3
        # 토스 항목은 대조 키를 돌려받지 않아 이름만 나온다(콜라비 메뉴와 같은 동작)
        assert stats["duplicate_skipped_names"] == (
            "토마토손님(11/16 발주분), 두릅손님(11/16 발주분), 토스복숭아손님")

    _scenario(steps)


def test_all_excluded_day_says_how_many_and_who(monkeypatch, tmp_path):
    """그날 주문이 전부 이전 발주분이면 400 '찾지 못했습니다'만 뜨던 것 → 제외 건수·받는분(발주일)을 함께 알린다."""
    run = _endpoint(monkeypatch, tmp_path)

    async def steps():
        # 제외가 없을 때의 안내는 그대로
        with pytest.raises(HTTPException) as nothing:
            await run(MON, [KOLRABI], False)
        assert nothing.value.status_code == 400
        assert "찾지 못했습니다" in nothing.value.detail and "이전 발주분" not in nothing.value.detail

        await run(MON, [TOMATO, DDUREUP], True)
        with pytest.raises(HTTPException) as exc:
            await run(TUE, [TOMATO, DDUREUP, KOLRABI], True)
        assert exc.value.status_code == 400
        assert "찾지 못했습니다" in exc.value.detail
        assert ("(이전 발주분 3건 자동 제외됨: 토마토손님(11/16 발주분), 두릅손님(11/16 발주분), 토스복숭아손님)"
                in exc.value.detail)

    _scenario(steps)
