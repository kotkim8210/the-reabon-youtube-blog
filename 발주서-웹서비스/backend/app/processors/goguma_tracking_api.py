"""Register goguma tracking numbers to Coupang via API."""

from __future__ import annotations

import asyncio
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from io import BytesIO

from openpyxl import load_workbook

from app.coupang.client import coupang_goguma_client
from app.processors.goguma_order import transform_option
from app.processors.haedal_tracking_parser import (
    detect_haedal_columns,
    find_courier_in_row,
    find_tracking_in_row,
)
from app.processors.tracking_match import (
    name_counts,
    option_key_set,
    option_rank,
    options_match,
    requires_option_guard,
)

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))

GOGUMA_KEYWORDS = ["고구마", "꿀고구마"]
DELIVERY_COMPANY_CODE = "HANJIN"  # 기본(해달은 보통 한진). 파일에 택배사가 명시되면 그걸 우선.

# 송장이 이미 들어간 주문 상태(배송지시·배송중·배송완료). 짝짓기 대상이 아니고, 그 송장번호·안심번호로
# 같은 회신 파일 재실행 시 새 주문에 옛 송장이 들어가는 것을 막는다(2026-11-16 리뷰).
SHIPPED_STATUSES = ("DEPARTURE", "DELIVERING", "FINAL_DELIVERY")
_STATUS_LABELS = {
    "ACCEPT": "결제완료",
    "INSTRUCT": "상품준비중",
    "DEPARTURE": "배송지시",
    "DELIVERING": "배송중",
    "FINAL_DELIVERY": "배송완료",
}

# 택배사명 → 쿠팡 deliveryCompanyCode. 미인식 시 기본(한진).
_COURIER_NAME_TO_CODE: list[tuple[tuple[str, ...], str]] = [
    (("대한통운", "cj"), "CJGLS"),
    (("한진",), "HANJIN"),
    (("롯데", "현대"), "HYUNDAI"),   # 롯데택배 = 쿠팡 코드 HYUNDAI(구 현대택배)
    (("우체국", "epost"), "EPOST"),
    (("로젠", "logen"), "KGB"),
]


def courier_code(name: object, default: str = DELIVERY_COMPANY_CODE) -> str:
    """택배사명 문자열 → 쿠팡 deliveryCompanyCode. 못 알아보면 기본값."""
    compact = re.sub(r"\s+", "", str(name or "")).lower()
    if not compact:
        return default
    for keys, code in _COURIER_NAME_TO_CODE:
        if any(k in compact for k in keys):
            return code
    return default


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


def _invoice_key(value: object) -> str:
    """송장번호 비교용 — 공백·하이픈 차이 무시."""
    if value is None:
        return ""
    return re.sub(r"[\s\-]", "", str(value))


