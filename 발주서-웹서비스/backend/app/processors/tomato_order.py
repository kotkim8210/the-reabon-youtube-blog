import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha1
from io import BytesIO

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.styles.colors import Color

KST = timezone(timedelta(hours=9))
JBT_SENDER_NAME = "(주)아이티소프트"
TOSS_WATERMELON_EXCLUDED_STATUS_PATTERNS = ("CANCEL", "RETURN", "REFUND", "EXCHANGE")
JBT_WATERMELON_KGS = {6, 7, 8}
JBT_WATERMELON_LABEL = "수박 6/7/8kg"


@dataclass
class _VirtualCell:
    value: object = ""


def normalize(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def is_mixed_chamoe(product_name: str, option_text: str) -> bool:
    return "성주참외" in product_name and "가정용 혼합과" in option_text


def delivery_watermelon_kg(product_name: str = "", option_text: str = "") -> int | None:
    text = normalize(f"{product_name} {option_text}")
    if "수박" not in text:
        return None
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*kg", text, re.IGNORECASE):
        try:
            kg = float(match.group(1))
        except ValueError:
            continue
        if kg.is_integer():
            return int(kg)
    return None


def is_jbt_corn_order(product_name: str = "", option_text: str = "") -> bool:
    text = normalize(f"{product_name} {option_text}")
    return "옥수수" in text and ("중품" in text or "특품" in text)


def stable_order_id(prefix: str, *values) -> str:
    raw = "|".join(normalize(value) for value in values if normalize(value))
    if not raw:
        return ""
    return f"{prefix}:{sha1(raw.encode('utf-8')).hexdigest()[:16]}"


def toss_order_id(item: dict) -> str:
    for key in ("orderNo", "orderId", "orderNumber", "orderSheetId", "paymentKey", "orderProductId"):
        value = item.get(key)
        if value:
            return str(value)
    return ""


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
    return normalize(" ".join(parts))


def is_toss_watermelon_order(item: dict) -> bool:
    return "수박" in _toss_item_text(item)


def _toss_address(item: dict) -> str:
    address = item.get("address") or item.get("receiverAddress1") or ""
    detail = item.get("detailAddress") or item.get("receiverAddress2") or ""
    return normalize(f"{address} {detail}".strip())


def _toss_zipcode(item: dict) -> str:
    zipcode = normalize(item.get("zipCode") or item.get("receiverZipCode") or "")
    if not zipcode:
        return ""
    try:
        return str(int(float(zipcode))).zfill(5)
    except (TypeError, ValueError):
        return zipcode.zfill(5)


def _toss_watermelon_option(item: dict) -> str:
    option = normalize(item.get("optionName") or "")
    if option:
        return option
    product_name = normalize(item.get("productName") or "")
    kg_match = re.search(r"(\d+\.?\d*)\s*kg", product_name, re.IGNORECASE)
    if kg_match:
        return f"{kg_match.group(1)}kg"
    kg_match = re.search(r"(\d+\.?\d*)\s*kg", _toss_item_text(item), re.IGNORECASE)
    if kg_match:
        return f"{kg_match.group(1)}kg"
    return product_name


def _virtual_toss_row(entry: dict) -> list[_VirtualCell]:
    row = [_VirtualCell() for _ in range(31)]
    row[2].value = entry.get("order_id", "")
    row[10].value = entry.get("product_name", "토스 수박")
    row[11].value = entry.get("option", "")
    row[22].value = entry.get("qty", "1")
    row[26].value = entry.get("name", "")
    row[27].value = entry.get("phone", "")
    row[28].value = entry.get("zipcode", "")
    row[29].value = entry.get("address", "")
    row[30].value = entry.get("memo", "")
    return row


async def collect_toss_watermelon_orders(from_date: str, to_date: str) -> list[dict]:
    from app.toss.client import toss_client

    orders = await toss_client.get_orders(
        start_date=from_date,
        end_date=to_date,
        status=None,
    )

    entries: list[dict] = []
    for item in orders:
        if not is_toss_watermelon_order(item):
            continue
        order_status = normalize(item.get("orderProductStatus") or item.get("status") or item.get("orderStatus") or "")
        if order_status and any(pattern in order_status.upper() for pattern in TOSS_WATERMELON_EXCLUDED_STATUS_PATTERNS):
            continue

        option = _toss_watermelon_option(item)
        if delivery_watermelon_kg(_toss_item_text(item), option) not in JBT_WATERMELON_KGS:
            continue

        address = _toss_address(item)
        entries.append(
            {
                "name": item.get("receiverName") or "",
                "phone": item.get("receiverRealPhone") or item.get("receiverPhone") or "",
                "zipcode": _toss_zipcode(item),
                "address": address,
                "qty": str(item.get("quantity") or 1),
                "product_name": item.get("productName") or "토스 수박",
                "option": option,
                "memo": item.get("shippingNote") or "",
                "order_id": toss_order_id(item)
                or stable_order_id(
                    "toss-watermelon",
                    item.get("receiverName"),
                    item.get("receiverRealPhone") or item.get("receiverPhone"),
                    address,
                    option,
                    item.get("quantity") or 1,
                ),
            }
        )

    return entries


async def process_toss_watermelon_order(from_date: str, to_date: str) -> tuple[bytes, str, dict]:
    entries = await collect_toss_watermelon_orders(from_date, to_date)
    if not entries:
        raise ValueError(f"토스 {JBT_WATERMELON_LABEL} 주문을 찾지 못했습니다. 기간: {from_date} ~ {to_date}")

    output_bytes, filename, stats = build_main_order_workbook(
        filtered_rows=[(_virtual_toss_row(entry), "수박") for entry in entries],
        has_tomato=False,
        has_chamoe=False,
        has_ddureup=False,
        has_watermelon=True,
        has_corn=False,
    )
    today = datetime.now(KST).strftime("%Y%m%d")
    filename = f"아이티소프트_토스수박6_7_8kg({today}).xlsx"
    stats = {
        **stats,
        "platform": "토스",
        "period": f"{from_date} ~ {to_date}",
    }
    return output_bytes, filename, stats


def transform_product(option_text: str, product_type: str = "") -> str:
    text = normalize(option_text)

    if product_type == "옥수수":
        grade = "중품" if "중품" in text else "특품" if "특품" in text else ""
        count_match = re.search(r"(\d+)\s*(?:개|입)", text)
        if grade and count_match:
            result = f"초당옥수수 {grade} {count_match.group(1)}개"
        else:
            result = text
        return result if result.endswith("_vip") else f"{result}_vip"

    if product_type == "수박":
        kg_match = re.search(r"(\d+\.?\d*)\s*kg", text, re.IGNORECASE)
        if kg_match:
            result = f"하우스수박(상품){kg_match.group(1)}kg이상"
        else:
            result = f"하우스수박(상품){text}".strip()
        return result if result.endswith("_vip") else f"{result}_vip"

    if product_type == "땅두릅":
        weight_match = re.search(r"(\d+\.?\d*)\s*(g|kg)", text, re.IGNORECASE)
        if weight_match:
            amount = weight_match.group(1)
            unit = weight_match.group(2).lower()
            weight_str = f"{amount}{unit}"
            if unit == "g":
                result = f"남해땅두릅(튀김용){weight_str}"
            else:
                result = f"남해땅두릅(특품){weight_str}"
        else:
            result = f"남해땅두릅{text}"
        return result if result.endswith("_vip") else f"{result}_vip"

    kg_match = re.search(r"(\d+\.?\d*)\s*kg", text, re.IGNORECASE)
    kg_suffix = f" {kg_match.group(1)}kg" if kg_match else ""

    text = re.sub(r"^1박스\s*", "", text)

    if "가정용" in text:
        grade_match = re.search(r"(혼합과|중소과|로얄과)", text)
        grade = grade_match.group(1) if grade_match else ""
        fruit_match = re.search(r"\((\d+-\d+과)\)", text)
        fruit_suffix = f"({fruit_match.group(1)})" if fruit_match else ""
        if grade:
            kg_str = kg_suffix.strip()
            result = f"가정용참외({grade}){kg_str}{fruit_suffix}"
            return result if result.endswith("_vip") else f"{result}_vip"

    if "짭짤이" in text:
        if "로얄" in text or "S~2S" in text or "S-2S" in text:
            kg_str = kg_suffix.strip()
            result = f"대저짭짤이특품(S)과 {kg_str}"
            return result if result.endswith("_vip") else f"{result}_vip"
        return text if text.endswith("_vip") else f"{text}_vip"

    if "특품" in text:
        cleaned = re.sub(r"\d+\.?\d*\s*kg", "", text).strip()
        result = f"대저토마토{cleaned}{kg_suffix}"
        return result if result.endswith("_vip") else f"{result}_vip"

    return text if text.endswith("_vip") else f"{text}_vip"


def build_main_order_workbook(
    filtered_rows: list[tuple],
    has_tomato: bool,
    has_chamoe: bool,
    has_ddureup: bool,
    has_watermelon: bool,
    has_corn: bool = False,
) -> tuple[bytes, str, dict]:
    wb = Workbook()
    ws = wb.active

    headers = [
        "송장번호",
        "수령인(성함)",
        "수령인(연락처)",
        "수령인(주소)",
        "품목명",
        "수량",
        "배송메세지",
        "보내는분 상호",
        "보내는분 연락처\n(해당업체 연락처)",
        "주문번호",
    ]

    col_widths = {
        "A": 13,
        "B": 12.375,
        "C": 15.5,
        "D": 45,
        "E": 36.75,
        "F": 13,
        "G": 26,
        "H": 15.125,
        "I": 13.375,
        "J": 16.125,
    }
    for col_letter, width in col_widths.items():
        ws.column_dimensions[col_letter].width = width

    fill_theme6 = PatternFill(patternType="solid", fgColor=Color(theme=6, tint=0.4))
    fill_theme9 = PatternFill(patternType="solid", fgColor=Color(theme=9, tint=0.4))
    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )
    header_font = Font(name="맑은 고딕", size=11, bold=True)
    data_font = Font(name="맑은 고딕", size=11)
    sales_groups: dict[str, dict[str, dict]] = {}

    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.border = thin_border
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        if col_idx in (1, 6):
            cell.fill = fill_theme6
        elif col_idx in (2, 3, 4, 5, 7, 8, 9):
            cell.fill = fill_theme9

    for index, (row, product_type) in enumerate(filtered_rows):
        out_row = index + 2

        name = normalize(row[26].value) if len(row) > 26 else ""
        phone = normalize(row[27].value) if len(row) > 27 else ""
        address = normalize(row[29].value) if len(row) > 29 else ""
        option = normalize(row[11].value) if len(row) > 11 else ""
        qty_value = row[22].value if len(row) > 22 else ""
        qty = normalize(qty_value)
        memo = normalize(row[30].value) if len(row) > 30 else ""
        order_no = normalize(row[2].value) if len(row) > 2 else ""

        address = address.replace("*", "")
        product = transform_product(option, product_type)
        try:
            qty_int = int(qty_value) if qty_value else 1
        except (TypeError, ValueError):
            qty_int = 1

        if product_type == "토마토":
            product_label = "대저토마토"
        elif product_type == "참외":
            product_label = "성주참외"
        elif product_type == "땅두릅":
            product_label = "남해땅두릅"
        elif product_type == "수박":
            product_label = "수박"
        elif product_type == "옥수수":
            product_label = "초당옥수수"
        else:
            product_label = "제이비티"

        option_bucket = sales_groups.setdefault(product_label, {}).setdefault(
            option,
            {
                "coupang_option_keyword": option,
                "vendor_option_name": product,
                "quantity": 0,
                "orders": [],
            },
        )
        option_bucket["quantity"] += qty_int
        if order_no:
            option_bucket["orders"].append({"order_id": order_no, "quantity": qty_int})

        mapping = {
            1: "",
            2: name,
            3: phone,
            4: address,
            5: product,
            6: qty,
            7: memo,
            8: JBT_SENDER_NAME,
            9: "010-5700-7756",
            10: order_no,
        }

        for col, value in mapping.items():
            cell = ws.cell(row=out_row, column=col, value=value)
            cell.font = data_font
            cell.border = thin_border

    ws.auto_filter.ref = f"A1:K{len(filtered_rows) + 1}"

    output = BytesIO()
    wb.save(output)
    output.seek(0)

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
    filename = f"아이티소프트_{product_label}({now.strftime('%Y%m%d')}).xlsx"
    stats = {
        "total": len(filtered_rows),
        "sales_groups": [
            {"product": label, "options": list(options.values())}
            for label, options in sales_groups.items()
        ],
    }
    return output.read(), filename, stats


