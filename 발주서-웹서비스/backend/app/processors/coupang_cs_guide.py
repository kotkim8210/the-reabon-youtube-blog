from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


CsCategory = Literal[
    "cancel",
    "address_change",
    "delivery_delay",
    "damaged_freshness",
    "wrong_item",
    "missing_item",
    "change_of_mind",
    "general",
]
OrderStatus = Literal[
    "unknown",
    "payment_completed",
    "preparing",
    "shipping",
    "delivered",
    "canceled",
]


@dataclass(frozen=True)
class CsGuideInput:
    inquiry_text: str
    order_status: OrderStatus = "unknown"
    category: CsCategory | Literal["auto"] = "auto"
    product_name: str = ""
    option_name: str = ""
    photo_received: bool = False
    tracking_confirmed: bool = False
    listing_checked: bool = False


CATEGORY_LABELS: dict[CsCategory, str] = {
    "cancel": "취소 요청",
    "address_change": "주소 변경",
    "delivery_delay": "배송 지연",
    "damaged_freshness": "파손·신선도·품질",
    "wrong_item": "오배송",
    "missing_item": "수량 누락",
    "change_of_mind": "단순 변심",
    "general": "일반 문의",
}

CATEGORY_KEYWORDS: tuple[tuple[CsCategory, tuple[str, ...]], ...] = (
    (
        "address_change",
        ("주소 변경", "주소변경", "배송지 변경", "배송지변경", "주소를 바꿔", "주소를 바꾸", "주소 바꾸"),
    ),
    ("cancel", ("취소", "주문 취소", "구매 취소")),
    (
        "delivery_delay",
        (
            "언제 오",
            "배송 지연",
            "배송지연",
            "안 와",
            "안와",
            "안 왔",
            "안왔",
            "도착 안",
            "도착 언제",
            "출고",
            "미집하",
            "집하되지",
            "송장만 등록",
        ),
    ),
    ("wrong_item", ("오배송", "다른 상품", "다른상품", "잘못 왔", "엉뚱한")),
    ("missing_item", ("누락", "덜 왔", "수량 부족", "개수 부족", "한 개 안", "하나 안")),
    (
        "damaged_freshness",
        (
            "파손",
            "터졌",
            "깨졌",
            "깨져",
            "썩",
            "곰팡",
            "상했",
            "무름",
            "물러",
            "품질 불량",
            "안 신선",
            "신선하지",
            "맛이 없",
            "맛없",
            "당도가 낮",
            "당도 낮",
            "안 달",
            "크기가 작",
            "너무 작",
            "너무 크",
        ),
    ),
    ("change_of_mind", ("변심", "필요 없어", "필요없어", "마음에 안", "반품하고 싶")),
)

URGENT_KEYWORDS = (
    "먹고 아",
    "복통",
    "구토",
    "설사",
    "병원",
    "응급",
    "다쳤",
    "부상",
    "알레르기",
)
PHONE_RE = re.compile(r"(?:\+?82[-\s]?)?0?1[016789][-\s]?\d{3,4}[-\s]?\d{4}")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
ACCOUNT_RE = re.compile(r"\b\d{2,4}[-\s]\d{2,6}[-\s]\d{3,8}\b")


def _classify(text: str) -> CsCategory:
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    for category, keywords in CATEGORY_KEYWORDS:
        if any(keyword in normalized for keyword in keywords):
            return category
    return "general"


def _base_reply(product_name: str) -> str:
    product = product_name.strip()
    if product:
        return f"안녕하세요. 문의하신 {product} 주문을 확인하고 있습니다."
    return "안녕하세요. 문의하신 주문을 확인하고 있습니다."


