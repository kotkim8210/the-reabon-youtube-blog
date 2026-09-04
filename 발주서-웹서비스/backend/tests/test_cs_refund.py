"""cs_refund: 주문리스트 JSON 파싱 + 거래처 통보 템플릿 생성 검증.

주의: AdminPlus 라이브 조회는 여기서 테스트하지 않는다(로그인/네트워크 필요).
엔드포인트/컬럼은 order.list.bd.js(그리드 JS)에서 확인한 실제 구조:
  url  = /partner/order/json/od.list.bd.php?proc=json&<검색폼>
  cols = merge,no,regdate,ordcode,orditem,dlvcmp,dlvcode,ordname,buyhp,
         revname,revhp,revaddress,dlvamount,totalamount,statesprt,...
"""

import json

from app.processors.cs_refund import (
    OrderRow,
    _fmt_md,
    build_refund_template,
    parse_order_json,
)

# jqGrid cell-배열 형태 (colModel 순서 23개). dlvcmp='7' → 롯데택배.
FIXTURE_CELL = json.dumps(
    {
        "page": "1",
        "total": 1,
        "records": 1,
        "rows": [
            {
                "id": "1",
                "cell": [
                    "", "1", "2026-07-19 20:04:59", "26071920071310880010",
                    "<img src='/img/noimage.png'>거반도 1kg (4~10과 내외)<br>1개",
                    "7", "262021776730", "식품애착", "010-5700-7756",
                    "심현순", "050212285183",
                    "인천광역시 미추홀구 학익소로61번길 135 신동아5차 35동 1705호",
                    "￦0", "￦27,000", "배송중", "관리",
                    "b1", "p1", "op1", "opt", "5", "intord1", "5",
                ],
            }
        ],
    },
    ensure_ascii=False,
)

# 이름-딕셔너리 형태 (PHP가 named로 줄 수도 있어 양쪽 지원). dlvcmp 이미 '롯데택배'.
FIXTURE_NAMED = {
    "rows": [
        {
            "ordcode": "26071920071310880010",
            "regdate": "2026-07-19 20:04:59",
            "orditem": "거반도 1kg (4~10과 내외) 1개",
            "dlvcmp": "롯데택배",
            "dlvcode": "262021776730",
            "revname": "심현순",
            "revhp": "050212285183",
            "revaddress": "인천광역시 미추홀구 학익소로61번길 135 신동아5차 35동 1705호",
            "statesprt": "배송중",
        }
    ]
}


def _assert_simhyeonsun(o: OrderRow) -> None:
    assert o.order_code == "26071920071310880010"
    assert o.tracking == "262021776730"
    assert o.product == "거반도 1kg (4~10과 내외)"
    assert o.recipient == "심현순"
    assert o.courier == "롯데택배"
    assert o.order_datetime.startswith("2026-07-19")


def test_parse_cell_array_shape():
    orders = parse_order_json(FIXTURE_CELL)
    assert len(orders) == 1
    _assert_simhyeonsun(orders[0])
    assert orders[0].recipient_phone == "050212285183"


def test_parse_named_dict_shape():
    orders = parse_order_json(FIXTURE_NAMED)
    assert len(orders) == 1
    _assert_simhyeonsun(orders[0])


def test_fmt_md_strips_leading_zeros():
    assert _fmt_md("2026-07-19 20:04:59") == "7.19"
    assert _fmt_md("2026.07.01") == "7.1"
    assert _fmt_md("") == ""


def test_build_refund_template_matches_example():
    order = OrderRow(
        order_code="26071920071310880010",
        order_datetime="2026-07-19 20:04:59",
        product="거반도 1kg (4~10과 내외)",
        tracking="262021776730",
        recipient="심현순",
    )
    text = build_refund_template(order, "4개중 1개 변질되어 부분환불 문의", "7.21")
    expected = (
        "발주일자/수령일자 : 7.19/7.21\n"
        "고객 주문번호 : 26071920071310880010\n"
        "수취인 성함 : 심현순\n"
        "발주 상품명: 거반도 1kg (4~10과 내외)\n"
        "송장번호: 262021776730\n"
        "원하시는 환불비중 : 4개중 1개 변질되어 부분환불 문의"
    )
    assert text == expected


def test_end_to_end_parse_then_template():
    order = parse_order_json(FIXTURE_CELL)[0]
    text = build_refund_template(order, "4개중 1개 변질되어 부분환불 문의", "7.21")
    assert "고객 주문번호 : 26071920071310880010" in text
    assert "송장번호: 262021776730" in text
    assert "발주 상품명: 거반도 1kg (4~10과 내외)" in text
