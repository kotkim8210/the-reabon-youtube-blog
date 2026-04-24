import re
from datetime import datetime, timezone, timedelta
from io import BytesIO
from collections import defaultdict

from openpyxl import load_workbook

from app.config import TEMPLATE_DIR


KST = timezone(timedelta(hours=9))


def normalize(value) -> str:
    """공백 완전 제거 후 문자열 반환 (이름 매칭용)"""
    if value is None:
        return ""
    return re.sub(r'\s+', '', str(value).strip())


def normalize_courier(name: str) -> str:
    """택배사명 정규화 — 쿠팡이 인식하는 형태로 변환.

    예: 'CJ대한통운' -> 'CJ 대한통운' (띄어쓰기 필수)
    """
    if not name:
        return name
    s = str(name).strip()
    # 'CJ대한통운' → 'CJ 대한통운'
    s = re.sub(r'(?i)^CJ대한통운$', 'CJ 대한통운', s)
    return s


def is_mixed_chamoe_row(product_name: str, option_text: str) -> bool:
    return "성주참외" in product_name and "가정용 혼합과" in option_text


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
    # Load 대저토마토 회신 파일
    tr_wb = load_workbook(filename=BytesIO(tomato_reply_bytes), data_only=True)
    tr_ws = tr_wb.active

    # Extract entries from 회신 파일 (row 1 = header, data from row 2)
    tomato_entries = []
    for row_idx in range(2, tr_ws.max_row + 1):
        tracking = normalize(tr_ws.cell(row=row_idx, column=1).value)   # A
        name = normalize(tr_ws.cell(row=row_idx, column=2).value)       # B
        phone = normalize(tr_ws.cell(row=row_idx, column=3).value)      # C
        address = normalize(tr_ws.cell(row=row_idx, column=4).value)    # D
        courier_raw = tr_ws.cell(row=row_idx, column=11).value          # K (택배사)
        courier = str(courier_raw).strip() if courier_raw else ""

        if not name or not tracking:
            continue

        tomato_entries.append({
            "name": name,
            "phone": phone,
            "address": address,
            "tracking": tracking,
            "courier": courier,
        })

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

    for row_idx in range(2, dl_ws.max_row + 1):
        # Column E = 5 (tracking number destination)
        e_cell = dl_ws.cell(row=row_idx, column=5)

        # Only fill empty E cells
        if e_cell.value is not None and normalize(e_cell.value) != "":
            continue

        product_name = str(dl_ws.cell(row=row_idx, column=11).value or "")
        option_text = str(dl_ws.cell(row=row_idx, column=12).value or "")
        if is_mixed_chamoe_row(product_name, option_text):
            continue

        dl_name = normalize(dl_ws.cell(row=row_idx, column=27).value)     # AA
        dl_phone = normalize(dl_ws.cell(row=row_idx, column=28).value)    # AB
        dl_address = normalize(dl_ws.cell(row=row_idx, column=30).value)  # AD

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

            # K열(11) = 상품명 → 대저토마토/참외/땅두릅 판별
            if "토마토" in product_name:
                has_tomato = True
            if "참외" in product_name:
                has_chamoe = True
            if "땅두릅" in product_name:
                has_ddureup = True
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
    product_label = "_".join(parts) if parts else "발주"
    filename = f"송장파일_{product_label}({now.strftime('%Y%m%d')}).xlsx"
    stats = {
        "filled": filled,
        "skipped": skipped,
        "tomato_entries": len(tomato_entries),
    }

    return output.read(), filename, stats
