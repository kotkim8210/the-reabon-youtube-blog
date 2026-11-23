"""이벤트 당첨자 — 개인정보 미기재 당첨자를 DeliveryList 주문번호로 채우기 + 여러 파일 한 번에(2026-11-23).

당첨자 CSV의 주문 아이디(G열) = DeliveryList 주문번호(C열). 당첨자 이름/별명이 구매자/수취인 이름과 70% 이상 같으면
같은 사람으로 보고 수취인 이름·주소·전화를 채운다. 별명이 이름과 무관하면(제타로스) 구매 금액 = 결제액일 때만 채운다.
"""

import asyncio
import json
import zipfile
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile
from openpyxl import Workbook, load_workbook

from app import api_common, main
from app.processors import event_order
from app.routes import process_fruit

HEADER = "경품명,별명,개인 식별 정보 확인,이름,연락처,주소,주문 아이디,구매 금액,환불/취소 금액,환불/날짜/시간"
# 개인정보 확인을 안 한 당첨자 — 이름·연락처·주소가 비어 온다
ROW_NICK = "황금향 (소) 2kg,제타로스,,,,,6104424933032,17600,0,"
ROW_MASKED = "부사 사과2kg(소과),유*희,,,,,26104446551289,17900,0,"
ROW_MISMATCH = "부사 사과2kg(소과),엉뚱이,,,,,28104446934676,99999,0,"
ROW_NOT_IN_DL = "부사 사과2kg(소과),없는사람,,,,,11111111111111,17900,0,"
ROW_FULL = "황금향 (소) 2kg,김*주,2026/11/21 21:37,김당첨,010-0000-0009,경기도 테스트시 테스트로 9,8104425050031,32330,0,"
ROW_REFUNDED_EMPTY = "부사 사과2kg(소과),환불이,,,,,26104446551289,17900,17900,2026/11/22 22:00"


def _csv(*rows: str) -> bytes:
    return ("\n".join((HEADER,) + rows) + "\n").encode("utf-8-sig")


def _delivery(*orders: dict) -> bytes:
    """쿠팡 DeliveryList 모양(41열) — 필요한 열만 채운다."""
    cols = {3: "주문번호", 19: "결제액", 25: "구매자", 27: "수취인이름", 28: "수취인전화번호",
            29: "우편번호", 30: "수취인 주소", 31: "배송메세지"}
    wb = Workbook()
    ws = wb.active
    for c in range(1, 42):
        ws.cell(1, c, cols.get(c, f"열{c}"))
    for r, o in enumerate(orders, start=2):
        ws.cell(r, 3, o["order"])
        ws.cell(r, 19, str(o.get("amount", 0)))
        ws.cell(r, 25, o.get("buyer", o["receiver"]))
        ws.cell(r, 27, o["receiver"])
        ws.cell(r, 28, o.get("phone", "0504-0000-0000"))
        ws.cell(r, 29, o.get("zipcode", "12345"))
        ws.cell(r, 30, o.get("address", "서울특별시 테스트구 테스트로 1"))
        ws.cell(r, 31, o.get("memo", ""))
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


DL = _delivery(
    {"order": "6104424933032", "receiver": "최강유", "amount": 17600, "address": "서울특별시 관악구 테스트로 1"},
    {"order": "26104446551289", "receiver": "유난희", "amount": 17900, "memo": "공동현관 1234"},
    {"order": "28104446934676", "receiver": "박주현", "amount": 32900},
)


def _jeju_rows(xlsx: bytes) -> list[list[str]]:
    ws = load_workbook(BytesIO(xlsx)).active
    rows = []
    for r in range(2, ws.max_row + 1):
        vals = [str(ws.cell(r, c).value or "") for c in range(1, ws.max_column + 1)]
        if any(vals):
            rows.append(vals)
    return rows


def test_name_similarity_masked_and_plain():
    assert event_order._name_similarity("유*희", "유난희") == 1.0
    assert event_order._name_similarity("김*주", "김병주") == 1.0
    assert event_order._name_similarity("제타로스", "최강유") < 0.7
    assert event_order._name_similarity("**", "최강") == 0.0      # 전부 가린 별명은 같다고 보지 않는다
    assert event_order._name_similarity("박주현", "박 주현") == 1.0


def test_missing_info_filled_by_masked_name_and_by_amount():
    results = event_order.process(_csv(ROW_NICK, ROW_MASKED, ROW_FULL), delivery_files=[DL])
    assert len(results) == 1
    data, _name, stats = results[0]
    assert stats["winners"] == 3 and "needs_check" not in stats
    filled = " / ".join(stats["filled_from_delivery"])
    assert "제타로스(6104424933032" in filled and "최강유" in filled and "결제액 일치" in filled
    assert "유*희(26104446551289" in filled and "유난희" in filled and "이름 100% 일치" in filled

    rows = _jeju_rows(data)
    by_name = {r[1]: r for r in rows}
    assert set(by_name) == {"최강유", "유난희", "김당첨"}
    assert by_name["최강유"][5] == "서울특별시 관악구 테스트로 1" and by_name["최강유"][4] == "12345"
    assert by_name["유난희"][12] == "공동현관 1234"          # DeliveryList 배송메세지가 있으면 그대로
    assert by_name["김당첨"][2] == "010-0000-0009"           # 개인정보가 있는 당첨자는 CSV 그대로


