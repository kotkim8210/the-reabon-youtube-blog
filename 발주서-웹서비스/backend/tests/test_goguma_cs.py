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


def test_normalize_inquiry_marks_status_and_thread():
    item = {
        "inquiryId": 12345,
        "content": "언제 배송되나요?",
        "inquiryAt": "2026-07-17 21:59:10",
        "orderIds": [111000222],
        "commentDtoList": [
            {"content": "안녕하세요 고객님, 오늘 발송됩니다.", "inquiryCommentAt": "2026-07-17 22:10:00"},
        ],
    }
    # unanswered_ids에 없으면 답변완료로 표시
    row = _normalize_inquiry(item, unanswered_ids=set())
    assert row["inquiry_id"] == 12345
    assert row["order_ids"] == ["111000222"]
    assert row["category"] == "배송 문의"
    assert row["answered"] is True
    assert row["comments"] == [{"content": "안녕하세요 고객님, 오늘 발송됩니다.", "at": "2026-07-17 22:10:00"}]
    assert row["suggested_reply"].startswith("안녕하세요 고객님")

    # unanswered_ids에 있으면 미답변
    row2 = _normalize_inquiry(item, unanswered_ids={12345})
    assert row2["answered"] is False


def test_normalize_inquiry_missing_fields():
    row = _normalize_inquiry({}, unanswered_ids=set())
    assert row["inquiry_id"] is None
    assert row["order_ids"] == []
    assert row["comments"] == []
    assert row["category"] == "기타"


def test_list_inquiries_sorts_unanswered_first(monkeypatch):
    """미답변이 위로, 그 다음 최신순. ALL로 전체 + NOANSWER로 미답변 ID 표시."""
    import asyncio
    from app.processors import goguma_cs

    all_items = [
        {"inquiryId": 1, "content": "썩었어요", "inquiryAt": "2026-07-20 10:00:00", "orderIds": [11]},
        {"inquiryId": 2, "content": "언제 오나요", "inquiryAt": "2026-07-22 10:00:00", "orderIds": [22]},
        {"inquiryId": 3, "content": "취소해주세요", "inquiryAt": "2026-07-21 10:00:00", "orderIds": [33]},
    ]

    async def fake_get(inquiry_start_at, inquiry_end_at, answered_type, page_num, page_size):
        if answered_type == "NOANSWER":
            content = [all_items[2]]  # id=3만 미답변
        else:
            content = all_items
        return {"data": {"content": content, "pagination": {"totalPages": 1}}}

    monkeypatch.setattr(goguma_cs.coupang_goguma_client, "get_online_inquiries", fake_get)

    res = asyncio.run(goguma_cs.list_inquiries(days=7))
    assert res["total"] == 3
    assert res["unanswered"] == 1
    assert res["answered"] == 2
    # 미답변(id=3) 먼저, 그 다음 답변완료 최신순(id=2가 id=1보다 최신)
    assert [q["inquiry_id"] for q in res["inquiries"]] == [3, 2, 1]
    assert res["inquiries"][0]["answered"] is False
    assert res["inquiries"][1]["answered"] is True
