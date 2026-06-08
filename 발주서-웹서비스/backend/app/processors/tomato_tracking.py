import re
import logging
from datetime import datetime, timezone, timedelta
from io import BytesIO
from collections import defaultdict

from openpyxl import load_workbook

from app.config import TEMPLATE_DIR
from app.processors.tomato_order import (
    JBT_WATERMELON_KGS,
    JBT_WATERMELON_LABEL,
    delivery_watermelon_kg,
    is_toss_watermelon_order,
    transform_product,
)
from app.processors.tracking_match import (
    name_counts,
    normalize_courier_name,
    option_key_set,
    options_match,
    requires_option_guard,
)
from app.toss.client import toss_client


logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))
TOSS_DELIVERY_COMPANY = "한진택배"
TRACKABLE_TOSS_STATUSES = {"PAID", "PREPARING_PRODUCT", "DELIVERING"}


def normalize(value) -> str:
    """공백 완전 제거 후 문자열 반환 (이름 매칭용)"""
    if value is None:
        return ""
    return re.sub(r'\s+', '', str(value).strip())


def normalize_courier(name: str) -> str:
    """택배사명 정규화 — 쿠팡이 인식하는 형태로 변환.

    예: 'CJ대한통운' -> 'CJ 대한통운' (띄어쓰기 필수)
    """
    return normalize_courier_name(name)


def is_mixed_chamoe_row(product_name: str, option_text: str) -> bool:
    return "성주참외" in product_name and "가정용 혼합과" in option_text


def product_type_for(product_name: str) -> str:
    if "토마토" in product_name:
        return "토마토"
    if "참외" in product_name:
        return "참외"
    if "땅두릅" in product_name or "두릅" in product_name:
        return "땅두릅"
    if "수박" in product_name:
        return "수박"
    if "옥수수" in product_name:
        return "옥수수"
    return ""


def corn_option_keys(*values: object) -> set[str]:
    text = normalize(" ".join(str(value) for value in values if value not in (None, "")))
    if "옥수수" not in text:
        return set()
    grade = "중품" if "중품" in text else "특품" if "특품" in text else ""
    counts = set(re.findall(r"(\d+)\s*(?:개|입)", text))
    if not grade or not counts:
        return set()
    return {f"corn:{grade}:{count}개" for count in counts}


def is_jbt_tracking_target(product_name: str, option_text: str) -> bool:
    if is_mixed_chamoe_row(product_name, option_text):
        return False
    product_type = product_type_for(product_name)
    if product_type in {"토마토", "참외", "땅두릅"}:
        return True
    if product_type == "수박":
        return delivery_watermelon_kg(product_name, option_text) in JBT_WATERMELON_KGS
    if product_type == "옥수수":
        return bool(corn_option_keys(product_name, option_text))
    return False


def _toss_item_text(value) -> str:
    parts: list[str] = []

    def walk(node) -> None:
        if node is None:
            return
        if isinstance(node, dict):
            for child in node.values():
                walk(child)
            return
        if isinstance(node, (list, tuple)):
            for child in node:
                walk(child)
            return
        parts.append(str(node))

    walk(value)
    return " ".join(parts)


def _toss_order_id(item: dict) -> str:
    for key in ("orderNo", "orderId", "orderNumber", "orderSheetId", "paymentKey"):
        value = item.get(key)
        if value:
            return str(value)
    return ""


def parse_reply_file(tomato_reply_bytes: bytes) -> list[dict]:
    """Parse 제이비티 회신 파일.

    Columns: A=송장번호, B=수령인, C=연락처, D=주소, E=품목명, K=택배사.
    """
    tr_wb = load_workbook(filename=BytesIO(tomato_reply_bytes), data_only=True)
    tr_ws = tr_wb.active

    entries = []
    for row_idx in range(2, tr_ws.max_row + 1):
        tracking = normalize(tr_ws.cell(row=row_idx, column=1).value)
        name = normalize(tr_ws.cell(row=row_idx, column=2).value)
        phone = normalize(tr_ws.cell(row=row_idx, column=3).value)
        address = normalize(tr_ws.cell(row=row_idx, column=4).value)
        product = tr_ws.cell(row=row_idx, column=5).value
        courier_raw = tr_ws.cell(row=row_idx, column=11).value
        courier = str(courier_raw).strip() if courier_raw else ""

        if not name or not tracking:
            continue

        entries.append({
            "name": name,
            "phone": phone,
            "address": address,
            "tracking": tracking,
            "courier": courier,
            "option_keys": option_key_set(product) | corn_option_keys(product),
        })

    return entries


