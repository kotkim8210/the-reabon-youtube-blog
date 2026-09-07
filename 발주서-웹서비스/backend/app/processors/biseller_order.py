"""비셀러 발주서 생성 (LA한입갈비) — 2026-09 신규.

쿠팡 DeliveryList에서 '한입 LA갈비' 주문을 뽑아 비셀러 발주 양식으로 채운다.
비셀러 상품명은 800g 낱개 개수를 그대로 풀어 쓴 표기다.
  쿠팡 '800g 4개' → '양념LA한입갈비 800g+800g+800g+800g (800G*4세트)'
"""

import logging
import re
from datetime import datetime, timezone, timedelta
from io import BytesIO

from openpyxl import load_workbook
from openpyxl.styles import Font

from app.config import TEMPLATE_DIR

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

TEMPLATE_NAME = "비셀러_발주서_원본.xlsx"
# 발주서에 고정으로 들어가는 보내는 사람(주문자) 정보 — 양식 J·K열.
SENDER_NAME = "(주)아이티소프트"
SENDER_PHONE = "010-5700-7756"
PRODUCT_LABEL = "LA한입갈비(비셀러)"


def normalize(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def _compact(*values: object) -> str:
    return re.sub(r"\s+", "", " ".join(normalize(v) for v in values))


def is_biseller_galbi_order(product_name: object, option_text: object) -> bool:
    """비셀러 발주 대상(LA한입갈비) 여부."""
    text = _compact(product_name, option_text)
    if "갈비" not in text:
        return False
    return "한입" in text or "LA갈비" in text.upper()


# 수량 단위 표기: 쿠팡 옵션은 '800g 4개', 라이브 이벤트 경품은 'LA한입갈비 800g 1팩'.
_COUNT_UNITS = r"(?:개입|개|팩|세트|봉지|봉|박스)"


def _galbi_count(text: str) -> int | None:
    """비셀러 갈비 표기에서 800g 낱개 개수를 읽는다. 못 읽으면 None."""
    match = (
        re.search(r"800g\s*(\d+)\s*" + _COUNT_UNITS, text, re.IGNORECASE)
        or re.search(r"(\d+)\s*" + _COUNT_UNITS + r"\s*800g", text, re.IGNORECASE)
        or re.search(r"(\d+)\s*" + _COUNT_UNITS, text)
    )
    if not match:
        return None
    count = int(match.group(1))
    return count if count >= 1 else None


def convert_galbi_option(
    product_name: object,
    option_text: object,
    *,
    promote_single: bool = False,
) -> str | None:
    """쿠팡 옵션·이벤트 경품명 → 비셀러 상품명. 개수를 못 읽으면 None.

    promote_single: 1팩짜리를 2세트로 올린다. 비셀러에 1세트 상품이 없어
        라이브 이벤트 당첨자(경품 'LA한입갈비 800g 1팩')는 2세트로 발주한다
        (2026-09-07 사용자 지시). 쿠팡 주문 경로는 그대로 둔다.
    """
    if not is_biseller_galbi_order(product_name, option_text):
        return None
    count = _galbi_count(_compact(product_name, option_text))
    if not count:
        return None
    if promote_single and count == 1:
        count = 2
    return f"양념LA한입갈비 {'+'.join(['800g'] * count)} (800G*{count}세트)"


def _find_total_row(ws) -> int:
    """'합계' 행 번호. 못 찾으면 마지막 행 다음."""
    for r in range(2, ws.max_row + 1):
        if normalize(ws.cell(row=r, column=7).value) == "합계":
            return r
    return ws.max_row + 1


def _entries_from_delivery(delivery_file_bytes: bytes) -> tuple[list[dict], list[str]]:
    """쿠팡 DeliveryList → 발주 행 목록. 갈비 주문인데 개수를 못 읽으면 미매칭으로 보고."""
    dl_ws = load_workbook(filename=BytesIO(delivery_file_bytes), data_only=True).active

    entries: list[dict] = []
    unmatched: list[str] = []
    for row in dl_ws.iter_rows(min_row=2):
        product_name = normalize(row[10].value) if len(row) > 10 else ""
        option = normalize(row[11].value) if len(row) > 11 else ""
        converted = convert_galbi_option(product_name, option)
        recipient = normalize(row[26].value) if len(row) > 26 else ""
        if not converted:
            if is_biseller_galbi_order(product_name, option):
                unmatched.append(f"{recipient or '이름없음'}({option or product_name}) — 수량 표기를 못 읽음")
            continue

        qty_val = row[22].value if len(row) > 22 else ""
        try:
            qty_int = int(float(qty_val)) if qty_val not in (None, "") else 1
        except (ValueError, TypeError):
            qty_int = 1

        zipcode = normalize(row[28].value) if len(row) > 28 else ""
        if zipcode:
            try:
                zipcode = str(int(float(zipcode))).zfill(5)
            except (ValueError, TypeError):
                pass

        entries.append({
            "name": recipient,
            "phone": normalize(row[27].value) if len(row) > 27 else "",
            "zipcode": zipcode,
            "address": normalize(row[29].value) if len(row) > 29 else "",
            "memo": normalize(row[30].value) if len(row) > 30 else "",
            "product": converted,
            "qty": qty_int,
            "order_no": normalize(row[2].value) if len(row) > 2 else "",
            "source_option": option or product_name,
        })
    return entries, unmatched


def _entries_from_winners(winners_bytes: bytes) -> tuple[list[dict], list[str]]:
    """라이브 이벤트 당첨자 CSV → 발주 행 목록.

    당첨자 CSV 파싱(환불 제외·개인정보 미기재 표기)은 event_order.parse_winners를 그대로 쓴다.
    비셀러 품목(LA한입갈비)이 아닌 경품은 다른 발주처 몫이라 needs_check로 알린다.
    """
    from app.processors.event_order import parse_winners

    winners = parse_winners(winners_bytes)
    entries: list[dict] = []
    notes: list[str] = []
    for winner in winners:
        prize = normalize(winner.get("product"))
        converted = convert_galbi_option(prize, "", promote_single=True)
        if not converted:
            notes.append(f"{winner.get('name') or '이름없음'}({prize or '경품미상'}) — 비셀러 발주 품목이 아님")
            continue
        entries.append({
            "name": normalize(winner.get("name")),
            "phone": normalize(winner.get("phone")),
            "zipcode": "",   # 당첨자 CSV에는 우편번호가 없다
            "address": normalize(winner.get("address")),
            "memo": normalize(winner.get("memo")) or "문 앞",
            "product": converted,
            "qty": 1,
            "order_no": normalize(winner.get("order_id")),
            "source_option": prize,
        })

    if winners:
        last = winners[-1]
        skipped_refund = int(last.get("_skipped_refund") or 0)
        if skipped_refund:
            notes.append(f"환불/취소 {skipped_refund}건 제외")
        notes.extend(last.get("_incomplete") or [])
    return entries, notes


def _drop_issued_winners(
    event_entries: list[dict],
    issued_keys: set[str],
    duplicate_names: list[str] | None = None,
) -> tuple[list[dict], int]:
    """이미 발주된 당첨자(주문번호+경품명)를 걸러낸다 — 같은 CSV 재업로드 시 중복발주 방지."""
    from app.processors import issued_orders

    wrapped = [
        {"order_id": e["order_no"], "option": e["source_option"], "name": e["name"], "_entry": e}
        for e in event_entries
    ]
    kept, dropped = issued_orders.filter_entries_by_issued(
        wrapped, issued_keys, skipped_names=duplicate_names
    )
    return [item["_entry"] for item in kept], dropped


def process(
    delivery_file_bytes: bytes | None = None,
    winners_bytes: bytes | None = None,
    issued_keys: set[str] | None = None,
    duplicate_names: list[str] | None = None,
) -> tuple[bytes, str, dict]:
    """비셀러 발주서 생성.

    winners_bytes: 라이브 이벤트 당첨자 CSV(선택) — 쿠팡 주문 뒤에 이어붙여 한 장으로 낸다
        (2026-09-07 요청: 당첨자 명단도 같은 비셀러 양식으로).
    issued_keys: 이미 발주된 '주문번호|옵션' 키. 당첨자 CSV 쪽 중복발주를 막는다
        (DeliveryList 쪽은 main.py의 filter_delivery_by_issued가 미리 걸러낸다).
    """
    if not delivery_file_bytes and not winners_bytes:
        raise ValueError("DeliveryList 또는 라이브 이벤트 당첨자 CSV 중 하나는 올려야 합니다.")

    entries: list[dict] = []
    needs_check: list[str] = []
    coupang_count = 0
    event_count = 0
    event_duplicate_skipped = 0

    if delivery_file_bytes:
        dl_entries, unmatched = _entries_from_delivery(delivery_file_bytes)
        entries.extend(dl_entries)
        needs_check.extend(unmatched)
        coupang_count = len(dl_entries)

    if winners_bytes:
        event_entries, notes = _entries_from_winners(winners_bytes)
        if issued_keys:
            event_entries, event_duplicate_skipped = _drop_issued_winners(
                event_entries, issued_keys, duplicate_names
            )
        entries.extend(event_entries)
        needs_check.extend(notes)
        event_count = len(event_entries)

    if needs_check:
        logger.warning("비셀러 발주 확인필요 %d건: %s", len(needs_check), "; ".join(needs_check))

    template_path = TEMPLATE_DIR / TEMPLATE_NAME
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

    total_row = _find_total_row(ws)
    capacity = total_row - 2  # 데이터 행 수(2행 ~ 합계행 직전)
    if len(entries) > capacity:
        # 주문이 양식 칸보다 많으면 합계 행 앞에 행을 넣어 늘린다(수식은 아래에서 다시 씀).
        ws.insert_rows(total_row, len(entries) - capacity)
        total_row = _find_total_row(ws)

    font11 = Font(size=11)
    order_date = datetime.now(KST).strftime("%Y-%m-%d")

    option_totals: dict[str, dict] = {}
    for i, entry in enumerate(entries):
        out_row = 2 + i
        mapping = {
            1: i + 1,                  # A 순번
            2: order_date,             # B 발주일
            3: entry["name"],          # C 수취인명
            4: entry["phone"],         # D 수취인연락처
            5: entry["zipcode"],       # E 우편번호
            6: entry["address"],       # F 주소
            7: entry["product"],       # G 상품명(비셀러 상품명)
            8: entry["qty"],           # H 수량
            9: entry["memo"],          # I 배송메세지
            10: SENDER_NAME,           # J 주문자명
            11: SENDER_PHONE,          # K 주문자연락처
            # L 택배사 / M 송장번호는 거래처가 채운다
        }
        for col, value in mapping.items():
            cell = ws.cell(row=out_row, column=col, value=value)
            cell.font = font11

        key = entry["source_option"] or entry["product"]
        bucket = option_totals.setdefault(
            key,
            {
                "coupang_option_keyword": key,
                "vendor_option_name": entry["product"],
                "quantity": 0,
                "orders": [],
            },
        )
        bucket["quantity"] += entry["qty"]
        if entry["order_no"]:
            bucket["orders"].append({"order_id": entry["order_no"], "quantity": entry["qty"]})

    # 남는 빈 칸의 순번은 지우고, 합계 수식은 실제 데이터 범위로 다시 쓴다.
    for r in range(2 + len(entries), total_row):
        ws.cell(row=r, column=1, value=None)
    last_data_row = max(total_row - 1, 2)
    ws.cell(row=total_row, column=8, value=f"=SUM(H2:H{last_data_row})")

    output = BytesIO()
    tmpl_wb.save(output)
    output.seek(0)

    # 파일명은 거래처(리앤유커머스) 회신 파일과 같은 규칙 — 담당자가 바로 알아본다.
    # 예: 나은_260907_리앤유커머스(아이티소프트).xlsx
    filename = f"나은_{datetime.now(KST).strftime('%y%m%d')}_리앤유커머스(아이티소프트).xlsx"
    stats = {
        "total": len(entries),
        "product": PRODUCT_LABEL,
        "options": list(option_totals.values()),
    }
    if winners_bytes:
        stats["coupang"] = coupang_count
        stats["event"] = event_count
    if event_duplicate_skipped:
        stats["duplicate_skipped"] = event_duplicate_skipped
    if needs_check:
        stats["needs_check"] = needs_check

    return output.read(), filename, stats
