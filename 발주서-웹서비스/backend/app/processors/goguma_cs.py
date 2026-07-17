"""고구마 쿠팡 온라인문의(CS) 조회 + 추천 답변 생성 + 답변 전송.

추천 답변 템플릿은 실제 CS 처리 예시(2026-07 쿠팡윙 캡처 14건)의 톤을 따른다:
- "안녕하세요 고객님"으로 시작, 사과 → 처리 안내, "감사합니다"로 마무리.
"""

import logging
from datetime import datetime, timedelta, timezone

from app import config
from app.coupang.client import coupang_goguma_client

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# 쿠팡 온라인문의 조회 API는 1회 조회 구간을 최대 7일로 제한한다.
_MAX_WINDOW_DAYS = 7
_MAX_PAGES = 20  # 폭주 방지 안전장치 (페이지당 50건)

# (카테고리 키, 화면 라벨, 매칭 키워드, 추천 답변) — 위에서부터 먼저 매칭된 것 사용.
# 순서 중요: 품질 문제(썩음/검은점)를 배송·환불보다 먼저 본다.
REPLY_TEMPLATES: list[tuple[str, str, list[str], str]] = [
    (
        "rotten",
        "썩음/상품불량",
        ["썩", "곰팡이", "부패", "상했", "상한", "상해", "물러", "무르", "벌레", "냄새"],
        "안녕하세요 고객님\n"
        "먼저 불편을 드려 정말 죄송합니다.\n"
        "빠른 확인과 처리를 위해 아래 사진 3가지를 남겨주시면 확인 후 바로 처리해드리겠습니다.\n"
        "1) 박스에 부착된 운송장 사진(송장 번호가 보이게끔)\n"
        "2) 해당 송장으로 박스 전체 사진\n"
        "3) 문제가 있는 고구마 사진\n"
        "확인되는 대로 교환/환불 처리 도와드리겠습니다.\n"
        "감사합니다",
    ),
    (
        "black_spot",
        "검은점(폴리페놀)",
        ["검은", "검정", "까만", "까맣", "반점", "흑점", "점이 있"],
        "안녕하세요 고객님\n"
        "고구마 표면이나 절단면의 검은 부분은 고구마에 함유된 폴리페놀 성분이 "
        "공기와 만나 산화되면서 나타나는 자연 현상으로, 품질에는 이상이 없습니다.\n"
        "그래도 드시기 불편한 부분이 있으시면 사진과 함께 남겨주시면 확인 후 처리 도와드리겠습니다.\n"
        "불편을 드려 죄송합니다. 감사합니다",
    ),
    (
        "size",
        "크기 불만",
        ["크기", "사이즈", "작아", "작은", "작네", "잘아", "잘고", "알이"],
        "안녕하세요 고객님\n"
        "생각하신 크기보다 작은 상품이 배송되어 실망을 드려 정말 죄송합니다.\n"
        "괜찮으시다면 반품 없이 받으신 상품은 그대로 드시는 조건으로 "
        "50% 부분 환불 처리를 도와드리고 싶습니다.\n"
        "원하시면 환불받으실 계좌번호, 성함, 연락처를 남겨주시면 바로 처리해드리겠습니다.\n"
        "다시 한번 죄송합니다. 감사합니다",
    ),
    (
        "cancel",
        "취소 요청",
        ["취소"],
        "안녕하세요 고객님\n"
        "주문 취소 요청 확인했습니다.\n"
        "아직 발송 전이라면 바로 취소 처리해드리겠습니다.\n"
        "다만 신선제품 특성상 이미 발송(배송중)된 경우에는 취소가 불가능한 점 양해 부탁드립니다.\n"
        "확인 후 처리 결과를 다시 안내드리겠습니다. 감사합니다",
    ),
    (
        "refund",
        "환불 요청",
        ["환불", "계좌"],
        "안녕하세요 고객님\n"
        "불편을 드려 죄송합니다.\n"
        "환불 처리를 도와드리겠습니다. 환불받으실 계좌번호, 성함, 연락처를 "
        "남겨주시면 확인 후 바로 처리해드리겠습니다.\n"
        "감사합니다",
    ),
    (
        "delivery",
        "배송 문의",
        ["배송", "언제", "출고", "송장", "발송", "도착", "안 와", "안와", "안옴"],
        "안녕하세요 고객님\n"
        "주문해주셔서 감사합니다.\n"
        "실제 출고 처리와 전산에 송장이 입력되는 시간에 차이가 있을 수 있습니다. "
        "정상적으로 오늘 발송되는 주문이라면 잠시 후 확인하시면 송장번호가 입력되어 있을 겁니다.\n"
        "조금만 기다려주시면 신선한 상품으로 빠르게 보내드리겠습니다. 감사합니다",
    ),
]

