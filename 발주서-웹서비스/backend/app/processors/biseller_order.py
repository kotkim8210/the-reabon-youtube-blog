"""비셀러 발주서 생성 (LA한입갈비) — 2026-09 신규.

쿠팡 DeliveryList에서 '한입 LA갈비' 주문을 뽑아 비셀러 발주 양식으로 채운다.
비셀러 상품명은 800g 낱개 개수를 그대로 풀어 쓴 표기다.
  쿠팡 '800g 4개' → '양념LA한입갈비 800g+800g+800g+800g (800G*4세트)'

2026-09-15부터 양식이 메이크샵 "발주용 양식(대량주문 업로드)"으로 바뀌었다:
  1~3행 헤더(라벨/필드키/필수·읽기전용) · 4행부터 데이터 · 상품은 상품번호(goods_no)로 지정.
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

TEMPLATE_NAME = "비셀러_대량주문_원본.xlsx"   # 메이크샵 발주용 양식(2026-09-15)
DATA_START_ROW = 4                         # 1~3행은 헤더
# 발주서에 고정으로 들어가는 주문자 정보 — J·K열.
SENDER_NAME = "(주)아이티소프트"
SENDER_PHONE = "010-5700-7756"

# 비셀러 상품 카탈로그 — 세트 수 → 메이크샵 상품번호(goods_no). 업로드 필수값이라
# 여기 없는 세트 수는 발주서에 못 넣고 needs_check로 알린다.
# 출처: "엑셀 대량 주문 양식 order_list_2026-09-15" (상품번호·회원등급코드·판매가격).
BISELLER_CATALOG: dict[int, dict] = {
    2: {"goods_no": 6120, "code": "PL0006032", "price": 20480,
        "name": "양념LA한입갈비 800g+800g (800G*2세트)"},
    4: {"goods_no": 6121, "code": "PL0006033", "price": 37800,
        "name": "양념LA한입갈비 800g+800g+800g+800g (800G*4세트)"},
}
OPTION_SNO = 0            # 옵션 없는 상품 — 메이크샵 양식의 옵션번호 필수값
DELIVERY_CONDITION = "무료배송"
PRODUCT_LABEL = "LA한입갈비(비셀러)"
# 발주서 파일명에 쓰는 상품명(거래처 표기 없이 상품만)
ORDER_PRODUCT_NAME = "LA한입갈비"


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
    count = galbi_set_count(product_name, option_text, promote_single=promote_single)
    if not count:
        return None
    return f"양념LA한입갈비 {'+'.join(['800g'] * count)} (800G*{count}세트)"


def galbi_set_count(product_name: object, option_text: object, *, promote_single: bool = False) -> int | None:
    """쿠팡 옵션·경품명 → 800g 세트 수. 갈비가 아니거나 개수를 못 읽으면 None."""
    if not is_biseller_galbi_order(product_name, option_text):
        return None
    count = _galbi_count(_compact(product_name, option_text))
    if not count:
        return None
    if promote_single and count == 1:
        count = 2
    return count



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
            "sets": galbi_set_count(product_name, option),
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
            "sets": galbi_set_count(prize, "", promote_single=True),
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

    # 카탈로그(상품번호)에 없는 세트 수는 업로드 자체가 안 되므로 발주서에서 빼고 알린다.
    uploadable: list[dict] = []
    for entry in entries:
        if entry.get("sets") in BISELLER_CATALOG:
            uploadable.append(entry)
        else:
            needs_check.append(
                f"{entry['name'] or '이름없음'}({entry['source_option']}) — 비셀러 상품번호가 없는 세트 수({entry.get('sets')}세트)"
            )

    font11 = Font(size=11)
    option_totals: dict[str, dict] = {}
    for i, entry in enumerate(uploadable):
        out_row = DATA_START_ROW + i
        item = BISELLER_CATALOG[entry["sets"]]
        if not entry["zipcode"]:
            needs_check.append(f"{entry['name']} — 우편번호 없음(메이크샵 필수값). 업로드 전 N열에 직접 입력")
        mapping = {
            1: i + 1,                   # A 순서
            2: item["goods_no"],        # B 상품번호 (필수)
            3: item["code"],            # C 회원등급 상품코드
            4: item["name"],            # D 상품명
            5: OPTION_SNO,              # E 옵션번호 (필수)
            6: "",                      # F 옵션명
            7: DELIVERY_CONDITION,      # G 배송비조건
            8: item["price"],           # H 판매가격
            9: entry["qty"],            # I 수량 (필수)
            10: SENDER_NAME,            # J 주문자 성명 (필수)
            11: SENDER_PHONE,           # K 주문자 전화번호 (필수)
            12: entry["name"],          # L 수취인 성명 (필수)
            13: entry["phone"],         # M 수취인 전화번호 (필수)
            14: entry["zipcode"],       # N 우편번호 (필수)
            15: entry["address"],       # O 수취인 주소 (필수)
            16: entry["memo"],          # P 배송메시지
        }
        for col, value in mapping.items():
            cell = ws.cell(row=out_row, column=col, value=value)
            cell.font = font11

        key = entry["source_option"] or entry["product"]
        bucket = option_totals.setdefault(
            key,
            {
                "coupang_option_keyword": key,
                "vendor_option_name": item["name"],
                "quantity": 0,
                "orders": [],
            },
        )
        bucket["quantity"] += entry["qty"]
        if entry["order_no"]:
            bucket["orders"].append({"order_id": entry["order_no"], "quantity": entry["qty"]})
    output = BytesIO()
    tmpl_wb.save(output)
    output.seek(0)

    # 파일명은 상품명 + 날짜 (2026-09-09 사용자 요청). 예: LA한입갈비(20260909).xlsx
    filename = f"{ORDER_PRODUCT_NAME}({datetime.now(KST).strftime('%Y%m%d')}).xlsx"
    stats = {
        "total": len(uploadable),
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
