import re
from datetime import datetime, timezone, timedelta
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from openpyxl import load_workbook


KST = timezone(timedelta(hours=9))

HEADERS = ["주문번호", "수령인", "수령인연락처", "배송주소", "상품명", "옵션", "수량", "배송메모"]
COL_MAP = {
    "order_no": 3,    # C열 (1-indexed)
    "name": 27,       # AA열
    "phone": 28,      # AB열
    "address": 30,    # AD열
    "product": 11,    # K열
    "option": 12,     # L열
    "qty": 23,        # W열
    "memo": 31,       # AE열
}


def normalize(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def process(delivery_file_bytes: bytes) -> tuple[bytes, str, dict]:
    dl_wb = load_workbook(filename=BytesIO(delivery_file_bytes), data_only=True)
    dl_ws = dl_wb.active

    filtered_rows = []
    for row in dl_ws.iter_rows(min_row=2):
        product = normalize(row[COL_MAP["product"] - 1].value) if len(row) >= COL_MAP["product"] else ""
        if "게걸무" in product:
            filtered_rows.append(row)

    out_wb = Workbook()
    ws = out_wb.active
    ws.title = "게걸무발주"

    header_font = Font(bold=True, size=11)
    header_fill = PatternFill(start_color="E8F5E9", end_color="E8F5E9", fill_type="solid")
    for col, header in enumerate(HEADERS, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")

    for i, row in enumerate(filtered_rows, 2):
        def get(col_1indexed):
            idx = col_1indexed - 1
            return normalize(row[idx].value) if len(row) > idx else ""

        ws.cell(row=i, column=1, value=get(COL_MAP["order_no"]))
        ws.cell(row=i, column=2, value=get(COL_MAP["name"]))
        ws.cell(row=i, column=3, value=get(COL_MAP["phone"]))
        ws.cell(row=i, column=4, value=get(COL_MAP["address"]))
        ws.cell(row=i, column=5, value=get(COL_MAP["product"]))
        ws.cell(row=i, column=6, value=get(COL_MAP["option"]))
        ws.cell(row=i, column=7, value=get(COL_MAP["qty"]))
        ws.cell(row=i, column=8, value=get(COL_MAP["memo"]))

    col_widths = [18, 10, 16, 45, 30, 20, 6, 25]
    for col, width in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(col)].width = width

    output = BytesIO()
    out_wb.save(output)
    output.seek(0)

    now = datetime.now(KST)
    filename = f"게걸무씨앗기름_발주({now.strftime('%Y%m%d')}).xlsx"
    stats = {"total": len(filtered_rows)}

    return output.read(), filename, stats
