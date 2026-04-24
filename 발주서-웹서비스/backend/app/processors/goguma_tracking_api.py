"""Register goguma tracking numbers to Coupang via API."""

from __future__ import annotations

import asyncio
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from io import BytesIO

from openpyxl import load_workbook

from app.coupang.client import coupang_client

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))

GOGUMA_KEYWORDS = ["고구마", "꿀고구마"]
DELIVERY_COMPANY_CODE = "HANJIN"


def normalize(value: object) -> str:
    """Remove all whitespace for matching."""
    if value is None:
        return ""
    return re.sub(r"\s+", "", str(value).strip())


def phone_digits(value: object) -> str:
    """전화번호에서 숫자만 추출 (하이픈/공백 형식 차이 무시)"""
    if value is None:
        return ""
    return re.sub(r"\D", "", str(value))


def find_tracking_in_row(ws, row_idx: int) -> str:
    """Find a 10-14 digit tracking number in columns P~V."""
    for col in range(16, 23):  # P ~ V
        val = ws.cell(row=row_idx, column=col).value
        if val is None:
            continue
        s = str(val).strip()
        if re.match(r"^\d{10,14}$", s):
            return s
    return ""


def parse_haedal_file(haedal_bytes: bytes) -> list[dict]:
    """Parse shipping workbook and extract rows with tracking numbers."""
    wb = load_workbook(filename=BytesIO(haedal_bytes), data_only=True)
    ws = wb.active

    start_row = 1
    a1_val = normalize(ws.cell(row=1, column=1).value)
    if "받" in a1_val or "수령" in a1_val:
        start_row = 2

    entries = []
    for row_idx in range(start_row, ws.max_row + 1):
        name = normalize(ws.cell(row=row_idx, column=1).value)     # A
        phone = phone_digits(ws.cell(row=row_idx, column=2).value)    # B
        address = normalize(ws.cell(row=row_idx, column=6).value)  # F
        if not name:
            continue

        tracking = find_tracking_in_row(ws, row_idx)
        if tracking:
            entries.append(
                {
                    "name": name,
                    "phone": phone,
                    "address": address,
                    "tracking": tracking,
                }
            )

    return entries


def is_goguma_order(item: dict) -> bool:
    """Check if an order item is a goguma product."""
    seller_name = (item.get("sellerProductName") or "").lower()
    vendor_name = (item.get("vendorItemName") or "").lower()
    return any(keyword in seller_name or keyword in vendor_name for keyword in GOGUMA_KEYWORDS)


async def _fetch_orders_by_status(order_status: str, from_date: str, to_date: str) -> list[dict]:
    rows: list[dict] = []
    next_token = None

    while True:
        result = await coupang_client.get_order_sheets(
            created_at_from=from_date,
            created_at_to=to_date,
            order_status=order_status,
            max_per_page=50,
            next_token=next_token,
        )
        if not result:
            break

        shipments = result.get("data", [])
        if not shipments:
            break

        for shipment in shipments:
            receiver = shipment.get("receiver") or {}
            shipment_box_id = shipment.get("shipmentBoxId")
            order_id = shipment.get("orderId")

            for item in shipment.get("orderItems", []):
                if not is_goguma_order(item) or not shipment_box_id:
                    continue

                phone_raw = (
                    receiver.get("safeNumber")
                    or receiver.get("receiverPhoneNumber1")
                    or ""
                )
                address_raw = f"{receiver.get('addr1') or ''} {receiver.get('addr2') or ''}".strip()

                rows.append(
                    {
                        "shipment_box_id": shipment_box_id,
                        "order_id": order_id,
                        "vendor_item_id": item.get("vendorItemId"),
                        "name": normalize(receiver.get("name") or ""),
                        "phone": phone_digits(phone_raw),
                        "address": normalize(address_raw),
                        "name_display": receiver.get("name") or "",
                        "order_status": order_status,
                    }
                )

        next_token = result.get("nextToken")
        if not next_token:
            break

    return rows


