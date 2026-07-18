"""사방넷 오픈API 클라이언트 (주문수집 + 송장전송).

프로토콜 (실제 연동체 2종에서 확인: tojiuni/sabangnet_API, lifelike PHP cron):
- 요청 XML(EUC-KR)을 공개 URL에 올려두고, 사방넷 RTL_API 엔드포인트에
  ?xml_url=<그 URL> 로 GET 호출하면 응답 XML이 돌아온다.
- 헤더: SEND_COMPAYNY_ID(오타 아님, 스펙 그대로) / SEND_AUTH_KEY / SEND_DATE
- 주문수집: {admin}/RTL_API/xml_order_info.html  (SABANG_ORDER_LIST)
- 송장전송: {admin}/RTL_API/xml_order_invoice.html (SABANG_INV_REGI)
"""

import asyncio
import logging
import re
import secrets
import time
import xml.etree.ElementTree as ET

import httpx

from app import config

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 60.0

# 주문수집 시 받아올 필드 (사방넷 ORD_FIELD 스펙 명칭)
ORD_FIELD = (
    "IDX|ORDER_ID|MALL_ID|ORDER_STATUS|ORDER_DATE|MALL_ORDER_ID"
    "|RECEIVE_NAME|RECEIVE_TEL|RECEIVE_CEL|RECEIVE_ZIPCODE|RECEIVE_ADDR|DELV_MSG"
    "|USER_NAME|PRODUCT_NAME|P_PRODUCT_NAME|SKU_VALUE|P_SKU_VALUE"
    "|SALE_CNT|P_EA|COMPAYNY_GOODS_CD|INVOICE_NO|DELIVERY_ID"
)


class SabangApiError(RuntimeError):
    """사방넷 API 오류 — 운영자에게 그대로 보여줄 메시지."""

    def __init__(self, message: str, raw: str = ""):
        super().__init__(message)
        self.message = message
        self.raw = raw


def _require_config() -> None:
    if not config.SABANG_COMPANY_ID or not config.SABANG_AUTH_KEY:
        raise SabangApiError(
            "사방넷 연동키가 설정되지 않았습니다. "
            "사방넷 마이페이지 > 서비스 관리 > 연동키 관리에서 인증키를 발급받고 "
            "fly secrets set SABANG_COMPANY_ID=<로그인ID> SABANG_AUTH_KEY=<인증키> 후 다시 시도해주세요."
        )


# ── 요청 XML 임시 호스팅 (사방넷이 xml_url로 가져감) ──────────────
_XML_TTL_SECONDS = 600
_xml_store: dict[str, tuple[bytes, float]] = {}


def put_request_xml(xml_bytes: bytes) -> str:
    """요청 XML을 저장하고 공개 경로 토큰을 돌려준다."""
    now = time.time()
    for key in [k for k, (_, exp) in _xml_store.items() if exp < now]:
        _xml_store.pop(key, None)
    token = secrets.token_hex(16)
    _xml_store[token] = (xml_bytes, now + _XML_TTL_SECONDS)
    return token


def get_request_xml(token: str) -> bytes | None:
    item = _xml_store.get(token)
    if not item:
        return None
    xml_bytes, expires = item
    if expires < time.time():
        _xml_store.pop(token, None)
        return None
    return xml_bytes


def _xml_public_url(token: str) -> str:
    return f"{config.PUBLIC_BASE_URL}/api/sabang/xml/{token}"


# ── XML 빌드 ──────────────────────────────────────────────────────
def _header_xml(extra: str = "") -> str:
    from datetime import datetime, timedelta, timezone
    today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y%m%d")
    return (
        "<HEADER>\n"
        f"<SEND_COMPAYNY_ID>{config.SABANG_COMPANY_ID}</SEND_COMPAYNY_ID>\n"
        f"<SEND_AUTH_KEY><![CDATA[{config.SABANG_AUTH_KEY}]]></SEND_AUTH_KEY>\n"
        f"<SEND_DATE>{today}</SEND_DATE>\n"
        f"{extra}"
        "</HEADER>\n"
    )


def build_order_list_xml(ord_st_date: str, ord_ed_date: str, order_status: str) -> bytes:
    """주문수집 요청 XML (EUC-KR). 날짜는 YYYYMMDD."""
    body = (
        '<?xml version="1.0" encoding="EUC-KR"?>\n'
        "<SABANG_ORDER_LIST>\n"
        + _header_xml()
        + "<DATA>\n"
        f"<ORD_ST_DATE>{ord_st_date}</ORD_ST_DATE>\n"
        f"<ORD_ED_DATE>{ord_ed_date}</ORD_ED_DATE>\n"
        f"<ORD_FIELD><![CDATA[{ORD_FIELD}]]></ORD_FIELD>\n"
        f"<ORDER_STATUS>{order_status}</ORDER_STATUS>\n"
        "</DATA>\n"
        "</SABANG_ORDER_LIST>"
    )
    return body.encode("euc-kr", errors="replace")


def build_mall_list_xml() -> bytes:
    body = (
        '<?xml version="1.0" encoding="EUC-KR"?>\n'
        "<SABANG_MALL_LIST>\n" + _header_xml() + "</SABANG_MALL_LIST>"
    )
    return body.encode("euc-kr", errors="replace")