def parse_haedal_file(haedal_bytes: bytes) -> list[dict]:
    """Parse shipping workbook and extract rows with tracking numbers."""
    wb = load_workbook(filename=BytesIO(haedal_bytes), data_only=True)
    ws = wb.active
    cols = detect_haedal_columns(ws)

    entries = []
    for row_idx in range(cols.start_row, ws.max_row + 1):
        name = normalize(ws.cell(row=row_idx, column=cols.name).value)
        phone = phone_digits(ws.cell(row=row_idx, column=cols.phone).value)
        address = normalize(ws.cell(row=row_idx, column=cols.address).value)
        product = ws.cell(row=row_idx, column=cols.product).value
        if not name:
            continue

        tracking = find_tracking_in_row(ws, row_idx, cols.tracking, cols.tracking_alt)
        if tracking:
            skip_cols = tuple(
                c for c in (cols.name, cols.phone, cols.address, cols.product, cols.tracking) if c
            )
            courier_name = find_courier_in_row(ws, row_idx, cols.courier, skip_cols)
            entries.append(
                {
                    "name": name,
                    "phone": phone,
                    "address": address,
                    "tracking": tracking,
                    "delivery_company_code": courier_code(courier_name),
                    "option_keys": option_key_set(product, transform_option(str(product or ""))),
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
        result = await coupang_goguma_client.get_order_sheets(
            created_at_from=from_date,
            created_at_to=to_date,
            order_status=order_status,
            max_per_page=50,
            next_token=next_token,
        )
        status_label = _STATUS_LABELS.get(order_status, order_status)
        if not isinstance(result, dict):
            # 재시도를 다 써도 응답이 없으면(None) 빈 목록으로 보면 안 된다 — 주문이 없는 줄 알고 넘어가거나
            # 송장 중복 확인이 빠진다. 아무것도 확인·등록하지 않고 멈춘다.
            raise RuntimeError(
                f"쿠팡 주문 조회 실패({status_label}) — 응답 없음. 송장을 하나도 등록하지 않았습니다. 잠시 후 다시 실행하세요."
            )
        code = result.get("code")
        if code is not None and str(code).upper() not in ("200", "0", "OK", "SUCCESS"):
            raise RuntimeError(
                f"쿠팡 주문 조회 실패({status_label}) — {result.get('message') or code}. 송장을 하나도 등록하지 않았습니다."
            )

        shipments = result.get("data") or []
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
                        # 이미 들어간 송장(배송지시·배송중·배송완료) — 같은 회신 재실행 방지용
                        "invoice_number": _invoice_key(shipment.get("invoiceNumber")),
                        # 한 묶음 송장 여러 개면 더 비싼 옵션 송장을 쓴다(salesPrice=옵션 판매가, orderPrice=결제액)
                        "price": item.get("salesPrice"),
                        "order_price": item.get("orderPrice"),
                        "item_name": item.get("vendorItemName") or "",
                        "option_keys": option_key_set(
                            item.get("vendorItemName"),
                            transform_option(item.get("vendorItemName") or ""),
                        )
                        or option_key_set(item.get("sellerProductName")),
                    }
                )

        next_token = result.get("nextToken")
        if not next_token:
            break

    return rows


async def fetch_pending_orders() -> list[dict]:
    """Fetch ACCEPT + INSTRUCT goguma orders from Coupang (조회만, 상태 변경 없음).

    결제완료(ACCEPT) 주문의 확인 처리(→상품준비중)는 여기서 하지 않는다 —
    해달 운송장과 실제로 매칭된 주문만 process_tracking_api에서 확인 처리한다.
    (매칭 안 된 결제완료 주문까지 넘어가면 고객 즉시취소가 막히는 부작용)

    송장이 이미 들어간 최근 주문(배송지시·배송중·배송완료, SHIPPED_STATUSES)도 함께 돌려준다 —
    order_status로 구분되고 짝짓기에는 쓰지 않는다. 그 송장번호(invoice_number)로 같은 회신 파일을
    다시 올렸을 때 같은 사람의 새 주문에 옛 송장이 들어가는 것을 막는다(2026-11-16 리뷰).
    조회가 하나라도 실패하면(응답 없음·예외) 빈 목록으로 보지 않고 예외로 멈춘다.
    """
    now = datetime.now(KST)
    from_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    to_date = now.strftime("%Y-%m-%d")

    instruct_orders = await _fetch_orders_by_status("INSTRUCT", from_date, to_date)
    accept_orders = await _fetch_orders_by_status("ACCEPT", from_date, to_date)
    shipped_orders: list[dict] = []
    for shipped_status in SHIPPED_STATUSES:
        shipped_orders.extend(await _fetch_orders_by_status(shipped_status, from_date, to_date))

    combined: dict[tuple[int, int], dict] = {}
    # 조회 사이에 송장이 들어가 두 번 잡힌 묶음은 출고 상태 쪽을 쓴다(짝짓기 대상에서 빠짐)
    for row in instruct_orders + accept_orders + shipped_orders:
        combined[(row["shipment_box_id"], row["vendor_item_id"])] = row

    all_orders = list(combined.values())
    logger.info(
        "고구마 주문 조회 완료: total=%s, instruct=%s, accept=%s, 송장확인용 출고=%s",
        len(all_orders),
        len(instruct_orders),
        len(accept_orders),
        len(shipped_orders),
    )
    return all_orders