def process_outputs(
    delivery_file_bytes: bytes,
    toss_watermelon_entries: list[dict] | None = None,
) -> list[tuple[bytes, str, dict]]:
    dl_wb = load_workbook(filename=BytesIO(delivery_file_bytes), data_only=True)
    dl_ws = dl_wb.active
    toss_watermelon_entries = toss_watermelon_entries or []

    filtered_rows = []
    has_tomato = False
    has_chamoe = False
    has_ddureup = False
    has_watermelon = False
    has_corn = False

    for row in dl_ws.iter_rows(min_row=2):
        product_name = normalize(row[10].value) if len(row) > 10 else ""
        option = normalize(row[11].value) if len(row) > 11 else ""

        if "대저토마토" in product_name:
            has_tomato = True
            filtered_rows.append((row, "토마토"))
        elif "성주참외" in product_name:
            if not is_mixed_chamoe(product_name, option):
                has_chamoe = True
                filtered_rows.append((row, "참외"))
        elif "땅두릅" in product_name:
            has_ddureup = True
            filtered_rows.append((row, "땅두릅"))
        elif "수박" in product_name:
            # 수박 6kg/7kg/8kg은 모두 제이비티 발주로 보낸다.
            if delivery_watermelon_kg(product_name, option) in JBT_WATERMELON_KGS:
                has_watermelon = True
                filtered_rows.append((row, "수박"))
        elif is_jbt_corn_order(product_name, option):
            has_corn = True
            filtered_rows.append((row, "옥수수"))

    for entry in toss_watermelon_entries:
        has_watermelon = True
        filtered_rows.append((_virtual_toss_row(entry), "수박"))

    results: list[tuple[bytes, str, dict]] = []
    if filtered_rows:
        results.append(
            build_main_order_workbook(
                filtered_rows=filtered_rows,
                has_tomato=has_tomato,
                has_chamoe=has_chamoe,
                has_ddureup=has_ddureup,
                has_watermelon=has_watermelon,
                has_corn=has_corn,
            )
        )

    return results


def process(
    delivery_file_bytes: bytes,
    toss_watermelon_entries: list[dict] | None = None,
) -> tuple[bytes, str, dict]:
    results = process_outputs(delivery_file_bytes, toss_watermelon_entries=toss_watermelon_entries)
    if not results:
        raise ValueError("제이비티 발주로 출력할 대저토마토·성주참외(중소/로얄)·남해땅두릅·수박 주문을 찾지 못했습니다.")
    return results[0]