def build_invoice_xml(items: list[dict], edit_yn: str = "N") -> bytes:
    """송장전송 요청 XML.

    items: [{"idx": 사방넷주문번호, "tak_code": 택배사코드, "invoice": 송장번호}]
    """
    rows = []
    for it in items:
        rows.append(
            "<DATA>\n"
            f"<SABANGNET_IDX><![CDATA[{it['idx']}]]></SABANGNET_IDX>\n"
            f"<TAK_CODE><![CDATA[{it['tak_code']}]]></TAK_CODE>\n"
            f"<TAK_INVOICE><![CDATA[{it['invoice']}]]></TAK_INVOICE>\n"
            "<DELV_HOPE_DATE></DELV_HOPE_DATE>\n"
            "</DATA>\n"
        )
    body = (
        '<?xml version="1.0" encoding="EUC-KR"?>\n'
        "<SABANG_INV_REGI>\n"
        + _header_xml(f"<SEND_INV_EDIT_YN>{edit_yn}</SEND_INV_EDIT_YN>\n")
        + "".join(rows)
        + "</SABANG_INV_REGI>"
    )
    return body.encode("euc-kr", errors="replace")


# ── 응답 파싱 ─────────────────────────────────────────────────────
def _decode_response(resp: httpx.Response) -> str:
    raw = resp.content
    for enc in ("euc-kr", "cp949", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("euc-kr", errors="replace")


def parse_order_response(xml_text: str) -> list[dict]:
    """SABANG_ORDER_LIST 응답 → 주문 dict 목록(소문자 키)."""
    text = xml_text.strip()
    if not text.startswith("<"):
        raise SabangApiError(f"사방넷 주문수집 응답이 XML이 아닙니다: {text[:300]}", raw=text[:1000])
    try:
        root = ET.fromstring(re.sub(r'encoding="[^"]+"', 'encoding="utf-8"', text, count=1))
    except ET.ParseError as e:
        raise SabangApiError(f"사방넷 응답 XML 파싱 실패: {e} / 응답 앞부분: {text[:300]}", raw=text[:1000])

    orders: list[dict] = []
    for data in root.iter("DATA"):
        order = {}
        for child in data:
            order[child.tag.strip().lower()] = (child.text or "").strip()
        if order:
            orders.append(order)
    return orders


def parse_result_response(xml_text: str) -> dict:
    """송장전송 등 결과성 응답을 관대하게 파싱."""
    text = xml_text.strip()
    result = {"raw": text[:1000]}
    if not text.startswith("<"):
        return result
    try:
        root = ET.fromstring(re.sub(r'encoding="[^"]+"', 'encoding="utf-8"', text, count=1))
    except ET.ParseError:
        return result
    items = []
    for data in root.iter("DATA"):
        items.append({c.tag.strip().lower(): (c.text or "").strip() for c in data})
    if items:
        result["items"] = items
    for tag in ("RESULT", "CODE", "MSG", "MESSAGE", "ERROR"):
        node = root.find(tag)
        if node is not None and (node.text or "").strip():
            result[tag.lower()] = node.text.strip()
    return result


# ── API 호출 ──────────────────────────────────────────────────────
async def _call_api(endpoint: str, xml_bytes: bytes) -> str:
    _require_config()
    token = put_request_xml(xml_bytes)
    xml_url = _xml_public_url(token)
    api_url = f"{config.SABANG_ADMIN_URL}/RTL_API/{endpoint}?xml_url={xml_url}"
    logger.info("사방넷 API 호출: %s (xml token=%s…)", endpoint, token[:8])
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        try:
            resp = await client.get(api_url)
        except httpx.RequestError as e:
            raise SabangApiError(f"사방넷 API 연결 실패: {e}")
    if resp.status_code >= 400:
        raise SabangApiError(
            f"사방넷 API HTTP {resp.status_code} 오류", raw=_decode_response(resp)[:500]
        )
    return _decode_response(resp)


def _looks_like_auth_error(text: str) -> bool:
    return bool(re.search(r"인증|AUTH|권한|허용|IP", text[:500], re.IGNORECASE)) and "<DATA>" not in text


async def fetch_orders(
    from_ymd: str,
    to_ymd: str,
    statuses: list[str] | None = None,
) -> list[dict]:
    """기간(YYYYMMDD)·상태별 주문수집. 상태 여러 개면 순차 호출 후 IDX 기준 중복 제거."""
    statuses = statuses or [s.strip() for s in config.SABANG_ORDER_STATUSES.split(",") if s.strip()]
    seen: set[str] = set()
    merged: list[dict] = []
    for st in statuses:
        text = await _call_api("xml_order_info.html", build_order_list_xml(from_ymd, to_ymd, st))
        try:
            orders = parse_order_response(text)
        except SabangApiError:
            if _looks_like_auth_error(text):
                raise SabangApiError(
                    f"사방넷 인증/권한 오류로 보입니다: {text[:300]}", raw=text[:1000]
                )
            raise
        for o in orders:
            idx = o.get("idx") or ""
            if idx and idx in seen:
                continue
            if idx:
                seen.add(idx)
            o["_order_status_query"] = st
            merged.append(o)
        await asyncio.sleep(0.3)
    logger.info("사방넷 주문수집: %s~%s 상태%s → %d건", from_ymd, to_ymd, statuses, len(merged))
    return merged


async def send_invoices(items: list[dict], edit_yn: str = "N") -> dict:
    """송장전송. items: [{idx, tak_code, invoice}]"""
    if not items:
        return {"sent": 0, "result": {}}
    text = await _call_api("xml_order_invoice.html", build_invoice_xml(items, edit_yn))
    result = parse_result_response(text)
    logger.info("사방넷 송장전송 %d건 응답: %s", len(items), text[:300])
    return {"sent": len(items), "result": result}


async def test_connection() -> dict:
    """쇼핑몰 목록 조회로 연동키 유효성 확인."""
    text = await _call_api("xml_mall_info.html", build_mall_list_xml())
    try:
        malls = parse_order_response(text)
    except SabangApiError as e:
        return {"status": "error", "message": e.message}
    return {"status": "ok", "mall_count": len(malls), "message": f"쇼핑몰 {len(malls)}곳 연동 확인"}
