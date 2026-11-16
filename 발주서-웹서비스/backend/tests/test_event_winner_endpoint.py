"""과일 이벤트 당첨자 카드(/api/process/event-winner-order) — 2026-11-16 리뷰 1순위 수정.

1) 경품이 거래처 2곳 이상(햇밤=쥬얼리 + 부사=제주다팜 등)으로 갈리면 "name 'KST' is not defined"·한글 X-Stats로
   발주서가 하나도 안 나왔다 → zip 응답 정상, X-Stats는 ASCII(JSON 이스케이프).
2) 꿀·호박고구마 경품이 제주다팜 발주서에 경품명 그대로 들어가 해달(고구마 화면)과 이중 발주될 수 있었다 → 빼고 '확인 필요'.
3) 화면의 '이전 발주분 자동 제외' 체크박스를 백엔드가 무시해 같은 명단을 다시 올리면 전원 다시 발주됐다
   → fruit_event 섹션에 주문아이디|발주 품목명으로 기록하고 영구 제외.
"""

import asyncio
import json
import zipfile
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile
from openpyxl import load_workbook

from app import main
from app.processors import event_order, issued_orders

HEADER = "경품명,별명,개인 식별 정보 확인,이름,연락처,주소,주문 아이디,구매 금액,환불/취소 금액,환불/날짜/시간"
ROW_CHESTNUT = "햇밤1kg,별명1,2026/11/15 21:01,밤당첨,010-0000-0001,부산광역시 테스트로 1,7103820345139,7700,0,"
ROW_BUSA = "부사 사과2kg(소과),별명2,2026/11/15 21:02,부사당첨,010-0000-0002,대구광역시 테스트로 2,21103842199632,34400,0,"
ROW_KKUL = "꿀고구마 중상 2kg,별명3,2026/11/15 21:03,꿀당첨,010-0000-0003,서울시 테스트로 3,30100000000001,13700,0,"
ROW_HOBAK = "호박고구마 특상 3kg,별명4,2026/11/15 21:04,호박당첨,010-0000-0004,광주시 테스트로 4,30100000000002,13700,0,"

BUSA_KEY = issued_orders.make_order_key("21103842199632", "부사 정품 소과 실중량 2kg(11-13과)")
CHESTNUT_KEY = issued_orders.make_order_key("7103820345139", "햇밤 대 1kg")


def _csv(*rows: str) -> bytes:
    return ("\n".join((HEADER,) + rows) + "\n").encode("utf-8-sig")


async def _body(response) -> bytes:
    return b"".join([chunk async for chunk in response.body_iterator])


@pytest.fixture
def endpoint(monkeypatch):
    """DB를 가로챈 event-winner-order 실행기. 반환: (run, recorded)."""
    recorded: list[dict] = []
    issued: set[str] = set()

    async def fake_exclusions(section, flag, reissue_stale=True):
        assert section == event_order.EVENT_SECTION and reissue_stale is False   # 당첨자는 재발주 없이 영구 제외
        return set(issued) if main._exclude_issued_enabled(flag) else set()

    async def fake_dates(section, flag):
        return {}

    async def fake_record(section, order_ids, filename, ymd):
        recorded.append({"section": section, "ids": list(order_ids), "filename": filename})

    monkeypatch.setattr(main, "_issued_exclusions", fake_exclusions)
    monkeypatch.setattr(main, "_issued_exclusion_dates", fake_dates)
    monkeypatch.setattr(main.database, "record_issued_orders", fake_record)

    def run(csv_bytes: bytes, exclude_issued: str = "true"):
        upload = UploadFile(file=BytesIO(csv_bytes), filename="winners_raw.csv")
        return asyncio.run(main.process_event_winner_order(
            winners_file=upload, exclude_issued=exclude_issued, user={"user_id": 1},
        ))

    run.issued = issued
    return run, recorded


def test_mixed_suppliers_zip_works_and_goguma_prizes_are_left_out(endpoint):
    run, recorded = endpoint
    response = run(_csv(ROW_CHESTNUT, ROW_BUSA, ROW_KKUL, ROW_HOBAK))

    assert response.media_type == "application/zip"
    stats_header = response.headers["x-stats"]
    assert stats_header.isascii()                     # 한글은 \uXXXX — latin-1 헤더 인코딩 오류 없음
    stats = json.loads(stats_header)
    assert stats["files"] == 2 and stats["winners"] == 2
    notes = " / ".join(stats["needs_check"])
    assert "고구마 경품 2건" in notes and "꿀당첨" in notes and "호박당첨" in notes

    with zipfile.ZipFile(BytesIO(asyncio.run(_body(response)))) as zf:
        names = zf.namelist()
        assert any(n.startswith("이벤트당첨_제주다팜_부사사과_발주(") for n in names)
        assert any(n.startswith("이벤트당첨_쥬얼리프룻_햇밤_발주(") for n in names)
        jeju_name = next(n for n in names if "제주다팜" in n)
        ws = load_workbook(BytesIO(zf.read(jeju_name))).active
        cells = [str(ws.cell(r, c).value or "") for r in range(2, ws.max_row + 1) for c in range(1, ws.max_column + 1)]
    assert "부사 정품 소과 실중량 2kg(11-13과)" in cells
    assert not any("고구마" in v for v in cells)       # 고구마 경품은 해달(고구마 화면)에서만 발주

    assert recorded == [{
        "section": "fruit_event",
        "ids": sorted([BUSA_KEY, CHESTNUT_KEY]),
        "filename": recorded[0]["filename"],
    }]
    assert recorded[0]["filename"].startswith("이벤트당첨_발주묶음(")


def test_reupload_skips_already_issued_winner(endpoint):
    run, recorded = endpoint
    run.issued.add(BUSA_KEY)
    response = run(_csv(ROW_CHESTNUT, ROW_BUSA))

    stats = json.loads(response.headers["x-stats"])
    assert stats["supplier"] == "쥬얼리프룻" and stats["winners"] == 1   # 부사 당첨자는 빠져 쥬얼리 1파일만
    assert stats["duplicate_skipped"] == 1 and "부사당첨" in stats["duplicate_skipped_names"]
    assert recorded[0]["ids"] == [CHESTNUT_KEY]


def test_reupload_all_issued_is_blocked_with_names(endpoint):
    run, recorded = endpoint
    run.issued.update({BUSA_KEY, CHESTNUT_KEY})
    with pytest.raises(HTTPException) as exc:
        run(_csv(ROW_CHESTNUT, ROW_BUSA, ROW_KKUL))
    assert exc.value.status_code == 400
    assert "이전에 이미 발주한 당첨자 2건" in exc.value.detail and "부사당첨" in exc.value.detail
    assert "고구마 경품 1건" in exc.value.detail
    assert recorded == []


def test_unchecked_exclude_box_issues_again(endpoint):
    run, _recorded = endpoint
    run.issued.add(BUSA_KEY)
    response = run(_csv(ROW_BUSA), exclude_issued="false")
    stats = json.loads(response.headers["x-stats"])
    assert stats["winners"] == 1 and "duplicate_skipped" not in stats


def test_goguma_only_csv_points_to_goguma_pages():
    with pytest.raises(ValueError) as exc:
        event_order.process(_csv(ROW_KKUL, ROW_HOBAK))
    assert "고구마 경품 2건" in str(exc.value) and "고구마 화면" in str(exc.value)