def test_not_filled_when_name_and_amount_differ_or_order_missing():
    results = event_order.process(_csv(ROW_FULL, ROW_MISMATCH, ROW_NOT_IN_DL), delivery_files=[DL])
    stats = results[0][2]
    assert stats["winners"] == 1 and "filled_from_delivery" not in stats
    assert "엉뚱이(28104446934676" in stats["needs_check"] and "확인 필요" in stats["needs_check"]
    assert "없는사람(11111111111111" in stats["needs_check"] and "같은 주문번호 없음" in stats["needs_check"]
    assert "박주현" not in json.dumps([r for r in _jeju_rows(results[0][0])], ensure_ascii=False)


def test_refunded_empty_winner_is_not_filled():
    results = event_order.process(_csv(ROW_FULL, ROW_REFUNDED_EMPTY), delivery_files=[DL])
    stats = results[0][2]
    assert stats["winners"] == 1 and stats["skipped_refund"] == 1 and "filled_from_delivery" not in stats


def test_without_delivery_list_hint_is_shown():
    stats = event_order.process(_csv(ROW_FULL, ROW_NICK))[0][2]
    assert "개인정보 미기재" in stats["needs_check"] and "DeliveryList(xlsx)를" in stats["needs_check"]


def test_same_csv_twice_counts_once():
    results = event_order.process([_csv(ROW_FULL), _csv(ROW_FULL)])
    stats = results[0][2]
    assert stats["winners"] == 1 and "두 번 올라와 1건" in stats["needs_check"]


@pytest.fixture
def endpoint(monkeypatch):
    recorded: list[dict] = []

    async def fake_exclusions(section, flag, reissue_stale=True):
        return set()

    async def fake_dates(section, flag):
        return {}

    async def fake_record(section, order_ids, filename, ymd):
        recorded.append({"section": section, "ids": list(order_ids), "filename": filename})

    monkeypatch.setattr(api_common, "_issued_exclusions", fake_exclusions)
    monkeypatch.setattr(api_common, "_issued_exclusion_dates", fake_dates)
    monkeypatch.setattr(main.database, "record_issued_orders", fake_record)

    def run(*named_files: tuple[str, bytes]):
        uploads = [UploadFile(file=BytesIO(data), filename=name) for name, data in named_files]
        return asyncio.run(process_fruit.process_event_winner_order(
            winners_file=None, files=uploads, exclude_issued="true", user={"user_id": 1},
        ))

    return run, recorded


def test_endpoint_takes_two_winner_csvs_and_delivery_list_together(endpoint):
    run, recorded = endpoint
    response = run(
        ("winners_raw_a.csv", _csv(ROW_MASKED)),
        ("DeliveryList(2026-11-23)_(0).xlsx", DL),
        ("winners_raw_b.csv", _csv(ROW_NICK, ROW_FULL)),
    )
    stats = json.loads(response.headers["x-stats"])
    assert stats["winners"] == 3 and stats["winner_files"] == 2 and len(stats["filled_from_delivery"]) == 2
    assert len(recorded) == 1 and len(recorded[0]["ids"]) == 3


def test_endpoint_mixed_suppliers_zip_keeps_fill_info(endpoint):
    run, _recorded = endpoint
    chestnut = "햇밤1kg,별명1,2026/11/15 21:01,밤당첨,010-0000-0001,부산광역시 테스트로 1,7103820345139,7700,0,"
    response = run(("w.csv", _csv(chestnut, ROW_NICK)), ("dl.xlsx", DL))
    assert response.media_type == "application/zip"
    stats = json.loads(response.headers["x-stats"])
    assert stats["files"] == 2 and "제타로스" in stats["filled_from_delivery"][0]
    with zipfile.ZipFile(BytesIO(asyncio.run(_body(response)))) as zf:
        assert len(zf.namelist()) == 2


async def _body(response) -> bytes:
    return b"".join([chunk async for chunk in response.body_iterator])


def test_endpoint_rejects_non_delivery_excel_and_delivery_only(endpoint):
    run, _recorded = endpoint
    wb = Workbook()
    wb.active.append(["상품명", "수량"])
    buf = BytesIO()
    wb.save(buf)
    with pytest.raises(HTTPException) as exc:
        run(("w.csv", _csv(ROW_FULL)), ("재고.xlsx", buf.getvalue()))
    assert exc.value.status_code == 400 and "DeliveryList" in exc.value.detail
    with pytest.raises(HTTPException) as exc:
        run(("dl.xlsx", DL))
    assert exc.value.status_code == 400 and "당첨자 CSV" in exc.value.detail
