"""쿠팡 상품·옵션 → 실제 발주처 판정 (발주 로직 재사용).

발주처가 옵션별로 갈리거나 이관되는 품목(미니밤호박·백도 딱딱이복숭아·홍감자)은
발주 기능만 고치고 마진방어(supplier_price_monitor) 설정을 잊으면 소싱현황이 옛 발주처
공급가로 계산된다(2026-07 백도 이관 때 실제 발생).

그래서 발주처 판정은 **발주 프로세서의 변환 함수를 그대로 호출**해 한 군데서만 결정하고,
마진방어 옵션에 적어둔 쿠팡 상품·옵션과 대조하는 테스트(test_margin_order_routing_sync)가
불일치를 잡는다. 발주 라우팅이 바뀌면 그 테스트가 깨지므로 마진 설정도 같이 고치게 된다.
"""

from __future__ import annotations

from app.processors import kolrabi_order, myeongi_order

JEJUDAPAM = "제주다팜"
JEWELRYFRUIT = "쥬얼리프룻"


def resolve_order_supplier(product_name: object, option_text: object) -> str | None:
    """쿠팡 상품명·옵션으로 발주처를 판정한다. 판정 불가(대상 아님)면 None."""
    # 제주다팜(콜라비 메뉴) — 변환 결과가 있어야 실제 발주 대상
    if kolrabi_order.convert_bamhobak_option(product_name, option_text):
        return JEJUDAPAM
    if kolrabi_order.convert_jeju_baekdo_option(product_name, option_text):
        return JEJUDAPAM
    if kolrabi_order.is_jeju_potato_order(product_name, option_text) and kolrabi_order.convert_potato_option(
        product_name, option_text
    ):
        return JEJUDAPAM
    if kolrabi_order.convert_apple_option(product_name, option_text):
        return JEJUDAPAM
    if kolrabi_order.convert_hongro_option(product_name, option_text):
        return JEJUDAPAM

    # 쥬얼리프룻(명이 메뉴)
    if myeongi_order.is_myeongi_baekdo_excluded(product_name, option_text):
        # 백도(딱복)는 쥬얼리 시즌 종료로 발주 중단(2026-08-10). 2·4kg은 위에서 제주다팜으로
        # 잡히고, 그 밖(1kg 등)은 발주처 없음 → None. 시즌 재개 시 이 분기를 되돌린다.
        return None
    if myeongi_order.is_jewelry_bamhobak_order(product_name, option_text):
        return JEWELRYFRUIT

    return None
