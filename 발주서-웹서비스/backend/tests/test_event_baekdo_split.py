"""이벤트 당첨자 발주: 백도 2·4kg 제주다팜 분리 출력 검증."""

from io import BytesIO

from openpyxl import load_workbook

from app.processors import event_order


def _csv(rows: list[list[str]]) -> bytes:
    header = "경품명,별명,개인 식별 정보 확인,이름,연락처,주소,주문 아이디,구매 금액,환불/취소 금액,환불/날짜/시간"
    lines = [header] + [",".join(r) for r in rows]
    return "\n".join(lines).encode("utf-8-sig")


def _row(prize: str, name: str) -> list[str]:
    return [prize, "닉", "Y", name, "010-1111-2222", "서울시 강남구 테스트로 1", "OID1", "10000", "", ""]


def test_event_supplier_split():
    assert event_order.event_supplier("백도 딱딱이복숭아 대과 2kg") == "jejudapam"
    assert event_order.event_supplier("백도 딱딱이복숭아 중과 4kg") == "jejudapam"
    # 2026-08-10: 쥬얼리 백도 발주 중단 → 1kg 당첨도 제주다팜(2kg로 승급)
    assert event_order.event_supplier("백도 딱딱이복숭아 중과 1kg") == "jejudapam"
    assert event_order.event_supplier("성주참외 3kg") == "jewelryfruit"
    assert event_order.event_supplier("대극천 복숭아 소과 1kg") == "jewelryfruit"


def test_event_product_name_baekdo_24kg_not_shinbi():
    # 회귀 방지: 백도 2·4kg가 신비로 둔갑하지 않고 제주다팜 발주명으로
    assert event_order.event_product_name("백도 딱딱이복숭아 대과 2kg") == "딱딱이 복숭아 대과 2kg"
    assert event_order.event_product_name("백도 딱딱이복숭아 중과 4kg") == "딱딱이 복숭아 중과 4kg"
    # 1kg 경품은 제주다팜 최소 규격 2kg로 올려서 발주 (이벤트 당첨자 전용 규칙)
    assert event_order.event_product_name("백도 딱딱이복숭아 중과 1kg") == "딱딱이 복숭아 중과 2kg"
    assert event_order.event_product_name(" 백도복숭아  대과 (1kg)") == "딱딱이 복숭아 대과 2kg"
    assert "신비" not in event_order.event_product_name("백도 딱딱이복숭아 대과 2kg")


def test_process_baekdo_only_goes_to_jejudapam():
    results = event_order.process(_csv([_row("백도 딱딱이복숭아 대과 2kg", "김당첨")]))
    assert len(results) == 1
    _bytes, filename, stats = results[0]
    assert "제주다팜" in filename and "백도" in filename
    assert stats["supplier"] == "제주다팜"
    assert stats["winners"] == 1
    ws = load_workbook(BytesIO(_bytes)).active
    found = any("딱딱이 복숭아 대과 2kg" == str(ws.cell(r, 8).value or "") for r in range(1, ws.max_row + 1))
    assert found


def test_process_mixed_returns_two_workbooks():
    results = event_order.process(_csv([
        _row("성주참외 3kg", "참외당첨"),
        _row("백도 딱딱이복숭아 중과 4kg", "백도당첨"),
        _row("백도 딱딱이복숭아 대과 1kg", "백도1kg당첨"),  # 1kg도 제주다팜(2kg 승급)
    ]))
    assert len(results) == 2
    by_supplier = {s["supplier"]: (b, f, s) for b, f, s in results}
    assert set(by_supplier) == {"쥬얼리프룻", "제주다팜"}
    assert by_supplier["쥬얼리프룻"][2]["winners"] == 1   # 참외만
    assert by_supplier["제주다팜"][2]["winners"] == 2     # 백도 4kg + 1kg(→2kg)


# ── 발주 칸에 당첨자 CSV를 올렸을 때: openpyxl 원본오류 대신 안내 (2026-07-27 실제 사고) ──
def test_delivery_slot_rejects_winners_csv_with_guidance():
    import pytest
    from fastapi import HTTPException

    from app.main import _require_xlsx

    csv_bytes = _csv([_row("백도 딱딱이복숭아 대과 2kg", "당첨자")])
    with pytest.raises(HTTPException) as exc:
        _require_xlsx(csv_bytes)
    assert exc.value.status_code == 400
    assert "이벤트 당첨자" in exc.value.detail
    assert "zip" not in exc.value.detail

    # 정상 xlsx는 통과
    from openpyxl import Workbook
    buf = BytesIO()
    Workbook().save(buf)
    assert _require_xlsx(buf.getvalue()) is None


# ── 이벤트 당첨자 백도 1kg → 제주다팜 2kg 승급 (2026-08-10) ──
def test_event_baekdo_1kg_promoted_to_jejudapam_2kg():
    """실제 CSV 경품명(' 백도복숭아  중과 (1kg)')이 빈 발주서로 나오던 사고.

    쥬얼리 백도 발주가 중단(is_myeongi_baekdo_excluded)이라 1kg 당첨자가 전부 걸러졌다.
    이벤트 당첨자만 2kg로 올려 제주다팜 발주서로 출력한다(일반 주문 경로는 불변).
    """
    results = event_order.process(_csv([
        _row(" 백도복숭아  중과 (1kg)", "도하림"),
        _row(" 백도복숭아  중과 (1kg)", "이영선"),
    ]))
    assert len(results) == 1
    _bytes, filename, stats = results[0]
    assert stats["supplier"] == "제주다팜"
    assert stats["total"] == 2 and stats["winners"] == 2
    ws = load_workbook(BytesIO(_bytes)).active
    names = [str(ws.cell(r, 8).value or "") for r in range(2, ws.max_row + 1)]
    assert names.count("딱딱이 복숭아 중과 2kg") == 2


def test_general_order_path_unchanged_by_event_rule():
    """일반 쿠팡 주문 경로는 그대로 — 이벤트 규칙이 새어나가면 안 된다."""
    from app.processors.kolrabi_order import convert_jeju_baekdo_option

    # 제주다팜 일반 발주: 2·4kg만 대상이고 1kg은 여전히 미대상
    assert convert_jeju_baekdo_option("햇 백도 딱딱이복숭아", "1박스 중과 2kg") == "딱딱이 복숭아 중과 2kg"
    assert convert_jeju_baekdo_option("햇 백도 딱딱이복숭아", "1박스 중과 1kg") is None
