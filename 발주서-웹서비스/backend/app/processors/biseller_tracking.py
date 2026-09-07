"""비셀러(LA한입갈비) 운송장번호 입력 — 2026-09-07 신규.

비셀러는 우리가 보낸 발주 양식에 L열 택배사·M열 송장번호를 채워 회신한다.
그 회신 파일(하루에 여러 장일 수 있음)을 쿠팡 DeliveryList와 매칭해
D열 택배사·E열 운송장번호를 채운다.
"""

import logging
import re
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from io import BytesIO

from openpyxl import load_workbook

from app.processors.tracking_match import coupang_courier_name

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


def normalize(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", "", str(value).strip())


def phone_digits(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\D", "", str(value))


def _tracking_text(value) -> str:
    """송장번호 셀 → 숫자 문자열. 엑셀이 숫자로 저장한 '411722399325.0'도 처리."""
    if value is None:
        return ""
    text = str(value).strip()
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    digits = re.sub(r"\D", "", text)
    return digits if len(digits) >= 8 else ""


def _reply_columns(ws) -> dict[str, int]:
    """비셀러 발주 양식 헤더에서 열 위치를 찾는다(열 순서가 바뀌어도 동작)."""
    found: dict[str, int] = {}
    for col in range(1, ws.max_column + 1):
        header = normalize(ws.cell(row=1, column=col).value)
        if not header:
            continue
        if "수취인명" in header or header == "수취인":
            found.setdefault("name", col)
        elif "수취인연락처" in header or "연락처" in header and "주문자" not in header:
            found.setdefault("phone", col)
        elif "주소" in header:
            found.setdefault("address", col)
        elif "상품명" in header:
            found.setdefault("product", col)
        elif "택배사" in header:
            found.setdefault("courier", col)
        elif "송장번호" in header or "운송장번호" in header:
            found.setdefault("tracking", col)
    return found


def parse_reply(reply_bytes: bytes) -> list[dict]:
    """비셀러 회신 파일 → [{name, phone, address, courier, tracking}]"""
    ws = load_workbook(filename=BytesIO(reply_bytes), data_only=True).active
    cols = _reply_columns(ws)
    if "name" not in cols or "tracking" not in cols:
        raise ValueError(
            "비셀러 회신 파일이 아닙니다. 발주 양식에 택배사·송장번호가 채워진 파일을 올려주세요. "
            "(감지된 열: "
            + ", ".join(str(ws.cell(row=1, column=c).value) for c in range(1, min(ws.max_column, 8) + 1))
            + ")"
        )

    entries: list[dict] = []
    for row_idx in range(2, ws.max_row + 1):
        name = normalize(ws.cell(row=row_idx, column=cols["name"]).value)
        tracking = _tracking_text(ws.cell(row=row_idx, column=cols["tracking"]).value)
        if not name or not tracking:
            continue
        entries.append({
            "name": name,
            "phone": phone_digits(ws.cell(row=row_idx, column=cols["phone"]).value) if "phone" in cols else "",
            "address": normalize(ws.cell(row=row_idx, column=cols["address"]).value) if "address" in cols else "",
            "courier": str(ws.cell(row=row_idx, column=cols["courier"]).value or "").strip() if "courier" in cols else "",
            "tracking": tracking,
        })
    return entries


def _require_delivery_list(ws) -> None:
    """DeliveryList 칸에 쿠팡 DeliveryList가 맞는지 확인(회신 파일 오업로드 방지)."""
    headers = {normalize(ws.cell(row=1, column=col).value) for col in range(1, min(ws.max_column, 41) + 1)}
    if {"주문번호", "운송장번호"} <= headers and ("수취인이름" in headers or ws.max_column >= 30):
        return
    raise ValueError(
        "DeliveryList 칸에 쿠팡 DeliveryList가 아닌 파일이 올라왔습니다. "
        "(감지된 열: " + ", ".join(sorted(h for h in headers if h)[:5]) + ") "
        "비셀러 회신 파일은 위쪽 칸에, 쿠팡에서 받은 DeliveryList는 아래 칸에 올려주세요."
    )


def process(
    delivery_bytes: bytes,
    reply_files: list[bytes] | None = None,
) -> tuple[bytes, str, dict]:
    """비셀러 회신 파일(들) → DeliveryList D열 택배사 / E열 운송장번호 입력."""
    entries: list[dict] = []
    for reply in (reply_files or []):
        if reply:
            entries.extend(parse_reply(reply))
    if not entries:
        raise ValueError("비셀러 회신 파일에서 송장번호를 찾을 수 없습니다.")

    dl_wb = load_workbook(filename=BytesIO(delivery_bytes))
    first_sheet = dl_wb.sheetnames[0]
    for sheet in dl_wb.sheetnames[1:]:
        del dl_wb[sheet]
    dl_ws = dl_wb[first_sheet]
    _require_delivery_list(dl_ws)

    # DeliveryList: 이름 → 행 목록(E열이 빈 행만 대상)
    dl_rows: dict[str, list[dict]] = defaultdict(list)
    for row_idx in range(2, dl_ws.max_row + 1):
        name = normalize(dl_ws.cell(row=row_idx, column=27).value)   # AA 수취인이름
        if not name:
            continue
        dl_rows[name].append({
            "row": row_idx,
            "phone": phone_digits(dl_ws.cell(row=row_idx, column=28).value),   # AB
            "address": normalize(dl_ws.cell(row=row_idx, column=30).value),    # AD
        })

    filled = 0
    skipped_details: list[str] = []
    used_rows: set[int] = set()

    for entry in entries:
        candidates = [c for c in dl_rows.get(entry["name"], []) if c["row"] not in used_rows]
        if not candidates:
            skipped_details.append(f"{entry['name']}({entry['tracking']}) — DeliveryList에 없음")
            continue
        if len(candidates) > 1:
            # 동명이인: 안심번호 숫자 → 주소 앞부분 순으로 좁힌다
            narrowed = [c for c in candidates if entry["phone"] and c["phone"] == entry["phone"]]
            if not narrowed and entry["address"]:
                narrowed = [c for c in candidates if c["address"][:12] and c["address"][:12] in entry["address"]]
            if len(narrowed) == 1:
                candidates = narrowed
            elif narrowed:
                candidates = narrowed
            else:
                skipped_details.append(f"{entry['name']}({entry['tracking']}) — 동명이인 구분 불가, 수동 확인")
                continue

        target = candidates[0]
        dl_ws.cell(row=target["row"], column=4, value=coupang_courier_name(entry["courier"], "롯데택배"))
        dl_ws.cell(row=target["row"], column=5, value=entry["tracking"])
        used_rows.add(target["row"])
        filled += 1

    if skipped_details:
        logger.warning("비셀러 운송장 미입력 %d건: %s", len(skipped_details), "; ".join(skipped_details))

    output = BytesIO()
    dl_wb.save(output)
    output.seek(0)

    now = datetime.now(KST)
    filename = f"DeliveryList_비셀러_운송장입력완료_{now.strftime('%Y%m%d')}.xlsx"
    stats = {
        "filled": filled,
        "skipped": len(skipped_details),
        "회신 건수": len(entries),
    }
    if skipped_details:
        stats["needs_check"] = skipped_details
    return output.read(), filename, stats
