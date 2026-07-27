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
    assert event_order.event_supplier("백도 딱딱이복숭아 중과 1kg") == "jewelryfruit"
    assert event_order.event_supplier("성주참외 3kg") == "jewelryfruit"
    assert event_order.event_supplier("대극천 복숭아 소과 1kg") == "jewelryfruit"


def test_event_product_name_baekdo_24kg_not_shinbi():
    # 회귀 방지: 백도 2·4kg가 신비로 둔갑하지 않고 제주다팜 발주명으로
    assert event_order.event_product_name("백도 딱딱이복숭아 대과 2kg") == "딱딱이 복숭아 대과 2kg"
    assert event_order.event_product_name("백도 딱딱이복숭아 중과 4kg") == "딱딱이 복숭아 중과 4kg"
    name_1kg = event_order.event_product_name("백도 딱딱이복숭아 중과 1kg")
    assert "백도 딱딱이 복숭아 중과 1kg" in name_1kg
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
        _row("백도 딱딱이복숭아 대과 1kg", "백도1kg당첨"),  # 1kg → 쥬얼리
    ]))
    assert len(results) == 2
    by_supplier = {s["supplier"]: (b, f, s) for b, f, s in results}
    assert set(by_supplier) == {"쥬얼리프룻", "제주다팜"}
    assert by_supplier["쥬얼리프룻"][2]["winners"] == 2   # 참외 + 백도 1kg
    assert by_supplier["제주다팜"][2]["winners"] == 1     # 백도 4kg
