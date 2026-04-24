import re
from datetime import datetime, timedelta, timezone
from io import BytesIO

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.styles.colors import Color

from app.processors import chamoe_mixed_order


KST = timezone(timedelta(hours=9))
JBT_SENDER_NAME = "(주)아이티소프트"


def normalize(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def is_mixed_chamoe(product_name: str, option_text: str) -> bool:
    return "성주참외" in product_name and "가정용 혼합과" in option_text


def transform_product(option_text: str, product_type: str = "") -> str:
    text = normalize(option_text)

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
            grade = "S" if "2.5" in kg_str else "S-3S"
            result = f"대저짭짤이특품({grade})과{kg_str}"
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
    product_label = "_".join(parts) if parts else "발주"
    filename = f"아이티소프트_{product_label}({now.strftime('%Y%m%d')}).xlsx"
    stats = {"total": len(filtered_rows)}
    return output.read(), filename, stats


def process_outputs(delivery_file_bytes: bytes) -> list[tuple[bytes, str, dict]]:
    dl_wb = load_workbook(filename=BytesIO(delivery_file_bytes), data_only=True)
    dl_ws = dl_wb.active

    filtered_rows = []
    has_tomato = False
    has_chamoe = False
    has_ddureup = False

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

    mixed_result = chamoe_mixed_order.process(delivery_file_bytes)

    results: list[tuple[bytes, str, dict]] = []
    if filtered_rows or mixed_result is None:
        results.append(
            build_main_order_workbook(
                filtered_rows=filtered_rows,
                has_tomato=has_tomato,
                has_chamoe=has_chamoe,
                has_ddureup=has_ddureup,
            )
        )

    if mixed_result:
        results.append(mixed_result)

    return results


def process(delivery_file_bytes: bytes) -> tuple[bytes, str, dict]:
    return process_outputs(delivery_file_bytes)[0]