async def fetch_pending_orders() -> list[dict]:
    """Fetch ACCEPT + INSTRUCT goguma orders from Coupang.

    ACCEPT orders are acknowledged first, then refetched as INSTRUCT when
    possible so invoice registration is less likely to be blocked by status.
    """
    now = datetime.now(KST)
    from_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    to_date = now.strftime("%Y-%m-%d")

    instruct_orders = await _fetch_orders_by_status("INSTRUCT", from_date, to_date)
    accept_orders = await _fetch_orders_by_status("ACCEPT", from_date, to_date)
    accept_shipment_box_ids = list({row["shipment_box_id"] for row in accept_orders})

    if accept_shipment_box_ids:
        logger.info("결제완료 주문 %s건 자동 확인 처리 시작", len(accept_shipment_box_ids))
        try:
            confirm_result = await coupang_client.confirm_orders(accept_shipment_box_ids)
            code = (confirm_result or {}).get("code")
            if code in (200, "200", 0):
                logger.info("쿠팡 주문 확인 성공: %s건", len(accept_shipment_box_ids))
            else:
                logger.warning("쿠팡 주문 확인 응답 이상: %s", confirm_result)
        except Exception as exc:
            logger.error("쿠팡 주문 확인 실패 (송장 등록은 계속 시도): %s", exc)
        await asyncio.sleep(3)

    refreshed_instruct = await _fetch_orders_by_status("INSTRUCT", from_date, to_date)
    refreshed_accept_map = {
        (row["shipment_box_id"], row["vendor_item_id"]): row
        for row in refreshed_instruct
        if row["shipment_box_id"] in accept_shipment_box_ids
    }

    combined: dict[tuple[int, int], dict] = {}
    for row in instruct_orders + refreshed_instruct:
        combined[(row["shipment_box_id"], row["vendor_item_id"])] = row
    for row in accept_orders:
        key = (row["shipment_box_id"], row["vendor_item_id"])
        combined[key] = refreshed_accept_map.get(key, row)

    all_orders = list(combined.values())
    logger.info(
        "고구마 주문 조회 완료: total=%s, instruct=%s, accept=%s, refreshed=%s",
        len(all_orders),
        len(instruct_orders),
        len(accept_orders),
        len(refreshed_accept_map),
    )
    return all_orders


