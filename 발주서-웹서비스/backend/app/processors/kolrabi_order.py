import re
from datetime import datetime, timezone, timedelta
from io import BytesIO
from copy import copy

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


def convert_quantity(option_text: str) -> str | None:
    """Convert option like '3kg 1박스' to '콜라비 정품 3kg'."""
    if not option_text:
        return None
    text = str(option_text).strip()
    match = re.match(r"(\d+)kg\s+1박스", text)
    if match:
        weight = match.group(1)
        if weight in ("3", "5", "10"):
            return f"콜라비 정품 {weight}kg"
    return None


def process(delivery_file_bytes: bytes) -> tuple[bytes, str, dict]:
    """Process delivery list for 콜라비 orders.

    Args:
        delivery_file_bytes: Raw bytes of the DeliveryList Excel file.

    Returns:
        Tuple of (output_bytes, filename, stats_dict).
    """
    # Load delivery list
    dl_wb = load_workbook(filename=BytesIO(delivery_file_bytes), data_only=True)
    dl_ws = dl_wb.active

    # Filter rows where column K (11) contains '콜라비' and option is valid
    filtered_rows = []
    for row in dl_ws.iter_rows(min_row=2):
        k_val = normalize(row[10].value) if len(row) > 10 else ""  # Column K = index 10
        option = str(row[11].value).strip() if len(row) > 11 and row[11].value else ""
        if "콜라비" in k_val and convert_quantity(option) is not None:
            filtered_rows.append(row)

    # Load template
    template_path = TEMPLATE_DIR / "콜라비_제주다팜_원본.xlsx"
    if not template_path.exists():
        raise FileNotFoundError(
            f"Template not found: {template_path}. "
            f"Please place the template file in the templates directory."
        )

    tmpl_wb = load_workbook(filename=str(template_path))
    # Keep only first sheet
    first_sheet_name = tmpl_wb.sheetnames[0]
    for name in tmpl_wb.sheetnames[1:]:
        del tmpl_wb[name]
    ws = tmpl_wb[first_sheet_name]

    font11 = Font(size=11)

    # Find first empty row in template (look at column B for name)
    start_row = 2
    for r in range(2, ws.max_row + 2):
        if ws.cell(row=r, column=2).value is None:
            start_row = r
            break

    for i, row in enumerate(filtered_rows):
        out_row = start_row + i

        # Column mappings (source 0-indexed):
        # AA=26 -> B(2) name
        # AB=27 -> C(3) phone
        # AD=29 -> F(6) address
        # L=11  -> H(8) product (converted)
        # W=22  -> I(9) quantity
        # AE=30 -> M(13) memo
        # AC=28 -> E(5) zipcode

        name = normalize(row[26].value) if len(row) > 26 else ""
        phone = normalize(row[27].value) if len(row) > 27 else ""
        zipcode = normalize(row[28].value) if len(row) > 28 else ""
        address = normalize(row[29].value) if len(row) > 29 else ""
        memo = normalize(row[30].value) if len(row) > 30 else ""
        option = normalize(row[11].value) if len(row) > 11 else ""
        qty_val = row[22].value if len(row) > 22 else ""
        qty = normalize(qty_val)

        product = convert_quantity(option)

        # Zipcode with zero-fill to 5 digits
        if zipcode:
            try:
                zipcode = str(int(float(zipcode))).zfill(5)
            except (ValueError, TypeError):
                zipcode = zipcode.zfill(5)

        mapping = {
            2: name,       # B - name
            3: phone,      # C - phone
            5: zipcode,    # E - zipcode
            6: address,    # F - address
            8: product,    # H - product
            9: qty,        # I - quantity
            10: "식품애착",  # J - fixed
            11: "010-5700-7756",  # K - fixed
            13: memo,      # M - memo
        }

        for col, value in mapping.items():
            cell = ws.cell(row=out_row, column=col, value=value)
            cell.font = font11

    # Save to bytes
    output = BytesIO()
    tmpl_wb.save(output)
    output.seek(0)

    now = datetime.now(KST)
    filename = f"제주다팜_아이티소프트_콜라비발주({now.strftime('%Y%m%d')}).xlsx"
    stats = {"total": len(filtered_rows)}

    return output.read(), filename, stats
