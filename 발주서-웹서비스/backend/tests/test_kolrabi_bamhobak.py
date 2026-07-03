# -*- coding: utf-8 -*-
"""회귀 테스트: 미니밤호박(보우짱) 발주처 분리.

2026-06: 1kg=제주다팜(kolrabi), 3·5·10kg=쥬얼리프룻(myeongi).

PYTHONPATH=backend python tests/test_kolrabi_bamhobak.py
"""
from app.processors import kolrabi_order as K
from app.processors import myeongi_order as M
from app.processors import tracking_input as TI


def test_jeju_bamhobak_only_1kg():
    # 제주다팜: 1kg만 발주 대상
    assert (
        K.convert_bamhobak_option("[산지직송] 제주 미니 밤호박 보우짱 단호박", "1박스 로얄 정품 1kg")
        == "제주 미니밤호박 보우짱 로얄과 1kg"
    )
    # 3·5·10kg은 제주다팜에서 제외(쥬얼리로 이관)
    assert K.convert_bamhobak_option("제주 미니 밤호박 보우짱", "1박스 로얄 정품 3kg") is None
    assert K.convert_bamhobak_option("제주 미니 밤호박 보우짱", "1박스 로얄 정품 5kg") is None
    assert K.convert_bamhobak_option("제주 미니 밤호박 보우짱", "1박스 로얄 정품 10kg") is None


def test_jewelry_bamhobak_3_5_10kg():
    # 쥬얼리프룻: 3·5·10kg 발주 대상
    assert (
        M._jewelry_bamhobak_option("[산지직송] 제주 미니 밤호박 보우짱 단호박", "1박스 로얄 정품 3kg")
        == "미니 밤호박 보우짱 로얄과 3kg"
    )
    assert (
        M._jewelry_bamhobak_option("제주 미니 밤호박 보우짱", "1박스 로얄 정품 10kg")
        == "미니 밤호박 보우짱 로얄과 10kg"
    )
    # 못난이 등급 보존
    assert (
        M._jewelry_bamhobak_option("제주 미니 밤호박 보우짱", "못난이 5kg")
        == "미니 밤호박 보우짱 못난이 5kg"
    )
    # 1kg은 쥬얼리 대상 아님(제주다팜)
    assert M._jewelry_bamhobak_option("제주 미니 밤호박 보우짱", "1박스 로얄 정품 1kg") is None


def test_jewelry_bamhobak_via_convert_option():
    # convert_option(발주·운송장 공용)에서도 3kg이 쥬얼리 품목명으로 변환
    assert (
        M.convert_option("1박스 로얄 정품 3kg", "제주 미니 밤호박 보우짱")
        == "미니 밤호박 보우짱 로얄과 3kg"
    )


def test_jewelry_potato_large_ships_as_special():
    assert M._jewelry_potato_option("햇 홍감자", "3kg(대)") == "햇 홍감자 특 3kg"
    assert M._jewelry_potato_option("햇 홍감자", "5kg(대)") == "햇 홍감자 특 5kg"


def test_bamhobak_excludes_other_products():
    assert M.is_jewelry_bamhobak_order("콜라비", "3kg 1박스") is False
    assert K.convert_bamhobak_option("초당옥수수", "중품 10개") is None


def test_bamhobak_tracking_semantic_key():
    keys = TI._semantic_option_keys("제주 미니 밤호박 보우짱 단호박", "1박스 로얄 정품 3kg")
    assert "bamhobak:3kg" in keys, keys


if __name__ == "__main__":
    test_jeju_bamhobak_only_1kg()
    test_jewelry_bamhobak_3_5_10kg()
    test_jewelry_bamhobak_via_convert_option()
    test_jewelry_potato_large_ships_as_special()
    test_bamhobak_excludes_other_products()
    test_bamhobak_tracking_semantic_key()
    print("ALL TESTS PASSED")