async def process_tracking_api(haedal_bytes: bytes) -> dict:
    """Parse tracking file, match Coupang orders, and register invoices."""
    haedal_entries = parse_haedal_file(haedal_bytes)
    if not haedal_entries:
        raise ValueError("해달 발주서에서 운송장번호를 찾을 수 없습니다.")

    coupang_orders = await fetch_pending_orders()
    if not coupang_orders:
        raise ValueError("결제완료 또는 상품준비중인 고구마 주문이 없습니다.")

    entry_by_name = defaultdict(list)
    entry_by_phone = defaultdict(list)
    for entry in haedal_entries:
        entry_by_name[entry["name"]].append(entry)
        if entry["phone"]:
            entry_by_phone[entry["phone"]].append(entry)

    used_entries = set()
    matched_pairs = []
    matched_via_phone: dict[int, str] = {}  # id(order) -> 해달측 이름 (fallback 표시용)
    results = []
    skip_count = 0

    for order in coupang_orders:
        candidates = entry_by_name.get(order["name"], [])
        available = [c for c in candidates if id(c) not in used_entries]

        matched = None
        matched_via_phone_only = False

        if available:
            for candidate in available:
                if candidate["phone"] == order["phone"] and candidate["address"] == order["address"]:
                    matched = candidate
                    break
            if matched is None:
                for candidate in available:
                    if candidate["phone"] == order["phone"]:
                        matched = candidate
                        break
            if matched is None:
                for candidate in available:
                    if candidate["address"] == order["address"]:
                        matched = candidate
                        break
            if matched is None:
                matched = available[0]

        # Fallback: 이름 매칭 실패 시 전화번호로 재시도
        # (CS로 수취인/주소가 바뀐 케이스 대응 — 전화번호는 보통 유지됨)
        if matched is None and order["phone"]:
            phone_pool = [
                c for c in entry_by_phone.get(order["phone"], [])
                if id(c) not in used_entries
            ]
            if len(phone_pool) == 1:
                matched = phone_pool[0]
                matched_via_phone_only = True
            elif len(phone_pool) > 1:
                for c in phone_pool:
                    if c["address"] == order["address"]:
                        matched = c
                        matched_via_phone_only = True
                        break

        if matched is None:
            skip_count += 1
            results.append(
                {
                    "order_id": str(order["order_id"]),
                    "name": order["name_display"],
                    "status": "skip",
                    "message": "매칭되는 수령인 없음 (이름·전화번호 모두 불일치)",
                }
            )
            continue

        used_entries.add(id(matched))
        matched_pairs.append((order, matched["tracking"]))
        if matched_via_phone_only:
            matched_via_phone[id(order)] = matched["name"]

    success_count = 0
    fail_count = 0

    def _build_dtos(pairs: list[tuple[dict, str]]) -> list[dict]:
        return [
            {
                "shipmentBoxId": order["shipment_box_id"],
                "orderId": order["order_id"],
                "vendorItemId": order["vendor_item_id"],
                "deliveryCompanyCode": DELIVERY_COMPANY_CODE,
                "invoiceNumber": tracking,
            }
            for order, tracking in pairs
        ]

    def _is_accept_related_error(msg: str, code) -> bool:
        if code in ("ORDER_NOT_ACCEPTED", "INVALID_STATUS"):
            return True
        lowered = str(msg or "").lower()
        return (
            "상품준비중" in str(msg)
            or "결제완료" in str(msg)
            or "status" in lowered
            or "state" in lowered
            or "accept" in lowered
        )

    async def _upload_and_parse(pairs: list[tuple[dict, str]]):
        dtos = _build_dtos(pairs)
        try:
            api_result = await coupang_client.upload_invoices(dtos)
            logger.info("쿠팡 송장업로드 API 응답: %s", api_result)
        except Exception as exc:
            logger.error("쿠팡 송장업로드 API 오류: %s", exc)
            return [], [(order, tracking, str(exc), None) for order, tracking in pairs]

        response_data = (api_result or {}).get("data", {})
        response_list = response_data.get("responseList", [])
        response_map = {item.get("shipmentBoxId"): item for item in response_list}

        if not response_list and api_result:
            code = api_result.get("code") or response_data.get("responseCode")
            if code in (200, 0, "200"):
                return list(pairs), []

        success_pairs = []
        fail_pairs = []
        for order, tracking in pairs:
            resp_item = response_map.get(order["shipment_box_id"], {})
            if resp_item.get("succeed"):
                success_pairs.append((order, tracking))
            else:
                message = resp_item.get("resultMessage") or resp_item.get("resultCode", "알 수 없는 오류")
                fail_pairs.append((order, tracking, str(message), resp_item.get("resultCode")))
        return success_pairs, fail_pairs

    if matched_pairs:
        success_pairs, fail_items = await _upload_and_parse(matched_pairs)

        retry_pairs = [(order, tracking) for order, tracking, msg, code in fail_items if _is_accept_related_error(msg, code)]
        retry_boxes = list({order["shipment_box_id"] for order, _ in retry_pairs})
        if retry_pairs:
            logger.info("상태 전이 의심 %s건 재시도 시작", len(retry_pairs))
            try:
                confirm_result = await coupang_client.confirm_orders(retry_boxes)
                logger.info("재시도용 주문 확인 응답: %s", confirm_result)
            except Exception as exc:
                logger.error("재시도용 주문 확인 실패: %s", exc)
            await asyncio.sleep(3)

            retry_success, retry_fail = await _upload_and_parse(retry_pairs)
            success_pairs.extend(retry_success)
            fail_items = [
                item for item in fail_items if not _is_accept_related_error(item[2], item[3])
            ] + retry_fail

        for order, tracking in success_pairs:
            success_count += 1
            haedal_name = matched_via_phone.get(id(order))
            if haedal_name:
                message = f"운송장 등록 완료 (전화번호 매칭: 해달 '{haedal_name}' → 쿠팡 '{order['name_display']}')"
            else:
                message = "운송장 등록 완료"
            results.append(
                {
                    "order_id": str(order["order_id"]),
                    "name": order["name_display"],
                    "tracking": tracking,
                    "status": "success",
                    "message": message,
                }
            )
        for order, tracking, message, _ in fail_items:
            fail_count += 1
            results.append(
                {
                    "order_id": str(order["order_id"]),
                    "name": order["name_display"],
                    "tracking": tracking,
                    "status": "fail",
                    "message": message,
                }
            )

    return {
        "haedal_entries": len(haedal_entries),
        "coupang_orders": len(coupang_orders),
        "success": success_count,
        "fail": fail_count,
        "skip": skip_count,
        "results": results,
    }
