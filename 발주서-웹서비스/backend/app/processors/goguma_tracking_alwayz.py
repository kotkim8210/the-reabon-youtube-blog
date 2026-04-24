"""올웨이즈 주문 파일에 해달 발주서 운송장번호를 자동 입력.

Flow:
1. 해달 발주서에서 (이름, 전화, 주소, 운송장번호) 추출
2. 올웨이즈 주문 파일에서 빈 W열(운송장번호) 행 탐색
3. 이름/전화/주소 매칭으로 운송장번호를 W열에 입력, U열에 "한진택배" 입력
"""

import re
from datetime import datetime, timezone, timedelta
from io import BytesIO
from collections import defaultdict

from openpyxl import load_workbook


KST = timezone(timedelta(hours=9))


def normalize(value) -> str:
    if value is None:
        return ""
    return re.sub(r'\s+', '', str(value).strip())


def find_tracking_in_row(ws, row_idx) -> str:
    for col in range(16, 23):  # P(16) ~ V(22)
        val = ws.cell(row=row_idx, column=col).value
        if val is not None:
            s = str(val).strip()
            if re.match(r'^\d{10,14}$', s):
                return s
    return ""


def process(
    haedal_bytes: bytes,
    alwayz_bytes: bytes,
) -> tuple[bytes, str, dict]:
    """해달 발주서 운송장번호를 올웨이즈 주문 파일 W열에 입력.

    Args:
        haedal_bytes: 해달 발주서 Excel (A=이름, B=전화, F=주소, P~V=운송장번호)
        alwayz_bytes: 올웨이즈 주문내역 Excel (S=수령인, T=연락처, O=주소, W=운송장번호, U=택배사)

    Returns:
        (output_bytes, filename, stats)
    """
    # 해달 발주서 파싱
    hd_wb = load_workbook(filename=BytesIO(haedal_bytes), data_only=True)
    hd_ws = hd_wb.active

    start_row = 1
    a1_val = normalize(hd_ws.cell(row=1, column=1).value)
    if "받" in a1_val or "분" in a1_val or "수령" in a1_val:
        start_row = 2

    haedal_entries = []
    for row_idx in range(start_row, hd_ws.max_row + 1):
        name = normalize(hd_ws.cell(row=row_idx, column=1).value)
        phone = normalize(hd_ws.cell(row=row_idx, column=2).value)
        address = normalize(hd_ws.cell(row=row_idx, column=6).value)

        if not name:
            continue

        tracking = find_tracking_in_row(hd_ws, row_idx)
        if tracking:
            haedal_entries.append({
                "name": name,
                "phone": phone,
                "address": address,
                "tracking": tracking,
            })

    # 올웨이즈 파일 로드
    al_wb = load_workbook(filename=BytesIO(alwayz_bytes))
    al_ws = al_wb.active

    entry_by_name = defaultdict(list)
    for entry in haedal_entries:
        entry_by_name[entry["name"]].append(entry)

    used_entries = set()
    filled = 0
    skipped = 0

    for row_idx in range(2, al_ws.max_row + 1):
        # W열(23) = 운송장번호 대상
        w_cell = al_ws.cell(row=row_idx, column=23)

        if w_cell.value is not None and normalize(w_cell.value) != "":
            continue

        al_name = normalize(al_ws.cell(row=row_idx, column=19).value)     # S = 수령인
        al_phone = normalize(al_ws.cell(row=row_idx, column=20).value)    # T = 수령인 연락처
        al_address = normalize(al_ws.cell(row=row_idx, column=15).value)  # O = 주소

        if not al_name:
            continue

        candidates = entry_by_name.get(al_name, [])
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

        # 전화+주소 매칭
        for _, c in available:
            if c["phone"] == al_phone and c["address"] == al_address:
                matched = c
                break

        # 전화만
        if matched is None:
            for _, c in available:
                if c["phone"] == al_phone:
                    matched = c
                    break

        # 주소만
        if matched is None:
            for _, c in available:
                if c["address"] == al_address:
                    matched = c
                    break

        # 첫번째
        if matched is None:
            matched = available[0][1]

        if matched:
            w_cell.value = matched["tracking"]
            al_ws.cell(row=row_idx, column=21).value = "한진택배"  # U = 택배사
            used_entries.add(id(matched))
            filled += 1
        else:
            skipped += 1

    output = BytesIO()
    al_wb.save(output)
    output.seek(0)

    now = datetime.now(KST)
    filename = f"일상애착_주문 내역_{now.strftime('%Y-%m-%d')}.xlsx"
    stats = {
        "filled": filled,
        "skipped": skipped,
        "haedal_entries": len(haedal_entries),
    }

    return output.read(), filename, stats