def _registered_invoices(orders: list[dict]) -> dict[str, set]:
    """쿠팡에 이미 들어간 송장번호 → 그 송장이 들어간 묶음(shipmentBoxId)들."""
    registered: dict[str, set] = defaultdict(set)
    for order in orders:
        key = _invoice_key(order.get("invoice_number"))
        if key:
            registered[key].add(order.get("shipment_box_id"))
    return registered


def _phone_eq(order: dict, entry: dict) -> bool:
    return bool(entry["phone"]) and entry["phone"] == order["phone"]


def _phone_conflict(order: dict, entry: dict) -> bool:
    """양쪽 다 전화가 있는데 숫자가 다르다 — 쿠팡 전화는 주문별 안심번호라 다른 주문일 가능성이 크다."""
    return bool(entry["phone"]) and bool(order["phone"]) and entry["phone"] != order["phone"]


def _address_eq(order: dict, entry: dict) -> bool:
    return bool(entry["address"]) and entry["address"] == order["address"]


def _option_eq(order: dict, entry: dict) -> bool:
    return options_match(entry.get("option_keys"), order.get("option_keys"))


def _assign_tier(
    orders: list[dict],
    candidates: dict[int, list[dict]],
    matched: dict[int, dict],
    used: set[int],
    allowed,
) -> None:
    """한 단계 조건(allowed)으로 최대한 많이 1:1로 짝짓는다(증가 경로). 앞 주문이 여러 송장에 맞으면
    뒤 주문에만 맞는 송장을 양보해, 먼저 조회된 주문이 같은 사람의 다른 주문 송장을 가로채지 않는다."""
    owner: dict[int, tuple[dict, dict]] = {}  # id(회신 줄) → (쿠팡 주문, 회신 줄)

    def assign(order: dict, seen: set[int]) -> bool:
        options = [entry for entry in candidates[id(order)] if id(entry) not in used and allowed(order, entry)]
        for entry in options:  # 빈 송장부터 회신 순서대로
            if id(entry) not in owner:
                owner[id(entry)] = (order, entry)
                return True
        for entry in options:  # 빈 게 없을 때만 앞 주문을 다른 송장으로 옮길 수 있는지 본다
            key = id(entry)
            if key in seen:
                continue
            seen.add(key)
            if assign(owner[key][0], seen):
                owner[key] = (order, entry)
                return True
        return False

    for order in orders:
        if id(order) not in matched:
            assign(order, set())
    for key, (order, entry) in owner.items():
        matched[id(order)] = entry
        used.add(key)


