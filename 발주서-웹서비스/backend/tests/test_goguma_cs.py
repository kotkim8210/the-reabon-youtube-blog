"""고구마 쿠팡 CS 추천 답변 로직 테스트."""

import pytest

from app.processors.goguma_cs import (
    DEFAULT_TEMPLATE,
    REPLY_TEMPLATES,
    _normalize_inquiry,
    suggest_reply,
)


@pytest.mark.parametrize(
    "content,expected_label",
    [
        ("고구마가 썩어서 왔어요 환불해주세요", "썩음/상품불량"),
        ("박스 열어보니 곰팡이가 있습니다", "썩음/상품불량"),
        ("고구마에 검은 점이 있는데 먹어도 되나요?", "검은점(폴리페놀)"),
        ("잘라보니 까만 부분이 있어요", "검은점(폴리페놀)"),
        ("생각보다 크기가 너무 작아요", "크기 불만"),
        ("알이 잘아서 실망했어요", "크기 불만"),
        ("주문 취소해주세요", "취소 요청"),
        ("환불 받고 싶어요", "환불 요청"),
        ("언제 배송되나요?", "배송 문의"),
        ("송장번호가 안 보여요", "배송 문의"),
        ("잘 먹었습니다", "기타"),
        ("", "기타"),
    ],
)
def test_suggest_reply_category(content, expected_label):
    label, reply = suggest_reply(content)
    assert label == expected_label
    assert reply.strip()


def test_quality_issues_win_over_refund_keyword():
    # 썩음 + 환불이 함께 나오면 품질 문제(사진 요청)가 우선
    label, reply = suggest_reply("고구마가 상해서 왔는데 환불해주세요")
    assert label == "썩음/상품불량"
    assert "운송장 사진" in reply


def test_all_templates_follow_cs_tone():
    replies = [reply for _k, _l, _kw, reply in REPLY_TEMPLATES] + [DEFAULT_TEMPLATE[1]]
    for reply in replies:
        assert reply.startswith("안녕하세요 고객님")
        assert reply.rstrip().endswith("감사합니다")


def test_normalize_inquiry():
    item = {
        "inquiryId": 12345,
        "content": "언제 배송되나요?",
        "inquiryAt": "2026-07-17 21:59:10",
        "orderIds": [111000222],
    }
    row = _normalize_inquiry(item)
    assert row["inquiry_id"] == 12345
    assert row["order_ids"] == ["111000222"]
    assert row["category"] == "배송 문의"
    assert row["suggested_reply"].startswith("안녕하세요 고객님")


def test_normalize_inquiry_missing_fields():
    row = _normalize_inquiry({})
    assert row["inquiry_id"] is None
    assert row["order_ids"] == []
    assert row["category"] == "기타"
