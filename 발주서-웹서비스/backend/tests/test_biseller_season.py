"""비셀러 김장·수산 시즌상품 발주 — BS-<상품번호> 코드 매칭 (2026-10-27 신규)."""

from io import BytesIO

from openpyxl import Workbook, load_workbook

from app.processors import biseller_order


def _delivery(rows: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    for i, r in enumerate(rows):
        row = i + 2
        ws.cell(row, 3, r.get("order_no", f"OID{i}"))
        ws.cell(row, 11, r.get("product", "국산 김장김치 전라도 포기 배추김치"))
        ws.cell(row, 12, r.get("option", "3kg, 1개"))
        if r.get("code"):
            ws.cell(row, 17, r["code"])          # Q열 업체상품코드
        ws.cell(row, 23, r.get("qty", 1))
        ws.cell(row, 27, r.get("name", f"수취인{i}"))
        ws.cell(row, 28, "0504-1234-5678")
        ws.cell(row, 29, r.get("zipcode", "16846"))
        ws.cell(row, 30, "경기도 용인시 수지구 풍덕천동 1209")
        ws.cell(row, 31, r.get("memo", "문 앞"))
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_bs_code():
    assert biseller_order.parse_bs_code("BS-12326217") == "12326217"
    assert biseller_order.parse_bs_code(" bs-5493 ") == "5493"
    assert biseller_order.parse_bs_code("PL0013453") is None
    assert biseller_order.parse_bs_code("") is None


def test_bs_code_order_uses_branduid_as_goods_no():
    """백골뱅이탕 대 1팩(BS-12326217) 실주문(2026-10-27) — 상품번호=branduid, 옵션번호 0."""
    payload = _delivery([{
        "product": "백골뱅이탕 밀키트 동해안 백골뱅이 골뱅이탕 캠핑 밀키트",
        "option": "1개 대 1팩", "code": "BS-12326217", "name": "강현진",
    }])
    out, filename, stats = biseller_order.process(payload)
    assert stats["total"] == 1
    assert filename.startswith("비셀러발주(") and filename.endswith(").xlsx")
    ws = load_workbook(BytesIO(out)).active
    # 1·2행 헤더 유지, 3행(읽기전용/필수 입력값 라벨)은 비어 있어야 비셀러 업로드가 인식한다
    assert ws.cell(1, 2).value == "상품번호" and ws.cell(2, 2).value == "goods_no"
    assert all(ws.cell(3, c).value in (None, "") for c in range(1, 17))
    assert ws.cell(4, 2).value == 12326217
    assert ws.cell(4, 5).value == 0
    assert ws.cell(4, 9).value == 1
    assert ws.cell(4, 12).value == "강현진"
    assert ws.cell(4, 14).value == "16846"
    # 카탈로그에 있으면 상품코드·상품명·공급가까지 채운다
    if "12326217" in biseller_order.load_catalog():
        assert ws.cell(4, 3).value == "PL0013453"
        assert "백골뱅이탕" in ws.cell(4, 4).value
        assert ws.cell(4, 8).value == 26250
    # 발주 이력 키는 DeliveryList 옵션 원문
    assert stats["options"][0]["coupang_option_keyword"] == "1개 대 1팩"
    assert stats["options"][0]["orders"][0]["order_id"] == "OID0"


def test_unknown_bs_code_still_issued_with_warning():
    payload = _delivery([{"product": "새 비셀러 상품", "option": "1kg", "code": "BS-99999999", "name": "미등록손님"}])
    out, _, stats = biseller_order.process(payload)
    assert stats["total"] == 1 and stats.get("catalog_missing") == 1
    assert any("BS-99999999" in note for note in stats["needs_check"])
    ws = load_workbook(BytesIO(out)).active
    assert ws.cell(4, 2).value == 99999999 and ws.cell(4, 5).value == 0


def test_non_biseller_rows_ignored_and_galbi_mixed():
    payload = _delivery([
        {"product": "국내산 햇밤 생알밤", "option": "3kg 1박스", "name": "밤손님"},            # 쥬얼리 몫
        {"product": "한입 LA갈비 양념갈비", "option": "800g 2개", "name": "갈비손님"},          # 종전 갈비 경로
        {"product": "국산 김장김치", "option": "3kg, 1개", "code": "BS-1905", "name": "김치손님", "qty": 2},
    ])
    out, filename, stats = biseller_order.process(payload)
    assert stats["total"] == 2
    assert filename.startswith("비셀러발주(")
    ws = load_workbook(BytesIO(out)).active
    assert [ws.cell(4, 2).value, ws.cell(5, 2).value] == [6120, 1905]
    assert ws.cell(5, 9).value == 2
    assert ws.cell(6, 2).value is None


def test_upsert_catalog_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(biseller_order, "CATALOG_PATH", tmp_path / "catalog.json")
    assert biseller_order.upsert_catalog([{"goods_no": "777", "code": "PL1", "name": "테스트", "price": 1000}]) == {
        "added": 1, "updated": 0, "total": 1,
    }
    assert biseller_order.upsert_catalog([{"goods_no": 777, "price": 2000}])["updated"] == 1
    item, in_catalog = biseller_order.resolve_bs_item("777")
    assert in_catalog and item["price"] == 2000 and item["code"] == "PL1"