def _match_orders(
    coupang_orders: list[dict],
    haedal_entries: list[dict],
    registered: dict[str, set],
    shipped_phones: set[str] | frozenset = frozenset(),
) -> tuple[dict[int, dict], dict[int, tuple[str, str | None]]]:
    """쿠팡 주문(결제완료·상품준비중) ↔ 해달 회신 줄을 1:1로 짝짓는다.

    이름만 같다고 짝지으면 남의 주문에 송장이 들어간다(2026-11-16 리뷰 — 토스 고객 김민지 송장이
    다른 쿠팡 김민지 결제완료 주문에 확인 처리·등록돼 '배송중'이 되고 실제로는 출고가 안 됐다). 그래서
      - 이름 + (전화 일치 또는 옵션 일치)여야 짝짓는다. 쿠팡 전화는 주문별 안심번호이고 해달 회신 전화는
        우리가 보낸 발주서에서 온 것이라 같으면 같은 주문이다.
      - 결제완료(ACCEPT)는 짝지으면 확인 처리(고객 즉시취소 불가)되므로 전화가 맞을 때만 짝짓는다.
      - 전화가 양쪽 다 있는데 다르면 옵션·주소가 같아도 짝짓지 않는다 — 같은 사람의 다른 주문이나 토스 주문 송장이다.
      - 회신 전화가 다른 쿠팡 주문의 안심번호면 그 주문 몫이다. 이미 출고된 주문(shipped_phones)도 같다 —
        묶음·분할 회신을 다시 올리면 쿠팡에 안 올라간 나머지 송장(같은 주문 다른 박스)이 새 주문에 들어간다.
      - 이미 다른 주문(묶음)에 들어간 송장은 쓰지 않는다(같은 회신 파일 재실행 방지).
      - 강한 신호부터 단계별로 전체 주문을 짝지어, 같은 사람 여러 주문이 전화/옵션으로 1:1이 되게 한다.
    반환: ({id(주문): 회신 줄}, {id(못 짝지은 주문): (skip 사유, 표시할 송장)})
    """
    entry_by_name: dict[str, list[dict]] = defaultdict(list)
    entry_by_phone: dict[str, list[dict]] = defaultdict(list)
    for entry in haedal_entries:
        entry_by_name[entry["name"]].append(entry)
        if entry["phone"]:
            entry_by_phone[entry["phone"]].append(entry)

    coupang_name_counts = name_counts(order["name"] for order in coupang_orders)
    pending_phones = {order["phone"] for order in coupang_orders if order["phone"]}
    shipped_only_phones = set(shipped_phones) - pending_phones
    other_order_phones = pending_phones | shipped_only_phones

    candidates: dict[int, list[dict]] = {}
    for order in coupang_orders:
        pool = list(entry_by_name.get(order["name"], [])) if order["name"] else []
        pooled = {id(entry) for entry in pool}
        if order["phone"]:
            pool += [entry for entry in entry_by_phone.get(order["phone"], []) if id(entry) not in pooled]
        candidates[id(order)] = pool

    def name_eq(order: dict, entry: dict) -> bool:
        return bool(order["name"]) and entry["name"] == order["name"]

    def usable(order: dict, entry: dict) -> bool:
        # 이 송장이 이미 다른 묶음에 들어가 있으면(배송지시·배송중·배송완료) 쓰지 않는다
        boxes = registered.get(_invoice_key(entry["tracking"]))
        return not boxes or order["shipment_box_id"] in boxes

    def name_guard(order: dict) -> bool:
        return requires_option_guard(order["name"], coupang_name_counts, len(entry_by_name.get(order["name"], [])))

    def phone_guard(order: dict) -> bool:
        return requires_option_guard(order["name"], coupang_name_counts, len(entry_by_phone.get(order["phone"], [])))

    def claimed_by(order: dict, entry: dict, phones: set[str]) -> bool:
        # 회신 전화가 이 주문이 아닌 다른 쿠팡 주문의 안심번호다 — 그 주문 몫
        return bool(entry["phone"]) and entry["phone"] != order["phone"] and entry["phone"] in phones

    def option_only_ok(order: dict, entry: dict) -> bool:
        # 전화로 못 가른 주문 — 이름+옵션은 한쪽 전화가 비었을 때만. 결제완료는 전화 없이 확인 처리하지 않는다.
        # 전화가 양쪽 다 있는데 다르면 다른 주문이고, 회신 전화가 다른 주문(출고된 주문 포함)의 안심번호면 그 주문 몫이다.
        return (
            order.get("order_status") != "ACCEPT"
            and not _phone_conflict(order, entry)
            and not claimed_by(order, entry, other_order_phones)
        )

    tiers = [
        # 1) 이름+전화(주문별 안심번호) — 같은 사람 여러 주문은 옵션 > 주소 순으로 가른다.
        lambda o, e: name_eq(o, e) and _phone_eq(o, e) and _option_eq(o, e) and _address_eq(o, e),
        lambda o, e: name_eq(o, e) and _phone_eq(o, e) and _option_eq(o, e),
        lambda o, e: name_eq(o, e) and _phone_eq(o, e) and not name_guard(o),
        # 2) 전화만 일치 — CS로 수취인 이름이 바뀐 경우(전화번호는 보통 유지됨)
        lambda o, e: not name_eq(o, e) and _phone_eq(o, e) and _option_eq(o, e) and _address_eq(o, e),
        lambda o, e: not name_eq(o, e) and _phone_eq(o, e) and _option_eq(o, e),
        lambda o, e: not name_eq(o, e) and _phone_eq(o, e) and not phone_guard(o),
        # 3) 전화로 못 가른 상품준비중 주문 — 이름+옵션
        lambda o, e: name_eq(o, e) and _option_eq(o, e) and _address_eq(o, e) and option_only_ok(o, e),
        lambda o, e: name_eq(o, e) and _option_eq(o, e) and option_only_ok(o, e),
    ]
    matched: dict[int, dict] = {}
    used: set[int] = set()
    for allowed in tiers:
        _assign_tier(
            coupang_orders, candidates, matched, used,
            lambda o, e, allowed=allowed: usable(o, e) and allowed(o, e),
        )

    reasons: dict[int, tuple[str, str | None]] = {}
    for order in coupang_orders:
        if id(order) in matched:
            continue
        pool = candidates[id(order)]
        live = [entry for entry in pool if usable(order, entry)]
        hits = [entry for entry in live if _phone_eq(order, entry) or (name_eq(order, entry) and _option_eq(order, entry))]
        free = [entry for entry in hits if id(entry) not in used]
        if not pool:
            reasons[id(order)] = ("매칭되는 수령인 없음 (이름·전화번호 모두 불일치)", None)
        elif not live:
            reasons[id(order)] = ("이미 등록된 송장 — 다른 주문에 들어간 번호(같은 회신 재실행?)", pool[0]["tracking"])
        elif not hits:
            reasons[id(order)] = ("이름만 같음 — 전화·옵션 불일치(동명이인 의심, 수동 확인)", None)
        elif free and all(claimed_by(order, entry, shipped_only_phones) for entry in free):
            reasons[id(order)] = ("출고된 다른 주문 몫 송장 — 같은 회신 재실행?(수동 확인)", free[0]["tracking"])
        elif order.get("order_status") == "ACCEPT" and not any(_phone_eq(order, entry) for entry in hits):
            reasons[id(order)] = ("결제완료 주문 — 전화 불일치라 확인 처리 안 함(수동 확인)", None)
        elif not free:
            reasons[id(order)] = ("회신 운송장 수 부족 — 같은 이름 송장은 다른 주문에 배정", None)
        elif all(_phone_conflict(order, entry) for entry in free):
            reasons[id(order)] = ("전화 불일치 — 동명이인·다른 주문 의심(수동 확인)", None)
        else:
            reasons[id(order)] = ("같은 이름 여러 주문 — 전화·옵션으로 구분 불가(수동 확인)", None)
    return matched, reasons


