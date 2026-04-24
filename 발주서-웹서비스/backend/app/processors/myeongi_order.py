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


def convert_option(option_text: str) -> str | None:
    """Convert option like '1kg 1박스' to '명이나물 1kg'."""
    if not option_text:
        return None
    text = str(option_text).strip()
    match = re.match(r"(\d+(?:kg|g))\s+1박스", text, re.IGNORECASE)
    if match:
        weight = match.group(1)
        return f"명이나물 {weight}"
    return text


def process(delivery_file_bytes: bytes) -> tuple[bytes, str, dict]:
    """Process delivery list for 명이나물 orders.

    Args:
        delivery_file_bytes: Raw bytes of the DeliveryList Excel file.

    Returns:
        Tuple of (output_bytes, filename, stats_dict).
    """
    dl_wb = load_workbook(filename=BytesIO(delivery_file_bytes), data_only=True)
    dl_ws = dl_wb.active

    filtered_rows = []
    for row in dl_ws.iter_rows(min_row=2):
        k_val = normalize(row[10].value) if len(row) > 10 else ""
        if "명이나물" in k_val:
            filtered_rows.append(row)

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

        product = convert_option(option)

        mapping = {
            1: today_str,           # A - 일자
            2: "알제이시스템즈",     # B - 거래처명
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

    output = BytesIO()
    tmpl_wb.save(output)
    output.seek(0)

    filename = f"명이나물_발주({now.strftime('%Y%m%d')}).xlsx"
    stats = {"total": len(filtered_rows)}

    return output.read(), filename, stats