DEFAULT_TEMPLATE = (
    "기타",
    "안녕하세요 고객님\n"
    "문의 남겨주셔서 감사합니다.\n"
    "말씀하신 내용 확인 후 빠르게 처리해서 안내드리겠습니다.\n"
    "불편을 드렸다면 죄송합니다. 감사합니다",
)


def suggest_reply(content: str) -> tuple[str, str]:
    """문의 내용에서 카테고리를 추정해 (카테고리 라벨, 추천 답변)을 돌려준다."""
    text = (content or "").strip()
    for _key, label, keywords, reply in REPLY_TEMPLATES:
        if any(kw in text for kw in keywords):
            return label, reply
    return DEFAULT_TEMPLATE


def _normalize_inquiry(item: dict) -> dict:
    order_ids = item.get("orderIds") or []
    if not isinstance(order_ids, list):
        order_ids = [order_ids]
    content = str(item.get("content") or "")
    category, reply = suggest_reply(content)
    return {
        "inquiry_id": item.get("inquiryId"),
        "content": content,
        "inquiry_at": str(item.get("inquiryAt") or ""),
        "order_ids": [str(o) for o in order_ids if o],
        "category": category,
        "suggested_reply": reply,
    }


async def list_unanswered_inquiries(days: int = 7) -> dict:
    """최근 N일간 미답변 온라인문의를 수집하고 추천 답변을 붙인다."""
    days = max(1, min(int(days or 7), 30))
    today = datetime.now(KST).date()
    start = today - timedelta(days=days - 1)

    inquiries: list[dict] = []
    seen_ids: set = set()

    window_start = start
    while window_start <= today:
        window_end = min(window_start + timedelta(days=_MAX_WINDOW_DAYS - 1), today)
        page = 1
        while page <= _MAX_PAGES:
            res = await coupang_goguma_client.get_online_inquiries(
                inquiry_start_at=window_start.isoformat(),
                inquiry_end_at=window_end.isoformat(),
                answered_type="NOANSWER",
                page_num=page,
                page_size=50,
            )
            data = (res or {}).get("data") or {}
            items = data.get("content") or []
            for item in items:
                if not isinstance(item, dict):
                    continue
                normalized = _normalize_inquiry(item)
                if normalized["inquiry_id"] in seen_ids:
                    continue
                seen_ids.add(normalized["inquiry_id"])
                inquiries.append(normalized)

            pagination = data.get("pagination") or {}
            total_pages = int(pagination.get("totalPages") or 1)
            if page >= total_pages or not items:
                break
            page += 1
        window_start = window_end + timedelta(days=1)

    inquiries.sort(key=lambda x: x["inquiry_at"], reverse=True)
    return {
        "total": len(inquiries),
        "days": days,
        "period": f"{start.isoformat()} ~ {today.isoformat()}",
        "inquiries": inquiries,
    }


async def send_reply(inquiry_id: int, content: str) -> dict:
    """온라인문의에 답변을 전송한다. WING ID(replyBy) 미설정 시 명확한 오류."""
    reply_by = config.COUPANG_GOGUMA_WING_ID
    if not reply_by:
        raise ValueError(
            "쿠팡 WING 로그인 ID가 설정되지 않아 답변을 전송할 수 없습니다. "
            "fly secrets set COUPANG_GOGUMA_WING_ID=<쿠팡윙 로그인 아이디> 후 다시 시도해주세요."
        )
    text = (content or "").strip()
    if not text:
        raise ValueError("답변 내용이 비어 있습니다.")
    if not inquiry_id:
        raise ValueError("문의 ID가 없습니다.")

    await coupang_goguma_client.reply_online_inquiry(int(inquiry_id), text, reply_by)
    logger.info("쿠팡 CS 답변 전송 완료: inquiry_id=%s, %d자", inquiry_id, len(text))
    return {"status": "ok", "inquiry_id": inquiry_id}