async def process_tracking_api(haedal_bytes: bytes) -> dict:
    """Parse tracking file, match Coupang orders, and register invoices."""
    haedal_entries = parse_haedal_file(haedal_bytes)
    if not haedal_entries:
        raise ValueError("해달 발주서에서 운송장번호를 찾을 수 없습니다.")

    fetched_orders = await fetch_pending_orders()
    # 송장이 이미 들어간 주문(배송지시·배송중·배송완료)은 짝짓지 않고 그 송장번호·안심번호만 재실행 방지에 쓴다
    coupang_orders = [order for order in fetched_orders if order.get("order_status") not in SHIPPED_STATUSES]
    if not coupang_orders:
        raise ValueError("결제완료 또는 상품준비중인 고구마 주문이 없습니다.")
    registered = _registered_invoices(fetched_orders)
    shipped_phones = {
        order["phone"]
        for order in fetched_orders
        if order.get("order_status") in SHIPPED_STATUSES and order.get("phone")
    }

    matched_entries, skip_reasons = _match_orders(coupang_orders, haedal_entries, registered, shipped_phones)

    matched_pairs = []
    matched_via_phone: dict[int, str] = {}  # id(order) -> 해달측 이름 (전화번호 매칭 표시용)
    results = []
    skip_count = 0

    for order in coupang_orders:
        matched = matched_entries.get(id(order))
        if matched is None:
            skip_count += 1
            message, shown_tracking = skip_reasons[id(order)]
            skipped = {
                "order_id": str(order["order_id"]),
                "name": order["name_display"],
                "status": "skip",
                "message": message,
            }
            if shown_tracking:
                skipped["tracking"] = shown_tracking
            results.append(skipped)
            continue

        order["delivery_code"] = matched.get("delivery_company_code") or DELIVERY_COMPANY_CODE
        matched_pairs.append((order, matched["tracking"]))
        if matched["name"] != order["name"]:
            matched_via_phone[id(order)] = matched["name"]

    # 한 주문(묶음 shipmentBoxId)에 상품이 여럿이면 해달은 상품마다 박스·송장을 따로 보낸다. 쿠팡은 분리배송이
    # 아니면 묶음 하나에 송장 하나만 받아, 서로 다른 송장을 같이 올리면 거부돼 하나도 안 들어갔다
    # (2026-11-02 파소향 3kg+5kg). 사용자 지시: 송장은 하나만, 더 비싼 옵션의 송장으로(2026-11-03 — 5kg 특상 송장).
    box_pairs: dict = defaultdict(list)
    for order, tracking in matched_pairs:
        box_pairs[order["shipment_box_id"]].append((order, tracking))
    bundle_notes: dict[int, str] = {}  # id(order) -> 결과 표시용 설명
    box_keep: dict = {}
    for box, pairs in box_pairs.items():
        trackings = list(dict.fromkeys(tracking for _order, tracking in pairs))
        if len(trackings) < 2:
            continue
        # 가격(salesPrice, 없으면 orderPrice) → 무게 → 크기 순. max는 순위가 같으면 앞의 것 → 모두 같으면 첫 송장
        keep_order, keep_tracking = max(
            pairs, key=lambda pair: option_rank(pair[0].get("price"), pair[0].get("order_price"), pair[0].get("item_name"))
        )
        box_keep[box] = (keep_tracking, keep_order.get("delivery_code"))
        others = "·".join(t for t in trackings if t != keep_tracking)
        option_label = (keep_order.get("item_name") or "").split(",")[-1].strip()  # '상품명, 1박스, 옵션' → 옵션
        for order, _tracking in pairs:
            bundle_notes[id(order)] = (
                f"한 주문 송장 {len(trackings)}개 → 더 비싼 '{option_label}' 송장 "
                f"{keep_tracking} 하나로, {others}는 같은 주문 다른 박스"
            )
    if box_keep:
        unified_pairs = []
        for order, tracking in matched_pairs:
            keep = box_keep.get(order["shipment_box_id"])
            if keep:
                tracking, order["delivery_code"] = keep
            unified_pairs.append((order, tracking))
        matched_pairs = unified_pairs

    success_count = 0
    fail_count = 0

    def _build_dtos(pairs: list[tuple[dict, str]]) -> list[dict]:
        return [
            {
                "shipmentBoxId": order["shipment_box_id"],
                "orderId": order["order_id"],
                "vendorItemId": order["vendor_item_id"],
                "deliveryCompanyCode": order.get("delivery_code") or DELIVERY_COMPANY_CODE,
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

    def _extract_response_list(api_result: dict) -> list[dict]:
        """쿠팡 송장업로드 응답에서 결과 항목 리스트를 꺼낸다.

        응답 구조가 버전/케이스별로 달라서 모두 대응:
          - {"data": {"responseList": [...]}}
          - {"data": [...]}                  (data 자체가 리스트)
          - {"responseList": [...]}          (data 래핑 없음)
        """
        if not isinstance(api_result, dict):
            return []
        data = api_result.get("data")
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict):
            rl = data.get("responseList")
            if isinstance(rl, list):
                return [x for x in rl if isinstance(x, dict)]
        rl = api_result.get("responseList")
        if isinstance(rl, list):
            return [x for x in rl if isinstance(x, dict)]
        return []

    def _item_failed(item: dict) -> tuple[bool, str, object]:
        """결과 항목이 '실패'인지 판정. (failed, message, result_code)

        쿠팡은 성공 시 succeed=true 또는 resultCode가 SUCCESS류이거나
        resultMessage가 비어있다. 명확한 실패 신호가 있을 때만 실패로 본다.
        """
        result_code = item.get("resultCode")
        result_message = item.get("resultMessage") or ""
        succeed = item.get("succeed")

        # 명시적 성공 신호
        if succeed is True:
            return (False, "", result_code)
        code_str = str(result_code or "").upper()
        if code_str in ("SUCCESS", "200", "0", "OK"):
            return (False, "", result_code)
        # 명시적 실패 신호 (succeed가 False이거나 실패 메시지/코드가 있음)
        if succeed is False:
            return (True, result_message or code_str or "등록 실패", result_code)
        if result_message and code_str not in ("", "SUCCESS", "200", "0", "OK"):
            return (True, result_message, result_code)
        if code_str and code_str not in ("SUCCESS", "200", "0", "OK"):
            return (True, result_message or code_str, result_code)
        # 신호 없음 → 배치 code가 200이면 성공으로 간주(상위에서 처리)
        return (False, "", result_code)

    async def _upload_and_parse(pairs: list[tuple[dict, str]]):
        dtos = _build_dtos(pairs)
        try:
            api_result = await coupang_goguma_client.upload_invoices(dtos)
            logger.info("쿠팡 송장업로드 API 응답: %s", api_result)
        except Exception as exc:
            logger.error("쿠팡 송장업로드 API 오류: %s", exc)
            return [], [(order, tracking, str(exc), None) for order, tracking in pairs]

        if not isinstance(api_result, dict) or not api_result:
            # 재시도를 다 써도 응답이 없으면(None) 등록됐는지 알 수 없다 — 성공으로 세지 않는다
            message = "쿠팡 응답 없음 — Wing에서 등록 여부 확인"
            return [], [(order, tracking, message, None) for order, tracking in pairs]

        top_code = api_result.get("code")
        response_list = _extract_response_list(api_result)

        # 배치 자체가 거부된 경우 (HTTP 200 envelope이지만 code가 에러)
        batch_ok = str(top_code or "").upper() in ("200", "0", "OK", "SUCCESS") or top_code is None

        # 결과 항목이 없으면: 배치 성공이면 전체 성공, 아니면 전체 실패
        if not response_list:
            if batch_ok:
                return list(pairs), []
            msg = api_result.get("message") or "쿠팡 응답에 결과 목록이 없습니다."
            return [], [(order, tracking, str(msg), top_code) for order, tracking in pairs]

        success_pairs: list[tuple[dict, str]] = []
        fail_pairs: list[tuple[dict, str, str, object]] = []

        # shipmentBoxId 기준 매칭이 가능하면 우선 사용, 안 되면 순서(zip) 기반.
        # 쿠팡은 요청 순서대로 결과를 돌려주므로 zip이 안전한 기본값.
        def _norm_id(v):
            try:
                return int(v)
            except (TypeError, ValueError):
                return None

        resp_by_box: dict[int, dict] = {}
        for item in response_list:
            bid = _norm_id(item.get("shipmentBoxId"))
            if bid is not None and bid != 0:
                resp_by_box.setdefault(bid, item)

        use_box_match = len(resp_by_box) >= len(pairs) > 0

        for idx, (order, tracking) in enumerate(pairs):
            item = None
            if use_box_match:
                item = resp_by_box.get(_norm_id(order["shipment_box_id"]))
            if item is None and idx < len(response_list):
                item = response_list[idx]  # 순서 기반 fallback
            if item is None:
                # 결과 항목을 못 찾았지만 배치가 성공이면 성공으로 간주
                if batch_ok:
                    success_pairs.append((order, tracking))
                else:
                    fail_pairs.append((order, tracking, "결과 항목 없음", top_code))
                continue

            failed, message, result_code = _item_failed(item)
            if failed:
                fail_pairs.append((order, tracking, str(message or "등록 실패"), result_code))
            else:
                success_pairs.append((order, tracking))

        return success_pairs, fail_pairs

    async def _confirm(boxes: list, label: str) -> str:
        """결제완료 → 상품준비중 확인 처리. 응답 없음(None)·예외면 그 사유, 아니면 ''."""
        try:
            confirm_result = await coupang_goguma_client.confirm_orders(boxes)
        except Exception as exc:
            logger.error("%s 실패: %s", label, exc)
            return str(exc) or type(exc).__name__
        logger.info("%s 응답: %s", label, confirm_result)
        if confirm_result is None:
            return "쿠팡 응답 없음"
        code = confirm_result.get("code") if isinstance(confirm_result, dict) else None
        if code not in (200, "200", 0, None):
            logger.warning("쿠팡 주문 확인 응답 이상: %s", confirm_result)
        return ""

    if matched_pairs:
        # 매칭된 주문 중 결제완료(ACCEPT)만 확인 처리 — 송장 등록은 상품준비중에서만 가능.
        # 매칭 안 된 결제완료 주문은 건드리지 않는다(결제완료는 전화가 맞을 때만 매칭된다 — _match_orders).
        confirm_fail_items: list[tuple[dict, str, str, object]] = []
        matched_accept_boxes = list({
            order["shipment_box_id"]
            for order, _ in matched_pairs
            if order.get("order_status") == "ACCEPT"
        })
        if matched_accept_boxes:
            logger.info("매칭된 결제완료 주문 %s건 확인 처리(상품준비중 전환)", len(matched_accept_boxes))
            confirm_error = await _confirm(matched_accept_boxes, "쿠팡 주문 확인")
            if confirm_error:
                # 확인 처리가 안 된 결제완료 주문엔 송장을 올리지 않고 실패로 집계 — 상품준비중 주문은 계속 등록한다
                confirm_fail_items = [
                    (order, tracking, f"결제완료 주문 확인 처리 실패 — 송장 미등록 ({confirm_error})", None)
                    for order, tracking in matched_pairs
                    if order.get("order_status") == "ACCEPT"
                ]
                matched_pairs = [pair for pair in matched_pairs if pair[0].get("order_status") != "ACCEPT"]
            await asyncio.sleep(3)

        success_pairs: list[tuple[dict, str]] = []
        fail_items: list[tuple[dict, str, str, object]] = []
        if matched_pairs:
            success_pairs, fail_items = await _upload_and_parse(matched_pairs)

        retry_pairs = [(order, tracking) for order, tracking, msg, code in fail_items if _is_accept_related_error(msg, code)]
        retry_boxes = list({order["shipment_box_id"] for order, _ in retry_pairs})
        if retry_pairs:
            logger.info("상태 전이 의심 %s건 재시도 시작", len(retry_pairs))
            confirm_error = await _confirm(retry_boxes, "재시도용 주문 확인")
            if confirm_error:
                retry_success = []
                retry_fail = [
                    (order, tracking, f"주문 확인 재시도 실패 — 송장 미등록 ({confirm_error})", None)
                    for order, tracking in retry_pairs
                ]
            else:
                await asyncio.sleep(3)
                retry_success, retry_fail = await _upload_and_parse(retry_pairs)
            success_pairs.extend(retry_success)
            fail_items = [
                item for item in fail_items if not _is_accept_related_error(item[2], item[3])
            ] + retry_fail
        fail_items = confirm_fail_items + fail_items

        for order, tracking in success_pairs:
            success_count += 1
            haedal_name = matched_via_phone.get(id(order))
            if haedal_name:
                message = f"운송장 등록 완료 (전화번호 매칭: 해달 '{haedal_name}' → 쿠팡 '{order['name_display']}')"
            else:
                message = "운송장 등록 완료"
            if id(order) in bundle_notes:
                message = f"{message} ({bundle_notes[id(order)]})"
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
            if id(order) in bundle_notes:
                message = f"{message} ({bundle_notes[id(order)]})"
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