async def process_toss_watermelon_tracking(tomato_reply_bytes: bytes) -> dict:
    """Register 제이비티 수박 6/7/8kg tracking numbers to Toss orders."""
    reply_entries = parse_reply_file(tomato_reply_bytes)
    if not reply_entries:
        return {
            "toss_orders": 0,
            "toss_success": 0,
            "toss_fail": 0,
            "toss_skip": 0,
            "toss_error": "제이비티 회신 파일에서 운송장번호를 찾을 수 없습니다.",
        }

    now = datetime.now(KST)
    from_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    to_date = now.strftime("%Y-%m-%d")

    toss_orders_raw = await toss_client.get_orders(
        start_date=from_date,
        end_date=to_date,
        status=None,
    )

    toss_orders = []
    skip_count = 0
    seen_order_product_ids = set()

    for item in toss_orders_raw:
        if not is_toss_watermelon_order(item):
            continue

        option = str(item.get("optionName") or "")
        if delivery_watermelon_kg(_toss_item_text(item), option) not in JBT_WATERMELON_KGS:
            continue

        order_product_id = item.get("orderProductId")
        if not order_product_id or order_product_id in seen_order_product_ids:
            continue
        seen_order_product_ids.add(order_product_id)

        existing_tracking = normalize(item.get("shippingTrackingNumber") or item.get("trackingNumber") or "")
        order_status = str(item.get("orderProductStatus") or item.get("status") or item.get("orderStatus") or "").strip().upper()
        order_id = _toss_order_id(item)
        receiver_name = item.get("receiverName") or ""
        receiver_phone = item.get("receiverRealPhone") or item.get("receiverPhone") or ""
        address = item.get("address") or item.get("receiverAddress1") or ""
        detail_address = item.get("detailAddress") or item.get("receiverAddress2") or ""
        full_address = f"{address} {detail_address}".strip()

        if existing_tracking:
            skip_count += 1
            continue
        if order_status and order_status not in TRACKABLE_TOSS_STATUSES:
            skip_count += 1
            continue

        toss_orders.append({
            "order_product_id": order_product_id,
            "order_id": order_id,
            "name": normalize(receiver_name),
            "phone": normalize(receiver_phone),
            "address": normalize(full_address),
            "name_display": receiver_name,
            "option_keys": option_key_set(
                option,
                transform_product(option, "수박"),
                item.get("productName"),
            ),
        })

    entry_by_name = defaultdict(list)
    entry_by_phone = defaultdict(list)
    entry_by_address = defaultdict(list)
    for entry in reply_entries:
        entry_by_name[entry["name"]].append(entry)
        if entry["phone"]:
            entry_by_phone[entry["phone"]].append(entry)
        if entry["address"]:
            entry_by_address[entry["address"]].append(entry)

    used_entries = set()
    matched_pairs = []
    toss_name_counts = name_counts(order["name"] for order in toss_orders)

    for order in toss_orders:
        candidates = entry_by_name.get(order["name"], [])
        if not candidates and order["phone"]:
            candidates = entry_by_phone.get(order["phone"], [])
        if not candidates and order["address"]:
            candidates = entry_by_address.get(order["address"], [])
        available = [entry for entry in candidates if id(entry) not in used_entries]
        if not available:
            skip_count += 1
            continue

        if requires_option_guard(order["name"], toss_name_counts, len(candidates)):
            available = [
                entry for entry in available
                if options_match(entry.get("option_keys"), order.get("option_keys"))
            ]
            if not available:
                skip_count += 1
                continue

        matched = None
        for entry in available:
            if entry["phone"] == order["phone"] and entry["address"] == order["address"]:
                matched = entry
                break
        if matched is None:
            for entry in available:
                if entry["phone"] == order["phone"]:
                    matched = entry
                    break
        if matched is None:
            for entry in available:
                if entry["address"] == order["address"]:
                    matched = entry
                    break
        if matched is None:
            for entry in available:
                if options_match(entry.get("option_keys"), order.get("option_keys")):
                    matched = entry
                    break
        if matched is None:
            matched = available[0]

        used_entries.add(id(matched))
        matched_pairs.append((order, matched["tracking"]))

    success_count = 0
    fail_count = 0

    for order, tracking in matched_pairs:
        try:
            await toss_client.register_tracking(
                order_product_id=order["order_product_id"],
                delivery_company=TOSS_DELIVERY_COMPANY,
                tracking_number=tracking,
            )
            success_count += 1
        except Exception as exc:
            fail_count += 1
            logger.error(
                f"토스 {JBT_WATERMELON_LABEL} 운송장 등록 실패 "
                "(orderProductId=%s, orderId=%s): %s",
                order.get("order_product_id"),
                order.get("order_id"),
                exc,
            )

    return {
        "toss_orders": len(toss_orders) + skip_count,
        "toss_success": success_count,
        "toss_fail": fail_count,
        "toss_skip": skip_count,
    }



