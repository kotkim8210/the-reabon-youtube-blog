"""쿠팡 CS(상품 변질/부분환불) → 거래처 카카오톡 통보 템플릿 생성기.

동작:
1) 수취인 성함으로 AdminPlus(pbfcompany) 주문리스트를 조회한다.
   로그인은 supplier_price_monitor 와 동일하게 PBF_PARTNER_ID/PASSWORD 로 /partner/login.chk.php POST.
2) 주문리스트 표는 화면상 jqGrid 라 HTML에 행이 없고, 그리드가 아래 JSON 엔드포인트를 호출한다:
       /partner/order/json/od.list.bd.php?proc=json&<검색폼 serialize>
   (order.list.bd.js line 508 확인). 그 JSON을 colModel 순서대로 파싱한다.
3) 동명이인/다건이면 후보를 돌려주고, 단건이면 아래 템플릿 문자열을 만든다.

거래처 카톡 템플릿(예시와 동일한 서식/띄어쓰기):
    발주일자/수령일자 : 7.19/7.21
    고객 주문번호 : 26071920071310880010
    수취인 성함 : 심현순
    발주 상품명: 거반도 1kg (4~10과 내외)
    송장번호: 262021776730
    원하시는 환불비중 : 4개중 1개 변질되어 부분환불 문의
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

import httpx

from app.config import PBF_PARTNER_ID, PBF_PARTNER_PASSWORD

KST = timezone(timedelta(hours=9))
ADMINPLUS_BASE = "https://pbfcompany.adminplus.co.kr"

# order.list.bd.js: var deleverycmp = "0:=선택=;2:CJ대한통운;4:로젠택배;7:롯데택배;5:한진택배"
COURIER_CODES: dict[str, str] = {
    "0": "",
    "2": "CJ대한통운",
    "4": "로젠택배",
    "5": "한진택배",
    "7": "롯데택배",
}

# jqGrid colModel 순서 (order.list.bd.js line 515-539). cell-배열 JSON일 때 인덱스 매핑용.
_CELL_FIELDS: list[str] = [
    "merge", "no", "regdate", "ordcode", "orditem", "dlvcmp", "dlvcode",
    "ordname", "buyhp", "revname", "revhp", "revaddress", "dlvamount",
    "totalamount", "statesprt", "management", "bidx", "pcode", "opidx",
    "stroption", "intstatesprt", "intordcode", "odstatusint",
]


class CsRefundError(RuntimeError):
    """CS 템플릿 생성 중 발생한 사용자 노출용 오류."""


@dataclass
class OrderRow:
    order_code: str = ""       # 주문번호 (거래처 통보용, 쿠팡 주문번호 아님)
    order_datetime: str = ""   # 주문일시 (발주일자 산출용)
    product: str = ""          # 주문상품(발주 상품명)
    courier: str = ""          # 택배사
    tracking: str = ""         # 운송장번호(송장번호)
    orderer: str = ""          # 주문자
    recipient: str = ""        # 받는분(수취인)
    recipient_phone: str = ""  # 받는분연락처
    address: str = ""          # 주소
    status: str = ""           # 주문상태(배송중/배송완료/취소/반품 등)


def _clean(value: object) -> str:
    """HTML/엔티티 제거 후 공백 1칸으로 정규화."""
    text = "" if value is None else str(value)
    text = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&#039;", "'")
        .replace("&quot;", '"')
    )
    return re.sub(r"\s+", " ", text).strip()


def _longest_digits(text: object, min_len: int = 6) -> str:
    runs = [r for r in re.findall(r"\d+", str(text or "")) if len(r) >= min_len]
    return max(runs, key=len) if runs else ""


def _clean_product(value: object) -> str:
    """주문상품 셀 → 상품명만. 이미지/노이즈 및 끝의 수량('1개') 제거."""
    text = _clean(value)
    text = re.sub(r"(?i)no\s*image", " ", text)
    text = re.sub(r"\s*\d+\s*개\s*$", "", text)  # 끝의 수량 제거
    return re.sub(r"\s+", " ", text).strip()


def _courier_name(value: object) -> str:
    """dlvcmp 값(코드 '7' 또는 이미 '롯데택배')을 택배사명으로."""
    raw = _clean(value)
    if re.fullmatch(r"\d+", raw):
        return COURIER_CODES.get(raw, "")
    return raw


def _row_get(row: object, field: str) -> object:
    """jqGrid row에서 필드 값 추출 (cell-배열 / 이름-딕셔너리 양쪽 지원)."""
    if isinstance(row, dict):
        cell = row.get("cell")
        if isinstance(cell, list):
            idx = _CELL_FIELDS.index(field) if field in _CELL_FIELDS else -1
            return cell[idx] if 0 <= idx < len(cell) else ""
        return row.get(field, "")
    if isinstance(row, list):
        idx = _CELL_FIELDS.index(field) if field in _CELL_FIELDS else -1
        return row[idx] if 0 <= idx < len(row) else ""
    return ""


def parse_order_json(payload: object) -> list[OrderRow]:
    """od.list.bd.php JSON → OrderRow 목록."""
    if isinstance(payload, (bytes, str)):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError) as exc:
            raise CsRefundError(
                "주문 데이터를 JSON으로 읽지 못했습니다 (로그인/세션 만료 가능)."
            ) from exc

    if isinstance(payload, dict):
        rows = payload.get("rows", [])
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []

    orders: list[OrderRow] = []
    for row in rows:
        order_code = _longest_digits(_clean(_row_get(row, "ordcode")), min_len=10)
        if not order_code:
            continue  # 합계/빈 행 등 방어
        orders.append(
            OrderRow(
                order_code=order_code,
                order_datetime=_clean(_row_get(row, "regdate")),
                product=_clean_product(_row_get(row, "orditem")),
                courier=_courier_name(_row_get(row, "dlvcmp")),
                tracking=_longest_digits(_clean(_row_get(row, "dlvcode")), min_len=8),
                orderer=_clean(_row_get(row, "ordname")),
                recipient=_clean(_row_get(row, "revname")),
                recipient_phone=re.sub(r"[^\d\-]", "", _clean(_row_get(row, "revhp"))),
                address=_clean(_row_get(row, "revaddress")),
                status=_clean(_row_get(row, "statesprt")),
            )
        )
    return orders


async def _login(client: httpx.AsyncClient) -> None:
    if not PBF_PARTNER_ID or not PBF_PARTNER_PASSWORD:
        raise CsRefundError("PBF_PARTNER_ID/PBF_PARTNER_PASSWORD가 설정되지 않았습니다 (fly secrets 확인).")
    response = await client.post(
        f"{ADMINPLUS_BASE}/partner/login.chk.php",
        data={"admid": PBF_PARTNER_ID, "admpwd": PBF_PARTNER_PASSWORD},
    )
    response.raise_for_status()
    if response.text.strip().lower() != "ok":
        raise CsRefundError("AdminPlus 로그인에 실패했습니다.")


async def fetch_orders(recipient: str, date_start: str, date_end: str) -> list[OrderRow]:
    """수취인 성함으로 주문리스트(jqGrid JSON)를 조회해 OrderRow 목록을 돌려준다.

    date_start/date_end: 'YYYY-MM-DD' (주문일자 기준 검색 범위).
    """
    sdate = json.dumps({"start": date_start, "end": date_end}, ensure_ascii=False)
    params = {
        "proc": "json",
        "mod": "order",
        "actpage": "od.list.bd",
        "status": "all",
        "orderexcelidx": "",
        "odbidx": "",
        "datefld": "a.regdate",
        "sdate": sdate,
        "searchtype": "all",
        "searchval": recipient,
        "page": "1",
        "rows": "100",
        "sidx": "regdate",
        "sord": "desc",
    }
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        await _login(client)
        response = await client.get(
            f"{ADMINPLUS_BASE}/partner/order/json/od.list.bd.php",
            params=params,
        )
        response.raise_for_status()
        return parse_order_json(response.text)


def _fmt_md(datetime_text: str) -> str:
    """'2026-07-19 20:04:59' 또는 '2026.07.19' → '7.19' (앞자리 0 제거)."""
    match = re.search(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", datetime_text or "")
    if match:
        return f"{int(match.group(2))}.{int(match.group(3))}"
    return (datetime_text or "").strip()


def today_md() -> str:
    now = datetime.now(KST)
    return f"{now.month}.{now.day}"


def candidate_dict(order: OrderRow) -> dict:
    return asdict(order)


def build_refund_template(order: OrderRow, note: str, received_date: str) -> str:
    """거래처 카카오톡 통보용 템플릿 문자열 생성 (예시와 동일한 서식/띄어쓰기)."""
    order_md = _fmt_md(order.order_datetime)
    lines = [
        f"발주일자/수령일자 : {order_md}/{received_date}",
        f"고객 주문번호 : {order.order_code}",
        f"수취인 성함 : {order.recipient}",
        f"발주 상품명: {order.product}",
        f"송장번호: {order.tracking}",
        f"원하시는 환불비중 : {note}".rstrip(),
    ]
    return "\n".join(lines)
