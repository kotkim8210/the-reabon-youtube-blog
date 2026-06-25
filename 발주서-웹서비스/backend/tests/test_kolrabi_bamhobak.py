# -*- coding: utf-8 -*-
"""회귀 테스트: 제주다팜 미니밤호박(보우짱 로얄과) 발주 매칭.

PYTHONPATH=backend python tests/test_kolrabi_bamhobak.py
"""
from app.processors import kolrabi_order as K
from app.processors import tracking_input as TI


def test_convert_bamhobak_option():
    # DeliveryList 옵션 '로얄 정품 {n}kg' → 제주다팜 발주 '제주 미니밤호박 보우짱 로얄과 {n}kg'
    assert (
        K.convert_bamhobak_option("[산지직송] 제주 미니 밤호박 보우짱 단호박", "1박스 로얄 정품 3kg")
        == "제주 미니밤호박 보우짱 로얄과 3kg"
    )
    assert (
        K.convert_bamhobak_option("제주 미니 밤호박 보우짱", "1박스 로얄 정품 10kg")
        == "제주 미니밤호박 보우짱 로얄과 10kg"
    )


def test_bamhobak_excludes_other_products():
    assert K.convert_bamhobak_option("콜라비", "3kg 1박스") is None
    assert K.convert_bamhobak_option("초당옥수수", "중품 10개") is None
    # 취급 중량(1·2·3·4·5·8·10kg)이 아니면 제외
    assert K.convert_bamhobak_option("제주 미니 밤호박 보우짱", "1박스 로얄 정품 7kg") is None


def test_bamhobak_tracking_semantic_key():
    keys = TI._semantic_option_keys("제주 미니 밤호박 보우짱 단호박", "1박스 로얄 정품 3kg")
    assert "bamhobak:3kg" in keys, keys


if __name__ == "__main__":
    test_convert_bamhobak_option()
    test_bamhobak_excludes_other_products()
    test_bamhobak_tracking_semantic_key()
    print("ALL TESTS PASSED")