def _status_guidance(order_status: OrderStatus) -> tuple[list[str], list[str]]:
    if order_status in {"payment_completed", "preparing"}:
        return (
            ["쿠팡 WING의 현재 주문 상태와 출고 처리 여부", "거래처 전달·포장 시작 여부"],
            ["출고 전인지 확인한 뒤 가능한 처리 범위를 안내합니다."],
        )
    if order_status == "shipping":
        return (
            ["택배사와 운송장 배송 흐름", "회수 또는 배송지 변경 가능 여부"],
            ["이미 출고된 주문은 택배 흐름을 먼저 확인하고 확답하지 않습니다."],
        )
    if order_status == "delivered":
        return (
            ["배송 완료 시각과 수령 장소", "실제 수령인 및 공동현관·경비실 보관 여부"],
            ["배송 완료 상태와 실제 수령 여부를 먼저 확인합니다."],
        )
    if order_status == "canceled":
        return (
            ["취소 완료 시각과 환불 진행 상태"],
            ["이미 취소된 주문은 추가 출고가 없는지 확인합니다."],
        )
    return (
        ["쿠팡 WING의 현재 주문 상태"],
        ["주문 상태를 확인한 뒤 가능한 처리 범위를 안내합니다."],
    )


def build_cs_guide(data: CsGuideInput) -> dict:
    text = data.inquiry_text.strip()
    if not text:
        raise ValueError("고객 문의 내용을 입력해 주세요.")

    category: CsCategory = _classify(text) if data.category == "auto" else data.category
    label = CATEGORY_LABELS[category]
    checks, steps = _status_guidance(data.order_status)
    do_not = [
        "확인 전 환불·재발송·취소 완료를 약속하지 않습니다.",
        "이 가이드만으로 주문 상태를 변경하거나 거래처에 자동 전송하지 않습니다.",
    ]
    decision_points = ["최종 환불·재발송·취소 여부는 관리자가 확인 후 결정합니다."]
    supplier_message = ""
    reply = _base_reply(data.product_name)

    if category == "cancel":
        checks.extend(["출고 전 취소 가능 여부", "이미 송장이 등록되었는지 여부"])
        steps.extend(["출고 전이면 WING과 거래처 양쪽의 취소 가능 여부를 확인합니다."])
        reply += " 현재 출고 단계와 취소 가능 여부를 확인한 뒤 정확히 안내드리겠습니다."
    elif category == "address_change":
        checks.extend(["변경할 주소를 채팅에 다시 받기보다 쿠팡 주문정보 변경 가능 여부", "이미 송장이 등록되었는지 여부"])
        steps.extend(["출고 전이면 안전한 공식 절차로 배송지 변경 가능 여부를 확인합니다."])
        do_not.append("고객의 상세 주소나 전화번호를 내부 메모에 불필요하게 복사하지 않습니다.")
        reply += " 현재 출고 단계에서 배송지 변경이 가능한지 확인한 뒤 안내드리겠습니다."
    elif category == "delivery_delay":
        checks.extend(["운송장 집하 여부", "택배사 이동 내역", "거래처 실제 출고일"])
        steps.extend(["송장만 등록되고 집하되지 않은 경우 거래처에 실제 출고 여부를 확인합니다."])
        supplier_message = "해당 주문의 실제 출고 여부와 집하 예정 시각을 확인 부탁드립니다."
        reply += " 운송장 이동 내역과 실제 출고 여부를 확인한 뒤 예상 일정을 안내드리겠습니다."
    elif category == "damaged_freshness":
        checks.extend(
            [
                "외부 박스·송장·상품 전체·문제 부위 사진",
                "문제가 있는 수량",
                "수령 직후 보관 상태와 상품 상세페이지 기준",
            ]
        )
        if data.photo_received:
            steps.append("받은 사진에서 송장, 전체 수량, 문제 부위가 모두 확인되는지 검토합니다.")
        else:
            steps.append("판단에 필요한 사진과 문제 수량을 먼저 요청합니다.")
        if not data.listing_checked:
            steps.append("상세페이지의 크기·등급·품질 안내와 실제 상품을 비교합니다.")
        supplier_message = "수령 사진과 문제 수량을 전달드리니 상품 상태 확인 및 처리 가능 범위를 회신 부탁드립니다."
        reply += " 정확한 확인을 위해 외부 박스, 송장, 상품 전체, 문제 부위와 문제 수량이 보이는 사진을 부탁드립니다."
    elif category == "wrong_item":
        checks.extend(["주문 상품·옵션과 수령 상품 비교", "외부 박스 송장과 수령 상품 전체 사진"])
        steps.extend(["동명이인 주문과 혼동되지 않도록 주문번호·옵션을 함께 대조합니다."])
        supplier_message = "주문 옵션과 실제 출고 상품이 다른지 출고 내역 확인 부탁드립니다."
        reply += " 주문 옵션과 실제 수령 상품을 확인할 수 있도록 송장과 상품 전체 사진을 부탁드립니다."
    elif category == "missing_item":
        checks.extend(["주문 수량·세트 구성", "박스 수와 실제 수령 수량", "분리 배송 여부"])
        steps.extend(["같은 주문의 분리 송장 또는 추가 박스가 있는지 먼저 확인합니다."])
        supplier_message = "주문 수량 대비 실제 출고 수량과 분리 배송 여부를 확인 부탁드립니다."
        reply += " 주문 수량과 분리 배송 여부를 확인한 뒤 빠르게 안내드리겠습니다."
    elif category == "change_of_mind":
        checks.extend(["상품 개봉·훼손 여부", "회수 가능 상태", "현재 주문·배송 상태"])
        steps.extend(["판매자센터의 현재 반품 가능 조건과 비용 부담 주체를 확인합니다."])
        reply += " 현재 배송 상태와 상품 상태를 확인한 뒤 반품 가능 범위를 안내드리겠습니다."
    else:
        checks.extend(["문의와 관련된 주문번호·상품·옵션이 일치하는지 여부"])
        steps.extend(["확인되지 않은 내용을 추정하지 않고 필요한 사실을 먼저 확인합니다."])
        reply += " 주문 상태와 문의 내용을 확인한 뒤 정확히 안내드리겠습니다."

    if data.tracking_confirmed and category == "delivery_delay":
        steps.append("확인한 배송 흐름을 기준으로 고객에게 현재 위치를 안내합니다.")

    urgent = any(keyword in text.lower() for keyword in URGENT_KEYWORDS)
    if urgent:
        urgency = "urgent"
        checks.insert(0, "섭취 중단 여부와 병원 진료 필요 여부")
        steps.insert(0, "건강·안전 관련 문의는 일반 보상 안내보다 먼저 관리자에게 즉시 공유합니다.")
        do_not.append("건강 피해의 원인이나 보상 범위를 임의로 단정하지 않습니다.")
        decision_points.insert(0, "건강·안전 관련 내용은 즉시 관리자 판단이 필요합니다.")
    elif category in {"damaged_freshness", "wrong_item", "missing_item"}:
        urgency = "attention"
    else:
        urgency = "normal"

    privacy_warning = bool(
        PHONE_RE.search(text) or EMAIL_RE.search(text) or ACCOUNT_RE.search(text)
    )
    return {
        "category": category,
        "category_label": label,
        "urgency": urgency,
        "summary": f"{label} 문의입니다. 사실 확인 후 관리자가 최종 처리해야 합니다.",
        "checks": list(dict.fromkeys(checks)),
        "steps": list(dict.fromkeys(steps)),
        "do_not": list(dict.fromkeys(do_not)),
        "reply_draft": reply,
        "supplier_message": supplier_message,
        "decision_points": list(dict.fromkeys(decision_points)),
        "privacy_warning": privacy_warning,
        "storage_notice": "문의 원문은 이 가이드 생성 과정에서 DB에 저장하지 않습니다.",
        "automation_notice": "답변 전송, 환불, 재발송, 취소, 주문 상태 변경은 자동으로 실행하지 않습니다.",
    }
