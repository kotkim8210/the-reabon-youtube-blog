import re
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from io import BytesIO

from openpyxl import load_workbook


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

    # 같은 이름이 게걸무 파일에 여러 번 나올 수도 있음 → 리스트로 저장
    src_data: dict[str, list[str]] = defaultdict(list)
    for row in src_ws.iter_rows(min_row=2):
        tracking = normalize(row[1].value) if len(row) > 1 else ""  # B열
        name = normalize(row[2].value) if len(row) > 2 else ""       # C열
        if name and tracking:
            src_data[name].append(tracking)

    dl_wb = load_workbook(filename=BytesIO(delivery_bytes))
    first_sheet = dl_wb.sheetnames[0]
    for s in dl_wb.sheetnames[1:]:
        del dl_wb[s]
    dl_ws = dl_wb[first_sheet]

    # DeliveryList: 이름 → [(row, 주소), ...]
    dl_name_entries: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for row_idx in range(2, dl_ws.max_row + 1):
        name = normalize(dl_ws.cell(row=row_idx, column=27).value)
        address = normalize(dl_ws.cell(row=row_idx, column=30).value)
        if name:
            dl_name_entries[name].append((row_idx, address))

    filled = 0
    skipped = 0
    warnings: list[str] = []

    for src_name, tracking_list in src_data.items():
        if src_name not in dl_name_entries:
            warnings.append(f"미매칭: '{src_name}' - DeliveryList에 없음")
            skipped += 1
            continue

        dl_entries = dl_name_entries[src_name]

        if len(dl_entries) == 1:
            # 단일 매칭
            target_row = dl_entries[0][0]
            e_cell = dl_ws.cell(row=target_row, column=5)
            if e_cell.value is None or normalize(e_cell.value) == "":
                e_cell.value = tracking_list[0]
                filled += 1
        else:
            # 동명이인: 주소 확인
            unique_addresses = set(addr for _, addr in dl_entries if addr)
            all_same_address = len(unique_addresses) <= 1

            if all_same_address:
                # 주소 동일 → 순차적으로 운송장 입력
                for i, (row_idx, _) in enumerate(dl_entries):
                    e_cell = dl_ws.cell(row=row_idx, column=5)
                    if e_cell.value is not None and normalize(e_cell.value) != "":
                        continue
                    # 게걸무 파일에 운송장이 여러 개면 순차, 1개면 동일 운송장 복사
                    tracking = tracking_list[i] if i < len(tracking_list) else tracking_list[0]
                    e_cell.value = tracking
                    filled += 1
            else:
                # 주소 다름 → 수동 처리
                rows = [r for r, _ in dl_entries]
                warnings.append(
                    f"동명이인 주소 다름: '{src_name}' ({rows}행) - 수동 처리 필요"
                )
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
