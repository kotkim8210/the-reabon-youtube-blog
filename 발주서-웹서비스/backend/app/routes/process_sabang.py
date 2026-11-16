"""사방넷 연동 라우트. main.py에서 분리(2026-11-17)."""

import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from io import BytesIO

from app import config
from app.auth import verify_token
from app.processors import sabang_fruit
from app.sabang import client as sabang_client
from app.sabang.client import SabangApiError
from app.api_common import KST
from app.routes.process_fruit import process_kolrabi_order, process_myeongi_order

logger = logging.getLogger("app.main")  # 분리 전과 같은 로그 이름

router = APIRouter()

# ── 사방넷 연동 (과일/Itsoft: 쥬얼리·제주다팜 자동수집 + 송장전송) ──


@router.get("/api/sabang/xml/{token}")
async def serve_sabang_request_xml(token: str):
    """사방넷이 xml_url 파라미터로 가져가는 요청 XML (임시 토큰·EUC-KR)."""
    xml_bytes = sabang_client.get_request_xml(token)
    if xml_bytes is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="XML not found or expired")
    return Response(content=xml_bytes, media_type="application/xml; charset=euc-kr")


@router.get("/api/sabang/status")
async def sabang_status(_token: dict = Depends(verify_token)):
    return {
        "configured": bool(config.SABANG_COMPANY_ID and config.SABANG_AUTH_KEY),
        "admin_url": config.SABANG_ADMIN_URL,
        "tak_code": config.SABANG_TAK_CODE,
        "tak_code_lotte": config.SABANG_TAK_CODE_LOTTE,
        "tak_code_cj": config.SABANG_TAK_CODE_CJ,
        "order_statuses": config.SABANG_ORDER_STATUSES,
    }


@router.post("/api/sabang/test-connection")
async def sabang_test_connection(_token: dict = Depends(verify_token)):
    """쇼핑몰 목록 조회로 사방넷 연동키 유효성 확인."""
    try:
        return await sabang_client.test_connection()
    except SabangApiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.message)


@router.get("/api/sabang/courier-codes")
async def sabang_courier_codes(
    days: int = 14,
    _token: dict = Depends(verify_token),
):
    """최근 출고완료(004) 주문에서 택배사코드(DELIVERY_ID)를 자동 수집·추정.

    거래처가 쓰는 택배사 코드를 몰라도, 실제 발송된 주문의 코드·송장 패턴
    (롯데 체크섬)으로 어떤 코드가 어느 택배사인지 알아낸다.
    """
    days = max(1, min(int(days or 14), 60))
    to_date = datetime.now(KST).date()
    from_date = to_date - timedelta(days=days - 1)
    try:
        orders = await sabang_client.fetch_orders(
            from_date.strftime("%Y%m%d"),
            to_date.strftime("%Y%m%d"),
            statuses=["004"],
        )
    except SabangApiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.message)
    codes = sabang_fruit.summarize_courier_codes(orders)
    return {"days": days, "total_orders": len(orders), "codes": codes}


def _sabang_delivery_upload(orders: list[dict]) -> UploadFile:
    ymd = datetime.now(KST).strftime("%Y%m%d")
    delivery_bytes = sabang_fruit.orders_to_delivery_xlsx(orders)
    return UploadFile(file=BytesIO(delivery_bytes), filename=f"DeliveryList_sabang_{ymd}.xlsx")


def _ymd_compact(date_str: str) -> str:
    return (date_str or "").replace("-", "").strip()


@router.post("/api/process/sabang-myeongi-order")
async def process_sabang_myeongi_order(
    from_date: str = Form(...),
    to_date: str = Form(...),
    toss_from_date: str = Form(""),
    toss_to_date: str = Form(""),
    exclude_issued: str = Form("true"),
    user: dict = Depends(verify_token),
):
    """사방넷 주문 자동수집 → 쥬얼리프룻 발주서 (DeliveryList 업로드 대체)."""
    try:
        orders = await sabang_client.fetch_orders(_ymd_compact(from_date), _ymd_compact(to_date))
    except SabangApiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.message)
    if not orders:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"사방넷에서 수집된 주문이 없습니다 ({from_date}~{to_date}, 상태 {config.SABANG_ORDER_STATUSES}).",
        )
    upload = _sabang_delivery_upload(orders)
    return await process_myeongi_order(
        delivery_file=upload,
        toss_from_date=toss_from_date,
        toss_to_date=toss_to_date,
        include_toss="",
        exclude_issued=exclude_issued,
        user=user,
    )


@router.post("/api/process/sabang-kolrabi-order")
async def process_sabang_kolrabi_order(
    from_date: str = Form(...),
    to_date: str = Form(...),
    toss_from_date: str = Form(""),
    toss_to_date: str = Form(""),
    exclude_issued: str = Form("true"),
    user: dict = Depends(verify_token),
):
    """사방넷 주문 자동수집 → 제주다팜 발주서 (DeliveryList 업로드 대체)."""
    try:
        orders = await sabang_client.fetch_orders(_ymd_compact(from_date), _ymd_compact(to_date))
    except SabangApiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.message)
    if not orders:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"사방넷에서 수집된 주문이 없습니다 ({from_date}~{to_date}, 상태 {config.SABANG_ORDER_STATUSES}).",
        )
    upload = _sabang_delivery_upload(orders)
    return await process_kolrabi_order(
        delivery_file=upload,
        toss_from_date=toss_from_date,
        toss_to_date=toss_to_date,
        include_toss="",
        exclude_issued=exclude_issued,
        user=user,
    )


@router.post("/api/process/sabang-fruit-tracking")
async def process_sabang_fruit_tracking(
    orderlist_file: UploadFile = File(...),
    tak_code: str = Form(""),
    _token: dict = Depends(verify_token),
):
    """거래처 회신(orderlist) → 사방넷 송장 자동 등록 (SABANG_INV_REGI).

    orderlist D열 주문번호가 사방넷 IDX여야 한다 — 즉 사방넷 수집으로 만든
    발주서의 회신 파일에만 사용 (쿠팡 DeliveryList 발주분은 대상 아님).
    """
    try:
        ol_bytes = await orderlist_file.read()
        entries = sabang_fruit.parse_orderlist_for_sabang(ol_bytes)
        if not entries:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="orderlist에서 (주문번호 D열, 운송장번호 R열) 쌍을 찾지 못했습니다. 거래처 회신 파일인지 확인해주세요.",
            )
        code = (tak_code or config.SABANG_TAK_CODE).strip()
        if not code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="사방넷 택배사코드가 없습니다. 화면의 택배사코드 칸에 입력하거나 "
                       "fly secrets set SABANG_TAK_CODE=<사방넷 롯데택배 코드> 로 설정해주세요.",
            )
        items = [{"idx": e["idx"], "tak_code": code, "invoice": e["tracking"]} for e in entries]
        result = await sabang_client.send_invoices(items)
        logger.info(f"사방넷 송장전송 완료: {len(items)}건")
        return {"total": len(items), "tak_code": code, **result}
    except SabangApiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.message)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("사방넷 송장전송 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )
