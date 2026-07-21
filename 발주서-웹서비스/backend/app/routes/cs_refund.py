"""CS(상품 변질/부분환불) → 거래처 카카오톡 통보 템플릿 생성 API."""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import verify_token
from app.processors import cs_refund

router = APIRouter(prefix="/api/cs-refund", tags=["cs-refund"])


class RefundTemplateInput(BaseModel):
    recipient: str                       # 수취인 성함 (CS 문의의 고객명)
    note: str = ""                       # 원하시는 환불비중 (예: '4개중 1개 변질되어 부분환불 문의')
    received_date: Optional[str] = None  # 수령일자 'M.D'. 미지정 시 오늘(=배송완료일 근사).
    order_code: Optional[str] = None     # 동명이인/다건일 때 선택한 주문번호
    days: int = 30                       # 조회 기간(오늘 기준 N일 전 ~ 오늘)


@router.post("/generate")
async def generate(body: RefundTemplateInput, _token: dict = Depends(verify_token)):
    """수취인 성함으로 AdminPlus 주문을 찾아 거래처 통보 템플릿을 만든다.

    - 단건: 템플릿 문자열(status='ok') 반환.
    - 동명이인/다건: 후보 목록(status='multiple') 반환 → 프론트에서 주문 선택 후 order_code로 재요청.
    """
    recipient = (body.recipient or "").strip()
    if not recipient:
        return {"status": "error", "message": "수취인 성함을 입력하세요."}

    now = datetime.now(cs_refund.KST)
    days = max(1, min(body.days, 180))
    end = now.strftime("%Y-%m-%d")
    start = (now - timedelta(days=days)).strftime("%Y-%m-%d")

    try:
        orders = await cs_refund.fetch_orders(recipient, start, end)
    except cs_refund.CsRefundError as exc:
        return {"status": "error", "message": str(exc)}
    except Exception as exc:  # noqa: BLE001 - 원인을 사용자에게 그대로 노출
        return {"status": "error", "message": f"AdminPlus 조회 실패: {exc}"}

    # 검색은 부분일치라 다른 이름이 섞일 수 있어, 정확히 같은 수취인명을 우선한다.
    exact = [o for o in orders if o.recipient == recipient]
    matches = exact or orders

    if body.order_code:
        picked = [o for o in matches if o.order_code == body.order_code]
        matches = picked or matches

    if not matches:
        return {
            "status": "empty",
            "message": f"'{recipient}' 님 주문을 최근 {days}일에서 찾지 못했습니다. 기간(days)을 늘려보세요.",
        }

    received = (body.received_date or "").strip() or cs_refund.today_md()

    # 동명이인 방지: 이름만으로 2건 이상이면 주소·상품 확인용 후보를 돌려준다.
    if len(matches) > 1 and not body.order_code:
        return {
            "status": "multiple",
            "message": f"'{recipient}' 님 주문이 {len(matches)}건입니다. 주소·상품 확인 후 선택하세요.",
            "candidates": [cs_refund.candidate_dict(o) for o in matches],
        }

    order = matches[0]
    text = cs_refund.build_refund_template(order, body.note, received)
    return {
        "status": "ok",
        "text": text,
        "received_date": received,
        "order": cs_refund.candidate_dict(order),
    }
