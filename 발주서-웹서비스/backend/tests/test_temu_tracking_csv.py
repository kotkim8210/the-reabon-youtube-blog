# -*- coding: utf-8 -*-
"""회귀 테스트: 테무 송장 대량등록 CSV 헤더 변형 + 택배사 매핑.

버그(2026-06-25): 테무 CSV order_export 의 항목ID 헤더가 '상품 주문 ID'(xlsx 는 '주문 상품 ID')라
헤더 검증이 거부 → 송장입력이 전혀 안 됐음. 또 송장파일에 '한진'이 명시돼도 '롯데택배'로 등록되던 문제.

프레임워크 없이 단독 실행: PYTHONPATH=backend python tests/test_temu_tracking_csv.py
"""
from app.processors import temu_tracking as T


def test_csv_item_id_header_variant():
    # CSV 내보내기 표기 '상품 주문 ID' (단어순서가 xlsx 와 반대)
    csv_text = (
        "주문 ID,상품 주문 ID,주문 상태,발송할 수량,수령인 이름,수령인 전화번호,선택 사항,제품 이름\n"
        "PO-1,IT-1,미발송,1,홍길동,+82 010 1111 2222,10kg,꿀고구마 10kg (중상)\n"
    )
    orders = T._parse_temu_export(csv_text.encode("utf-8-sig"), "order_export.csv")
    assert len(orders) == 1, f"기대 1건, 실제 {len(orders)}"
    o = orders[0]
    assert o["order_id"] == "PO-1", o
    # 항목ID가 PO 로 폴백되지 않고 '상품 주문 ID' 값으로 정확히 매핑돼야 함
    assert o["item_id"] == "IT-1", o


def test_xlsx_item_id_header_variant_still_works():
    # 기존 xlsx 표기 '주문 상품 ID' 도 계속 통과해야 함(회귀 방지)
    csv_text = (
        "주문 ID,주문 상품 ID,주문 상태,발송할 수량,수령인 이름,선택 사항,제품 이름\n"
        "PO-2,IT-2,미발송,2,김철수,3kg,꿀고구마 3kg\n"
    )
    orders = T._parse_temu_export(csv_text.encode("utf-8-sig"), "order_export.csv")
    assert len(orders) == 1 and orders[0]["item_id"] == "IT-2", orders


def test_carrier_name_mapping():
    assert T._temu_carrier_name("한진") == "한진택배"
    assert T._temu_carrier_name("Hanjin") == "한진택배"
    assert T._temu_carrier_name("롯데택배") == "롯데택배"
    assert T._temu_carrier_name("CJ대한통운") == "CJ 대한통운"


if __name__ == "__main__":
    test_csv_item_id_header_variant()
    test_xlsx_item_id_header_variant_still_works()
    test_carrier_name_mapping()
    print("ALL TESTS PASSED")
