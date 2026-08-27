"""홍로사과(가을햇사과) 제주다팜 발주·운송장·마진방어 (2026-08-27 신규)."""

from io import BytesIO

from openpyxl import Workbook, load_workbook

from app.processors import kolrabi_order
from app.processors.tracking_input import _semantic_option_keys

COUPANG_PRODUCT = "2026 햇 안동 고당도 홍로사과 아삭한 꿀사과 산지직송 제철 햇사과"


def test_all_20_options_map_to_jeju_names():
    for grade in ("소과", "중소과", "중대과", "대과"):
        for kg in ("1.5", "2", "3", "4", "5"):
            got = kolrabi_order.convert_hongro_option(COUPANG_PRODUCT, f"1박스 {grade} {kg}kg")
            assert got, (grade, kg)
            assert grade in got and f"{kg}kg" in got


def test_real_option_text_from_coupang():
    assert (
        kolrabi_order.convert_hongro_option(COUPANG_PRODUCT, "1박스 소과 1.5kg(7-10과내)")
        == "가을햇사과(홍사과) 가정용 소과 포장재포함 1.5kg(7-10과내)"
    )
    # 중소과/중대과가 소과/대과로 잘못 잡히지 않는다
    assert "중소과" in kolrabi_order.convert_hongro_option(COUPANG_PRODUCT, "1박스 중소과 2kg")
    assert "중대과" in kolrabi_order.convert_hongro_option(COUPANG_PRODUCT, "1박스 중대과 3kg")


def test_hongro_and_cheongsagwa_are_exclusive():
    """청사과(아오리)와 홍로가 서로 섞이면 안 된다."""
    assert kolrabi_order.convert_apple_option(COUPANG_PRODUCT, "1박스 소과 2kg") is None
    green = "[핫딜] 새콤아삭 고당도선별 아오리사과 여름 청사과 풋사과"
    assert kolrabi_order.convert_hongro_option(green, "1박스 가정용 대과 4kg") is None
    assert kolrabi_order.convert_apple_option(green, "1박스 가정용 대과 4kg") is not None
    # 취급 안 하는 중량은 제외
    assert kolrabi_order.convert_hongro_option(COUPANG_PRODUCT, "1박스 소과 10kg") is None


def _delivery(rows: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    for i, r in enumerate(rows):
        row = i + 2
        ws.cell(row, 3, r.get("order_no", f"OID{i}"))
        ws.cell(row, 11, r["product"])
        ws.cell(row, 12, r["option"])
        ws.cell(row, 23, r.get("qty", 1))
        ws.cell(row, 27, r.get("name", f"수취인{i}"))
        ws.cell(row, 28, "010-0000-0000")
        ws.cell(row, 29, "12345")
        ws.cell(row, 30, "서울시 어딘가")
        ws.cell(row, 31, "")
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_process_hongro_and_process_outputs():
    data = _delivery([
        {"product": COUPANG_PRODUCT, "option": "1박스 소과 1.5kg(7-10과내)", "name": "Kevin"},
        {"product": COUPANG_PRODUCT, "option": "1박스 대과 5kg", "name": "김광은"},
        {"product": "콜라비 정품", "option": "3kg"},
    ])
    result = kolrabi_order.process_hongro(data)
    assert result is not None
    _bytes, filename, stats = result
    assert "홍로사과" in filename
    assert stats["total"] == 2
    ws = load_workbook(BytesIO(_bytes)).active
    assert str(ws.cell(2, 8).value).startswith("가을햇사과(홍사과)")

    labels = {st.get("product") for _b, _f, st in kolrabi_order.process_outputs(data)}
    assert "홍로사과(제주다팜)" in labels


def test_tracking_semantic_keys_match_both_sides():
    ol = _semantic_option_keys("가을햇사과(홍사과) 가정용 소과 포장재포함 1.5kg(7-10과내)", "")
    dl = _semantic_option_keys(COUPANG_PRODUCT, "1박스 소과 1.5kg(7-10과내)")
    assert "hongro:소과:1.5kg" in ol
    assert "hongro:소과:1.5kg" in dl
    # 등급 혼동 방지
    js = _semantic_option_keys("가을햇사과(홍사과) 가정용 중소과 포장재포함 2kg(7-8과내외)", "")
    assert "hongro:중소과:2kg" in js and "hongro:소과:2kg" not in js


def test_margin_monitor_matches_order_mapping():
    from app import supplier_price_monitor as spm

    config = spm.MONITOR_CONFIGS["hongro-jeju"]
    assert config.product_code == "10001216"
    assert config.template_path.exists()
    assert [o.row for o in config.options] == list(range(8, 28))
    for o in config.options:
        assert spm.option_supplier_name(o, config) == "제주다팜"
        converted = kolrabi_order.convert_hongro_option(o.coupang_product, o.coupang_option)
        assert converted == o.supplier_option_name, (o.label, converted, o.supplier_option_name)


def test_margin_template_rows_align():
    from app import supplier_price_monitor as spm

    config = spm.MONITOR_CONFIGS["hongro-jeju"]
    ws = load_workbook(config.template_path)["쥬얼리프룻"]
    assert [str(ws.cell(r, 3).value) for r in range(8, 28)] == ["제주다팜"] * 20
    # 공급가(I열)는 실측값이 채워져 있어야 첫 실행부터 비교가 된다
    assert all(isinstance(ws.cell(r, 9).value, (int, float)) for r in range(8, 28))
    assert ws.cell(8, 9).value == 6300 and ws.cell(27, 9).value == 17500