def process(
    tomato_reply_bytes: bytes,
    delivery_bytes: bytes,
    delivery_company: str = "",
) -> tuple[bytes, str, dict]:
    """Input tracking numbers from 대저토마토 회신 파일 into DeliveryList.

    Args:
        tomato_reply_bytes: Raw bytes of the 대저토마토 회신 Excel file.
            Columns: A=송장번호, B=수령인(성함), C=수령인(연락처), D=수령인(주소), K=택배사
        delivery_bytes: Raw bytes of the DeliveryList Excel file.
        delivery_company: 택배사 이름 (미지정 시 회신 파일 K열에서 읽음)

    Returns:
        Tuple of (output_bytes, filename, stats_dict).
    """
    tomato_entries = parse_reply_file(tomato_reply_bytes)

    # Load DeliveryList
    dl_wb = load_workbook(filename=BytesIO(delivery_bytes))
    dl_ws = dl_wb.active

    # Keep only first sheet
    first_sheet_name = dl_wb.sheetnames[0]
    for sheet_name in dl_wb.sheetnames[1:]:
        del dl_wb[sheet_name]
    dl_ws = dl_wb[first_sheet_name]

    # Build index by name
    entry_by_name = defaultdict(list)
    for entry in tomato_entries:
        entry_by_name[entry["name"]].append(entry)

    used_entries = set()
    filled = 0
    skipped = 0
    has_tomato = False
    has_chamoe = False
    has_ddureup = False
    has_watermelon = False
    has_corn = False
    delivery_name_counts = name_counts(
        normalize(dl_ws.cell(row=row_idx, column=27).value)
        for row_idx in range(2, dl_ws.max_row + 1)
    )

    for row_idx in range(2, dl_ws.max_row + 1):
        # Column E = 5 (tracking number destination)
        e_cell = dl_ws.cell(row=row_idx, column=5)

        # Only fill empty E cells
        if e_cell.value is not None and normalize(e_cell.value) != "":
            continue

        product_name = str(dl_ws.cell(row=row_idx, column=11).value or "")
        option_text = str(dl_ws.cell(row=row_idx, column=12).value or "")
        if not is_jbt_tracking_target(product_name, option_text):
            continue

        dl_name = normalize(dl_ws.cell(row=row_idx, column=27).value)     # AA
        dl_phone = normalize(dl_ws.cell(row=row_idx, column=28).value)    # AB
        dl_address = normalize(dl_ws.cell(row=row_idx, column=30).value)  # AD
        dl_option_keys = option_key_set(
            option_text,
            transform_product(option_text, product_type_for(product_name)),
        ) | corn_option_keys(product_name, option_text)
        if not dl_option_keys:
            dl_option_keys = option_key_set(product_name)

        if not dl_name:
            continue

        candidates = entry_by_name.get(dl_name, [])
        if not candidates:
            skipped += 1
            continue

        available = [
            (i, c) for i, c in enumerate(candidates)
            if id(c) not in used_entries
        ]
        if not available:
            skipped += 1
            continue

        if requires_option_guard(dl_name, delivery_name_counts, len(candidates)):
            available = [
                (i, c) for i, c in available
                if options_match(c.get("option_keys"), dl_option_keys)
            ]
            if not available:
                skipped += 1
                continue

        matched = None

        # Try phone + address match first
        for idx, c in available:
            if c["phone"] == dl_phone and c["address"] == dl_address:
                matched = c
                break

        # Try phone only match
        if matched is None:
            for idx, c in available:
                if c["phone"] == dl_phone:
                    matched = c
                    break

        # Try address only match
        if matched is None:
            for idx, c in available:
                if c["address"] == dl_address:
                    matched = c
                    break

        # Fall back to first available
        if matched is None:
            matched = available[0][1]

        if matched:
            e_cell.value = matched["tracking"]
            # D열(4) = 택배사: 회신 파일 K열 값을 무조건 DeliveryList D열에 덮어쓰기
            courier_val = matched.get("courier") or delivery_company
            dl_ws.cell(row=row_idx, column=4).value = normalize_courier(courier_val) if courier_val else ""
            used_entries.add(id(matched))
            filled += 1

            # K열(11) = 상품명 → 제이비티 발주 상품 판별
            if "토마토" in product_name:
                has_tomato = True
            if "참외" in product_name:
                has_chamoe = True
            if "땅두릅" in product_name:
                has_ddureup = True
            if "수박" in product_name:
                has_watermelon = True
            if "옥수수" in product_name:
                has_corn = True
        else:
            skipped += 1

    # Save to bytes
    output = BytesIO()
    dl_wb.save(output)
    output.seek(0)

    # 파일명: 실제 처리된 상품에 따라 동적 생성
    now = datetime.now(KST)
    parts = []
    if has_tomato:
        parts.append("대저토마토")
    if has_chamoe:
        parts.append("성주참외")
    if has_ddureup:
        parts.append("남해땅두릅")
    if has_watermelon:
        parts.append("수박")
    if has_corn:
        parts.append("초당옥수수")
    product_label = "_".join(parts) if parts else "발주"
    filename = f"송장파일_{product_label}({now.strftime('%Y%m%d')}).xlsx"
    stats = {
        "filled": filled,
        "skipped": skipped,
        "tomato_entries": len(tomato_entries),
    }

    return output.read(), filename, stats
