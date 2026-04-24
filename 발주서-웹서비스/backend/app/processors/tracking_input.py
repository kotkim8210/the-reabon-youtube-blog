import re
from datetime import datetime, timezone, timedelta
from io import BytesIO

from openpyxl import load_workbook
from openpyxl.styles import Font

from app.config import TEMPLATE_DIR


KST = timezone(timedelta(hours=9))


def normalize(value) -> str:
    """공백 완전 제거 후 문자열 반환 (이름 매칭용)"""
    if value is None:
        return ""
    return re.sub(r'\s+', '', str(value).strip())


def process(
    orderlist_bytes: bytes,
    delivery_bytes: bytes,
) -> tuple[bytes, str, dict]:
    """Input tracking numbers from orderlist into DeliveryList.

    Args:
        orderlist_bytes: Raw bytes of the order list Excel file.
            Columns: K=name, M=phone, O=address, R=tracking
        delivery_bytes: Raw bytes of the DeliveryList Excel file.
            Columns: AA=name, AB=phone, AD=address, E=tracking (to fill)

    Returns:
        Tuple of (output_bytes, filename, stats_dict).
    """
    # Load orderlist
    ol_wb = load_workbook(filename=BytesIO(orderlist_bytes), data_only=True)
    ol_ws = ol_wb.active

    # Build list of order entries: (name, phone, address, tracking)
    order_entries = []
    for row in ol_ws.iter_rows(min_row=2):
        name = normalize(row[10].value) if len(row) > 10 else ""     # K = index 10
        phone = normalize(row[12].value) if len(row) > 12 else ""    # M = index 12
        address = normalize(row[14].value) if len(row) > 14 else ""  # O = index 14
        tracking = normalize(row[17].value) if len(row) > 17 else "" # R = index 17

        if name and tracking:
            order_entries.append({
                "name": name,
                "phone": phone,
                "address": address,
                "tracking": tracking,
            })

    # Load DeliveryList
    dl_wb = load_workbook(filename=BytesIO(delivery_bytes))
    dl_ws = dl_wb.active

    # Keep only first sheet
    first_sheet_name = dl_wb.sheetnames[0]
    for sheet_name in dl_wb.sheetnames[1:]:
        del dl_wb[sheet_name]
    dl_ws = dl_wb[first_sheet_name]

    filled = 0
    skipped = 0

    # Build index of order entries by name for faster lookup
    from collections import defaultdict
    order_by_name = defaultdict(list)
    for entry in order_entries:
        order_by_name[entry["name"]].append(entry)

    # Track which order entries have been used
    used_entries = set()

    for row_idx in range(2, dl_ws.max_row + 1):
        # Column E = 5 (tracking number destination)
        e_cell = dl_ws.cell(row=row_idx, column=5)

        # Only fill empty E cells
        if e_cell.value is not None and normalize(e_cell.value) != "":
            continue

        # Get delivery list data
        dl_name = normalize(dl_ws.cell(row=row_idx, column=27).value)     # AA
        dl_phone = normalize(dl_ws.cell(row=row_idx, column=28).value)    # AB
        dl_address = normalize(dl_ws.cell(row=row_idx, column=30).value)  # AD

        if not dl_name:
            continue

        candidates = order_by_name.get(dl_name, [])

        # 폴백: 이름 잘림(쿠팡 열폭 제한 등) 대응 - 접두어 매칭
        if not candidates:
            MIN_PREFIX_LEN = 8
            for order_name, entries in order_by_name.items():
                if len(order_name) < MIN_PREFIX_LEN:
                    continue
                if dl_name.startswith(order_name) or order_name.startswith(dl_name):
                    candidates = entries
                    break

        if not candidates:
            skipped += 1
            continue

        # Filter out already used entries
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

        # Fall back to first available with same name
        if matched is None:
            matched = available[0][1]

        if matched:
            e_cell.value = matched["tracking"]
            used_entries.add(id(matched))
            filled += 1
        else:
            skipped += 1

    # Save to bytes
    output = BytesIO()
    dl_wb.save(output)
    output.seek(0)

    now = datetime.now(KST)
    filename = f"DeliveryList_운송장입력완료_{now.strftime('%Y%m%d')}.xlsx"
    stats = {"filled": filled, "skipped": skipped}

    return output.read(), filename, stats
