import re
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from io import BytesIO

from openpyxl import load_workbook

from app.processors.tracking_match import option_key_set, options_match


KST = timezone(timedelta(hours=9))


def normalize(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", "", str(value).strip())


def process(
    tracking_bytes: bytes,
    delivery_bytes: bytes,
) -> tuple[bytes, str, dict]:
    """게걸무 택배발송 파일의 운송장번호를 DeliveryList에 매핑.

    택배발송 파일: B열=운송장번호, C열=수령인이름
    DeliveryList: AA열(col27)=수령인이름, AD열(col30)=수령지주소, E열(col5)=운송장번호 입력 대상

    동명이인 처리:
    - DeliveryList에 같은 이름 여러 행 + AD열 주소도 모두 동일 → 모든 행에 순차적으로 운송장 입력
    - 주소가 다르면 → 수동 처리 경고
    """
    src_wb = load_workbook(filename=BytesIO(tracking_bytes), data_only=True)
    src_ws = src_wb.active

    # 같은 이름이 게걸무 파일에 여러 번 나올 수도 있음 → 옵션/주소와 함께 리스트로 저장
    src_data: dict[str, list[dict]] = defaultdict(list)
    for row in src_ws.iter_rows(min_row=2):
        tracking = normalize(row[1].value) if len(row) > 1 else ""  # B열
        name = normalize(row[2].value) if len(row) > 2 else ""       # C열
        if name and tracking:
            src_data[name].append(
                {
                    "tracking": tracking,
                    "address": normalize(row[29].value) if len(row) > 29 else "",
                    "option_keys": option_key_set(row[11].value if len(row) > 11 else "")
                    or option_key_set(row[10].value if len(row) > 10 else ""),
                }
            )

    dl_wb = load_workbook(filename=BytesIO(delivery_bytes))
    first_sheet = dl_wb.sheetnames[0]
    for s in dl_wb.sheetnames[1:]:
        del dl_wb[s]
    dl_ws = dl_wb[first_sheet]

    # DeliveryList: 이름 → [{row, 주소, 옵션키}, ...]
    dl_name_entries: dict[str, list[dict]] = defaultdict(list)
    for row_idx in range(2, dl_ws.max_row + 1):
        name = normalize(dl_ws.cell(row=row_idx, column=27).value)
        address = normalize(dl_ws.cell(row=row_idx, column=30).value)
        if name:
            dl_name_entries[name].append(
                {
                    "row": row_idx,
                    "address": address,
                    "option_keys": option_key_set(dl_ws.cell(row=row_idx, column=12).value)
                    or option_key_set(dl_ws.cell(row=row_idx, column=11).value),
                }
            )

    filled = 0
    skipped = 0
    warnings: list[str] = []

    used_rows: set[int] = set()

    for src_name, tracking_entries in src_data.items():
        if src_name not in dl_name_entries:
            warnings.append(f"미매칭: '{src_name}' - DeliveryList에 없음")
            skipped += 1
            continue

        dl_entries = dl_name_entries[src_name]
        duplicate_guard = len(dl_entries) > 1 or len(tracking_entries) > 1

        for tracking_entry in tracking_entries:
            candidates = [entry for entry in dl_entries if entry["row"] not in used_rows]
            if duplicate_guard:
                candidates = [
                    entry for entry in candidates
                    if options_match(tracking_entry.get("option_keys"), entry.get("option_keys"))
                ]
                if not candidates:
                    warnings.append(f"동명이인 옵션 불일치: '{src_name}' - 수동 처리 필요")
                    skipped += 1
                    continue

            if tracking_entry.get("address"):
                address_matches = [
                    entry for entry in candidates
                    if entry["address"] == tracking_entry["address"]
                ]
                if address_matches:
                    candidates = address_matches

            if not candidates:
                skipped += 1
                continue

            target_row = candidates[0]["row"]
            e_cell = dl_ws.cell(row=target_row, column=5)
            if e_cell.value is None or normalize(e_cell.value) == "":
                dl_ws.cell(row=target_row, column=4).value = "롯데택배"
                e_cell.value = tracking_entry["tracking"]
                used_rows.add(target_row)
                filled += 1
            else:
                skipped += 1

    output = BytesIO()
    dl_wb.save(output)
    output.seek(0)

    now = datetime.now(KST)
    filename = f"DeliveryList_게걸무_운송장입력완료_{now.strftime('%Y%m%d')}.xlsx"
    stats: dict = {"filled": filled, "skipped": skipped}
    if warnings:
        stats["warnings"] = warnings

    return output.read(), filename, stats
