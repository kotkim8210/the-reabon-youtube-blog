import re
from datetime import datetime, timezone, timedelta
from io import BytesIO

from openpyxl import load_workbook
from openpyxl.styles import Font

from app.config import TEMPLATE_DIR


KST = timezone(timedelta(hours=9))


def normalize(value) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _combined_text(product_name: object, option_text: object) -> str:
    return normalize(f"{product_name or ''} {option_text or ''}")


def is_apple_corn_order(product_name: object, option_text: object) -> bool:
    text = _combined_text(product_name, option_text)
    return "애플초당옥수수" in text or ("애플" in text and "초당옥수수" in text)


def _apple_corn_option(product_name: object, option_text: object) -> str | None:
    text = _combined_text(product_name, option_text)
    if not is_apple_corn_order(product_name, option_text):
        return None

    count_match = re.search(r"(\d+)\s*(?:개|입)", text)
    if not count_match:
        return None
    count = count_match.group(1)
    if count not in ("5", "10", "15", "20"):
        return None
    return f"애플초당옥수수(특품) {count}개"


def convert_option(option_text: str, product_name: str = "") -> str | None:
    """Convert DeliveryList option text to the vendor-facing product name."""
    apple_corn = _apple_corn_option(product_name, option_text)
    if apple_corn:
        return apple_corn

    text = str(option_text).strip()
    if not text:
        return None
    match = re.match(r"(\d+(?:kg|g))\s+1박스", text, re.IGNORECASE)
    if match:
        weight = match.group(1)
        return f"명이나물 {weight}"
    return text


def process(delivery_file_bytes: bytes) -> tuple[bytes, str, dict]:
    """Process delivery list for 쥬얼리프룻 명이나물 orders.

    Args:
        delivery_file_bytes: Raw bytes of the DeliveryList Excel file.

    Returns:
        Tuple of (output_bytes, filename, stats_dict).
    """
    dl_wb = load_workbook(filename=BytesIO(delivery_file_bytes), data_only=True)
    dl_ws = dl_wb.active

    filtered_rows = []
    has_myeongi = False
    has_apple_corn = False
    for row in dl_ws.iter_rows(min_row=2):
        k_val = normalize(row[10].value) if len(row) > 10 else ""
        option = normalize(row[11].value) if len(row) > 11 else ""
        if "명이나물" in k_val:
            filtered_rows.append(row)
            has_myeongi = True
        elif is_apple_corn_order(k_val, option):
            filtered_rows.append(row)
            has_apple_corn = True

    template_path = TEMPLATE_DIR / "명이나물_pbfcompany_원본.xlsx"
    if not template_path.exists():
        raise FileNotFoundError(
            f"Template not found: {template_path}. "
            f"Please place the template file in the templates directory."
        )

    tmpl_wb = load_workbook(filename=str(template_path))
    first_sheet_name = tmpl_wb.sheetnames[0]
    for name in tmpl_wb.sheetnames[1:]:
        del tmpl_wb[name]
    ws = tmpl_wb[first_sheet_name]

    font11 = Font(size=11)
    now = datetime.now(KST)
    today_str = now.strftime("%Y-%m-%d")

    start_row = 2
    for r in range(2, ws.max_row + 2):
        if ws.cell(row=r, column=3).value is None:
            start_row = r
            break

    option_totals: dict[str, dict] = {}

    for i, row in enumerate(filtered_rows):
        out_row = start_row + i

        name = normalize(row[26].value) if len(row) > 26 else ""
        phone = normalize(row[27].value) if len(row) > 27 else ""
        address = normalize(row[29].value) if len(row) > 29 else ""
        memo = normalize(row[30].value) if len(row) > 30 else ""
        option = normalize(row[11].value) if len(row) > 11 else ""
        qty_val = row[22].value if len(row) > 22 else ""
        qty = normalize(qty_val)
        order_no = normalize(row[2].value) if len(row) > 2 else ""

        product_name = normalize(row[10].value) if len(row) > 10 else ""
        product = convert_option(option, product_name)
        try:
            qty_int = int(float(qty_val)) if qty_val not in (None, "") else 1
        except (ValueError, TypeError):
            qty_int = 1

        mapping = {
            1: today_str,           # A - 일자
            2: "아이티소프트",       # B - 거래처명
            3: name,                # C - 받는분성명
            4: phone,               # D - 받는분전화번호
            # 5: "",                # E - 받는분기타연락처 (비워두기)
            6: address,             # F - 받는분주소 (우편번호 제외)
            7: product,             # G - 품목명
            8: qty,                 # H - 수량
            9: "식품애착",           # I - 보내는분성명
            10: "010-5700-7756",    # J - 보내는분전화번호
            # 11: "",              # K - 보내는분주소 (비워두기)
            12: memo,               # L - 배송메시지
            13: order_no,           # M - 주문번호
        }

        for col, value in mapping.items():
            cell = ws.cell(row=out_row, column=col, value=value)
            cell.font = font11

        bucket = option_totals.setdefault(
            option or product or "명이나물",
            {
                "coupang_option_keyword": option or product or "쥬얼리프룻",
                "vendor_option_name": product or "쥬얼리프룻",
                "quantity": 0,
                "orders": [],
            },
        )
        bucket["quantity"] += qty_int
        if order_no:
            bucket["orders"].append({"order_id": order_no, "quantity": qty_int})

    output = BytesIO()
    tmpl_wb.save(output)
    output.seek(0)

    product_parts = []
    if has_myeongi:
        product_parts.append("명이나물")
    if has_apple_corn:
        product_parts.append("애플초당옥수수")
    product_label = "_".join(product_parts)
    product_name = "+".join(product_parts) if product_parts else "쥬얼리프룻"
    if product_label:
        filename = f"쥬얼리프룻_{product_label}_발주({now.strftime('%Y%m%d')}).xlsx"
    else:
        filename = f"쥬얼리프룻_발주({now.strftime('%Y%m%d')}).xlsx"
    stats = {
        "total": len(filtered_rows),
        "product": product_name,
        "options": list(option_totals.values()),
    }

    return output.read(), filename, stats
