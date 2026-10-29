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


def test_output_uses_shared_strings_for_beseller_upload():
    """비셀러 업로드는 공용 문자열표(sharedStrings)만 읽는다 — 인라인 문자열이면 '상품번호 항목이 없습니다'(2026-10-28)."""
    import re
    import zipfile
    import xml.etree.ElementTree as ET

    payload = _delivery([
        {"product": "백골뱅이탕 밀키트", "option": "1개 대 1팩", "code": "BS-12326217", "name": "강현진"},
        {"product": "청어 과메기", "option": "1개 4미 8쪽 야채 혼술세트", "code": "BS-2174", "name": "권민찬"},
    ])
    out, _filename, stats = biseller_order.process(payload)
    assert stats["total"] == 2
    z = zipfile.ZipFile(BytesIO(out))
    assert "xl/sharedStrings.xml" in z.namelist()
    sheet = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "inlineStr" not in sheet
    assert "/xl/sharedStrings.xml" in z.read("[Content_Types].xml").decode("utf-8")
    assert "sharedStrings.xml" in z.read("xl/_rels/workbook.xml.rels").decode("utf-8")

    # 공용 문자열표만 읽는 단순 리더로 1행 제목·4행 상품번호를 읽을 수 있어야 한다
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    sst = ["".join(t.text or "" for t in si.iter(ns + "t"))
           for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(ns + "si")]
    cells = {}
    for c in ET.fromstring(sheet.encode("utf-8")).iter(ns + "c"):
        v = c.find(ns + "v")
        if v is not None:
            cells[c.get("r")] = sst[int(v.text)] if c.get("t") == "s" else v.text
    assert cells["B1"] == "상품번호" and cells["B2"] == "goods_no"
    assert cells["B4"] == "12326217" and cells["B5"] == "2174"
    assert not any(re.fullmatch(r"[A-P]3", ref) for ref in cells)   # 3행은 비어 있어야 한다

    # openpyxl로 읽어도 값이 그대로여야 한다(이메일 첨부·운송장 입력 등 내부 처리 호환)
    ws = load_workbook(BytesIO(out)).active
    assert ws.cell(1, 2).value == "상품번호" and ws.cell(4, 2).value == 12326217
    assert ws.cell(4, 12).value == "강현진" and ws.cell(5, 12).value == "권민찬"


def test_to_shared_strings_is_idempotent():
    payload = _delivery([{"product": "청어 과메기", "option": "4미", "code": "BS-2174", "name": "권민찬"}])
    out, _fn, _stats = biseller_order.process(payload)
    assert biseller_order.to_shared_strings(out) == out


def test_output_uses_relative_paths_like_excel():
    """비셀러 업로드는 openpyxl 절대경로(/xl/worksheets/sheet1.xml)를 못 따라간다 → 상대경로로(2026-10-29 실제 업로드로 확인)."""
    import zipfile

    payload = _delivery([{"product": "청어 과메기", "option": "4미", "code": "BS-2174", "name": "권민찬"}])
    out, _fn, _stats = biseller_order.process(payload)
    z = zipfile.ZipFile(BytesIO(out))
    names = [i.filename for i in z.infolist()]
    assert names[0] == "[Content_Types].xml"
    for name in names:
        if name.endswith(".rels"):
            assert 'Target="/' not in z.read(name).decode("utf-8"), name
    rels = z.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    assert 'Target="worksheets/sheet1.xml"' in rels and 'Target="sharedStrings.xml"' in rels
    ws = load_workbook(BytesIO(out)).active
    assert ws.cell(1, 2).value == "상품번호" and ws.cell(4, 2).value == 2174


def test_to_shared_strings_writes_raw_korean_like_excel():
    """lxml이 깔린 PC의 openpyxl은 한글을 &#…; 로 쓴다 → 엑셀처럼 원래 글자로 풀어 공용 문자열표에 넣는다(2026-10-28)."""
    import zipfile

    wb = Workbook()
    ws = wb.active
    ws["A1"] = "상품번호"
    ws["B1"] = "A&B <x>"
    buf = BytesIO()
    wb.save(buf)
    zin = zipfile.ZipFile(BytesIO(buf.getvalue()))
    src = BytesIO()
    with zipfile.ZipFile(src, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "xl/worksheets/sheet1.xml":
                ncr = "".join(f"&#{ord(ch)};" for ch in "상품번호")
                data = data.decode("utf-8").replace("상품번호", ncr).encode("utf-8")
            zout.writestr(info, data)
    sheet_src = zipfile.ZipFile(BytesIO(src.getvalue())).read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "&#49345;" in sheet_src                     # 입력은 숫자 참조 상태

    out = biseller_order.to_shared_strings(src.getvalue())
    sst = zipfile.ZipFile(BytesIO(out)).read("xl/sharedStrings.xml").decode("utf-8")
    assert "<t>상품번호</t>" in sst and "&#" not in sst
    assert "A&amp;B &lt;x&gt;" in sst                  # 특수문자 이스케이프는 유지
    ws2 = load_workbook(BytesIO(out)).active
    assert ws2["A1"].value == "상품번호" and ws2["B1"].value == "A&B <x>"
