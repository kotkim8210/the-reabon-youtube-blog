"""Toss-only: 토스 주문 수집 → 해달 발주서 생성 + 토스 운송장 등록."""

import re
import logging
from hashlib import sha1
from datetime import datetime, timezone, timedelta
from io import BytesIO
from collections import defaultdict

import httpx
from openpyxl import load_workbook
from openpyxl.styles import Font

from app.config import TEMPLATE_DIR
from app.processors.tracking_match import (
    name_counts,
    option_key_set,
    options_match,
)
from app.processors.tracking_input import _match_tier
from app.processors.goguma_order import is_hobak_goguma_text
from app.processors.goguma_order import transform_toss_option as normalize_goguma_toss_option
from app.processors.haedal_tracking_parser import (
    detect_haedal_columns,
    find_courier_in_row,
    find_tracking_in_row,
)
from app.toss.client import toss_client

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))

GOGUMA_KEYWORDS = ["고구마", "꿀고구마"]
TOSS_DELIVERY_COMPANY = "한진택배"
TRACKABLE_TOSS_STATUSES = {"PAID", "PREPARING_PRODUCT", "DELIVERING"}


def normalize_toss_courier(name: object, default: str | None = None) -> str:
    """택배사명을 토스가 인식하는 정식명으로 정규화. (해달 파일이 '한진'처럼 약식으로 적어도)

    토스 deliveryCompany는 정식 택배사명을 요구한다. '한진' → '한진택배' 처럼 맞춰야 등록된다.
    default: 값이 비었을 때 쓸 택배사. 미지정 시 고구마(해달) 기본인 한진택배.
    발주처별 실제 발송 택배사가 다르므로 호출부가 명시해야 한다
    (쥬얼리프룻·제주다팜=롯데택배 — 한진 기본값 탓에 수박 건이 토스에서
    배송추적 안 되던 2026-06-15 사고 재발 방지).
    """
    fallback = default or TOSS_DELIVERY_COMPANY
    compact = re.sub(r"\s+", "", str(name or "")).lower()
    if not compact:
        return fallback
    if "대한통운" in compact or compact.startswith("cj"):
        return "CJ대한통운"
    if "한진" in compact:
        return "한진택배"
    if "롯데" in compact or "현대" in compact:
        return "롯데택배"
    if "우체국" in compact or "epost" in compact:
        return "우체국택배"
    if "로젠" in compact or "logen" in compact:
        return "로젠택배"
    return str(name).strip() or fallback


def normalize(value) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    s = re.sub(r"\s+", " ", s)
    return s


def stable_order_id(prefix: str, *values) -> str:
    raw = "|".join(normalize(value) for value in values if normalize(value))
    if not raw:
        return ""
    return f"{prefix}:{sha1(raw.encode('utf-8')).hexdigest()[:16]}"


def toss_order_id(item: dict) -> str:
    for key in ("orderNo", "orderId", "orderNumber", "orderSheetId", "paymentKey"):
        value = item.get(key)
        if value:
            return str(value)
    return ""


def normalize_strip(value) -> str:
    """공백 완전 제거 (매칭용)."""
    if value is None:
        return ""
    return re.sub(r"\s+", "", str(value).strip())


def transform_toss_option(product_name: str, option_name: str) -> str:
    return normalize_goguma_toss_option(product_name, option_name)


def is_goguma_order(item: dict) -> bool:
    """꿀고구마 토스 주문. 호박고구마는 별도 섹션(hobak_goguma)이 발주·운송장 처리한다."""
    product_name = (item.get("productName") or "").lower()
    option_name = (item.get("optionName") or "").lower()
    if is_hobak_goguma_text(product_name, option_name):
        return False
    return any(kw in product_name or kw in option_name for kw in GOGUMA_KEYWORDS)


# ---------------------------------------------------------------------------
# 1) 토스 주문 수집 → 발주서 생성
# ---------------------------------------------------------------------------

async def process_toss_order(
    from_date: str,
    to_date: str,
    exclude_order_ids: set[str] | None = None,
    skipped_names: list[str] | None = None,
    reissue_keys: set[str] | None = None,
    reissued: list[tuple[str, str]] | None = None,
) -> tuple[bytes, str, dict]:
    """Collect goguma orders from Toss API and generate 해달 발주서.

    Args:
        from_date: Start date (YYYY-MM-DD).
        to_date: End date (YYYY-MM-DD).
        exclude_order_ids: 이미 발주한 '주문번호|품목' 키(goguma 이력) — '전체 수집'과 같은 키라 서로 중복을 막는다.
        skipped_names·reissue_keys·reissued: goguma_auto.process_from_api와 같은 뜻(제외 이름·미출고 재발주).

    Returns:
        Tuple of (output_bytes, filename, stats_dict).
    """
    orders = await toss_client.get_orders(
        start_date=from_date,
        end_date=to_date,
        status="PAID",
    )

    entries = []
    for item in orders:
        if not is_goguma_order(item):
            continue

        address = item.get("address") or ""
        detail_addr = item.get("detailAddress") or ""
        full_address = f"{address} {detail_addr}".strip()

        zipcode = item.get("zipCode") or ""
        if zipcode:
            try:
                zipcode = str(int(float(zipcode))).zfill(5)
            except (ValueError, TypeError):
                zipcode = str(zipcode).zfill(5)

        product = transform_toss_option(
            item.get("productName") or "",
            item.get("optionName") or "",
        )

        entries.append({
            "name": item.get("receiverName") or "",
            "phone": item.get("receiverRealPhone") or item.get("receiverPhone") or "",
            "zipcode": zipcode,
            "address": full_address,
            "qty": str(item.get("quantity") or 1),
            "product": product,
            "memo": item.get("shippingNote") or "",
            "order_id": toss_order_id(item) or stable_order_id(
                "toss-api",
                item.get("receiverName"),
                item.get("receiverRealPhone") or item.get("receiverPhone"),
                full_address,
                product,
                item.get("quantity") or 1,
            ),
        })

    # 이전 영업일 발주분 자동 제외 — '토스만'으로 만든 뒤 '전체 수집'(또는 반대)을 눌러도 해달에 이중 발주되지 않게
    # (2026-11-16 리뷰: 이 경로는 이력을 조회도 기록도 안 했다).
    duplicate_skipped = 0
    if exclude_order_ids or reissue_keys:
        from app.processors.issued_orders import filter_entries_by_issued

        entries, duplicate_skipped = filter_entries_by_issued(
            entries, exclude_order_ids or set(), skipped_names=skipped_names,
            reissue_keys=reissue_keys, reissued=reissued,
        )

    if not entries:
        if duplicate_skipped:
            names = ", ".join(n for n in (skipped_names or []) if n)
            raise ValueError(
                f"신규 토스 고구마 주문이 없습니다 (이전 발주분 {duplicate_skipped}건 자동 제외"
                + (f": {names}" if names else "") + ")."
            )
        raise ValueError("해당 기간에 토스 고구마 주문이 없습니다.")

    # Load template
    template_path = TEMPLATE_DIR / "해달_발주서_한진양식.xlsx"
    if not template_path.exists():
        raise FileNotFoundError(
            f"템플릿 파일을 찾을 수 없습니다: {template_path}. "
            f"templates 디렉토리에 해달_발주서_한진양식.xlsx 파일을 넣어주세요."
        )

    tmpl_wb = load_workbook(filename=str(template_path))
    first_sheet = tmpl_wb.sheetnames[0]
    for name in tmpl_wb.sheetnames[1:]:
        del tmpl_wb[name]
    ws = tmpl_wb[first_sheet]

    font11 = Font(size=11)

    start_row = 2
    for r in range(2, ws.max_row + 2):
        if ws.cell(row=r, column=1).value is None:
            start_row = r
            break

    option_totals: dict[str, dict] = {}

    for i, entry in enumerate(entries):
        row_idx = start_row + i
        mapping = {
            1: entry["name"],
            2: entry["phone"],
            5: entry["zipcode"],
            6: entry["address"],
            7: "식품애착",
            8: "010-5700-7756",
            12: "전라남도 해남군 산이면 새상골길 ",
            13: entry["qty"],
            14: entry["product"],
            16: "선불",
            19: entry["memo"],
        }
        for col, value in mapping.items():
            cell = ws.cell(row=row_idx, column=col, value=value)
            cell.font = font11

        try:
            qty_int = int(float(entry["qty"])) if entry["qty"] not in (None, "") else 1
        except (ValueError, TypeError):
            qty_int = 1
        bucket = option_totals.setdefault(
            entry["product"] or "고구마",
            {
                "coupang_option_keyword": entry["product"] or "고구마",
                "vendor_option_name": entry["product"] or "고구마",
                "quantity": 0,
                "orders": [],
            },
        )
        bucket["quantity"] += qty_int
        if entry.get("order_id"):
            bucket["orders"].append({"order_id": entry["order_id"], "quantity": qty_int})

    output = BytesIO()
    tmpl_wb.save(output)
    output.seek(0)

    now = datetime.now(KST)
    filename = f"해달 발주서 한진양식_토스_알제이시스템즈_꿀고구마({now.strftime('%y%m%d')}).xlsx"
    stats = {
        "total": len(entries),
        "period": f"{from_date} ~ {to_date}",
        "product": "고구마",
        "options": list(option_totals.values()),
    }
    if duplicate_skipped:
        stats["duplicate_skipped"] = duplicate_skipped

    return output.read(), filename, stats


# ---------------------------------------------------------------------------
# 2) 토스 운송장 등록
# ---------------------------------------------------------------------------

def parse_haedal_file(haedal_bytes: bytes) -> list[dict]:
    """Parse 해달 발주서 and extract entries with tracking numbers."""
    wb = load_workbook(filename=BytesIO(haedal_bytes), data_only=True)
    ws = wb.active

    cols = detect_haedal_columns(ws)

    entries = []
    for row_idx in range(cols.start_row, ws.max_row + 1):
        name = normalize_strip(ws.cell(row=row_idx, column=cols.name).value)
        phone = normalize_strip(ws.cell(row=row_idx, column=cols.phone).value)
        address = normalize_strip(ws.cell(row=row_idx, column=cols.address).value)
        product = ws.cell(row=row_idx, column=cols.product).value

        if not name:
            continue

        tracking = find_tracking_in_row(ws, row_idx, cols.tracking, cols.tracking_alt)
        if tracking:
            skip_cols = tuple(
                c for c in (cols.name, cols.phone, cols.address, cols.product, cols.tracking) if c
            )
            courier = find_courier_in_row(ws, row_idx, cols.courier, skip_cols)
            entries.append({
                "name": name,
                "phone": phone,
                # 전화는 숫자만 비교 — 회신 '010-1234-5678'과 토스 API '01012345678'은 같은 번호(2026-11-16 리뷰)
                "phone_digits": re.sub(r"\D", "", phone),
                "address": address,
                "tracking": tracking,
                "courier": courier,
                "option_keys": option_key_set(product, transform_toss_option("", str(product or ""))),
                # 꿀·호박고구마 구분(품목명이 비면 모름=None) — 같은 사람의 다른 상품 박스 송장을 넣지 않게
                "hobak": is_hobak_goguma_text(product) if normalize_strip(product) else None,
            })

    return entries


def _masked_name_match(masked: str, full_names) -> list[str]:
    """토스가 가린 수취인명('정*순')을 해달 풀네임('정정순')과 매칭.

    같은 글자수이고 '*' 위치를 뺀 나머지 글자가 모두 일치하면 같은 사람으로 본다.
    토스 Shopping API는 일부 주문의 receiverName을 별표로 가려서 내려준다.
    """
    if "*" not in masked:
        return []
    return [
        name
        for name in full_names
        if len(name) == len(masked)
        and all(m == "*" or m == c for m, c in zip(masked, name))
    ]


def _tracking_key(value: object) -> str:
    """송장번호 비교용 — 숫자만(하이픈·공백 표기 차이 무시). 숫자가 없으면 공백만 뺀 글자."""
    return re.sub(r"\D", "", str(value or "")) or normalize_strip(value)


# ── 토스 주문 ↔ 해달 회신 송장 짝짓기 (order = 토스 주문, entry = 회신 줄) ──
def _phone_key(value: object) -> str:
    """전화 비교용 숫자 — 엑셀이 앞자리 0을 떨군 '1011112222'도 '01011112222'로 본다."""
    digits = re.sub(r"\D", "", str(value or ""))
    return "0" + digits if digits and not digits.startswith("0") else digits


def _entry_phone(entry: dict) -> object:
    # 회신 파서는 phone_digits를 채우지만, 다른 경로에서 온 줄은 전화 원문(phone)만 있을 수 있다
    return entry.get("phone_digits") or entry.get("phone")


def _phone_same(order: dict, entry: dict) -> bool:
    key = _phone_key(order["phone_digits"])
    return bool(key) and key == _phone_key(_entry_phone(entry))


def _phone_conflict(order: dict, entry: dict) -> bool:
    """양쪽 다 전화가 있는데 다르다 — 안심번호는 주문마다 달라 다른 주문일 가능성이 크다(옵션만으로는 안 넣는다)."""
    a, b = _phone_key(order["phone_digits"]), _phone_key(_entry_phone(entry))
    return bool(a and b) and a != b


def _option_same(order: dict, entry: dict) -> bool:
    return options_match(entry.get("option_keys"), order.get("option_keys"))


def _address_same(order: dict, entry: dict) -> bool:
    return bool(order["address"]) and order["address"] == entry.get("address")


def _same_goguma_kind(order: dict, entry: dict) -> bool:
    """꿀고구마 주문에 호박고구마 박스 송장(또는 그 반대)을 넣지 않는다. 회신 품목명이 비면 모른다고 보고 통과."""
    return entry.get("hobak") is None or entry["hobak"] == order["hobak"]


def _goguma_skip_reason(order: dict, used: set[int]) -> str:
    candidates = order["candidates"]
    if not candidates:
        return "매칭되는 수령인 없음"
    same_kind = [entry for entry in candidates if _same_goguma_kind(order, entry)]
    if not same_kind:
        return "다른 상품 송장뿐 — 이 회신에 없음"
    signal = [entry for entry in same_kind if _phone_same(order, entry) or _option_same(order, entry)]
    if not signal:
        return "이름만 같음(전화·옵션 다름) — 수동 확인"
    usable = [entry for entry in signal
              if _phone_same(order, entry) or not _phone_conflict(order, entry) or _address_same(order, entry)]
    if not usable:
        return "전화 다름(옵션만 같음) — 수동 확인"
    if all(id(entry) in used for entry in usable):
        return "사용 가능한 운송장번호 없음"
    return "동명이인 구분 불가 — 수동 확인"


async def process_toss_tracking(
    haedal_bytes: bytes,
    product_filter=None,
    product_label: str = "고구마",
) -> dict:
    """Parse tracking file, match Toss orders, register via API.

    product_filter: 토스 item → bool. 기본은 꿀고구마(is_goguma_order).
        호박고구마 섹션은 goguma_order.is_hobak_goguma_toss_order를 넘긴다.

    Returns:
        Dict with counts and per-order results.
    """
    product_filter = product_filter or is_goguma_order
    # 1. Parse 해달 file
    haedal_entries = parse_haedal_file(haedal_bytes)
    if not haedal_entries:
        raise ValueError("해달 발주서에서 운송장번호를 찾을 수 없습니다.")

    # 2. Fetch Toss orders and keep only statuses that can still accept
    # delivery info updates. Fetching all recent orders lets us return
    # clear skip messages instead of a hard error when orders already moved.
    now = datetime.now(KST)
    from_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    to_date = now.strftime("%Y-%m-%d")

    try:
        toss_orders_raw = await toss_client.get_orders(
            start_date=from_date,
            end_date=to_date,
            status=None,
        )
    except Exception as e:
        raise ValueError(f"토스 API 조회 실패: {e}") from e
    if toss_orders_raw is None:
        # 빈 목록으로 보면 '고구마 주문 없음'으로 잘못 안내된다 — 조회 실패는 실패로 멈춘다(2026-11-16 리뷰)
        raise ValueError("토스 API 조회 실패: 응답 없음 — 잠시 후 다시 시도하세요.")

    # Filter goguma orders
    toss_orders = []
    tracked_orders = []  # 이미 송장 있는 주문 — 등록은 안 하고 짝짓기에서 그 송장 줄을 먼저 뺀다
    pre_skipped_results = []
    seen_order_product_ids = set()
    for item in toss_orders_raw:
        if not product_filter(item):
            continue

        order_product_id = item.get("orderProductId")
        if not order_product_id or order_product_id in seen_order_product_ids:
            continue
        seen_order_product_ids.add(order_product_id)

        receiver_name = item.get("receiverName") or ""
        receiver_phone = item.get("receiverRealPhone") or item.get("receiverPhone") or ""
        address = item.get("address") or ""
        detail_addr = item.get("detailAddress") or ""
        full_address = f"{address} {detail_addr}".strip()
        order_status = item.get("orderProductStatus") or item.get("status") or ""
        existing_tracking = normalize_strip(item.get("shippingTrackingNumber") or "")
        order_id = item.get("orderId") or item.get("orderNumber") or ""

        order = {
            "order_product_id": order_product_id,
            "order_id": order_id,
            "name": normalize_strip(receiver_name),
            "phone": normalize_strip(receiver_phone),
            "phone_digits": re.sub(r"\D", "", str(receiver_phone)),
            "address": normalize_strip(full_address),
            "name_display": receiver_name,
            "order_status": order_status,
            "option_keys": option_key_set(
                item.get("optionName"),
                transform_toss_option(item.get("productName") or "", item.get("optionName") or ""),
            )
            or option_key_set(item.get("productName")),
            "hobak": is_hobak_goguma_text(item.get("productName"), item.get("optionName")),
        }

        if existing_tracking:
            pre_skipped_results.append({
                "order_id": str(order_id),
                "name": receiver_name,
                "tracking": existing_tracking,
                "status": "skip",
                "message": "이미 운송장번호가 등록된 주문",
            })
            order["tracking_key"] = _tracking_key(existing_tracking)
            tracked_orders.append(order)
            continue

        if order_status not in TRACKABLE_TOSS_STATUSES:
            pre_skipped_results.append({
                "order_id": str(order_id),
                "name": receiver_name,
                "status": "skip",
                "message": f"운송장 등록 불가 상태: {order_status or 'UNKNOWN'}",
            })
            continue

        toss_orders.append(order)

    if not toss_orders:
        goguma_total = len(seen_order_product_ids)
        if pre_skipped_results:
            return {
                "haedal_entries": len(haedal_entries),
                "toss_orders": goguma_total,
                "success": 0,
                "fail": 0,
                "skip": len(pre_skipped_results),
                "results": pre_skipped_results,
            }
        if toss_orders_raw:
            raise ValueError(
                f"토스에서 {len(toss_orders_raw)}건의 주문을 찾았지만 "
                f"{product_label} 주문이 없습니다."
            )
        raise ValueError(
            f"토스에서 {product_label} 주문을 찾을 수 없습니다. "
            f"(조회 기간: {from_date} ~ {to_date})"
        )

    # 3. Match — 이름만 같으면 동명이인 주문·같은 사람의 다른 박스에 송장이 들어간다(2026-11-16 리뷰).
    # 전화(숫자만 비교) 또는 옵션(kg·등급)이 맞아야 하고, 강한 신호부터 단계별로 전체를 1:1로 짝짓는다
    # (주문마다 바로 배정하면 앞 주문이 약한 신호로 남의 박스를 가져간다 — tracking_input과 같은 방식).
    entry_by_name = defaultdict(list)
    entry_by_tracking = defaultdict(list)
    for entry in haedal_entries:
        entry["claimed"] = False
        entry_by_name[entry["name"]].append(entry)
        entry_by_tracking[_tracking_key(entry["tracking"])].append(entry)

    # 이미 토스에 등록된 송장의 회신 줄은 그 주문 몫으로 먼저 뺀다 — 실패 건 재시도로 같은 해달 파일을 다시 올리면
    # 진짜 주인이 빠진 그 줄이 동명이인·같은 사람의 다른 박스 주문에 또 등록됐다(2026-11-16 리뷰). 합포장으로 같은
    # 송장 줄이 여럿이면 주문마다 하나만(그 주문과 가장 잘 맞는 줄) 차지해, 남은 줄은 같은 상자의 재시도 주문이 받는다.
    used_entries: set[int] = set()
    for order in tracked_orders:
        same = [entry for entry in entry_by_tracking.get(order["tracking_key"], []) if id(entry) not in used_entries]
        if same:
            best = max(same, key=lambda e: (_same_goguma_kind(order, e), _option_same(order, e), _phone_same(order, e)))
            used_entries.add(id(best))

    # 이름 수·전화 선점에는 이미 송장 있는 주문도 넣는다 — 다시 올려도 첫 실행과 같은 가드가 걸리게
    toss_name_counts = name_counts(order["name"] for order in [*toss_orders, *tracked_orders])
    for order in [*toss_orders, *tracked_orders]:
        candidates = entry_by_name.get(order["name"], [])
        # 토스가 수취인명을 가린 경우('정*순')에도 풀네임 해달 항목과 와일드카드 매칭
        if not candidates and "*" in order["name"]:
            for masked_name in _masked_name_match(order["name"], entry_by_name.keys()):
                candidates = candidates + entry_by_name[masked_name]
        order["candidates"] = candidates
        order["matched"] = None
        for entry in candidates:
            if _phone_same(order, entry) and _same_goguma_kind(order, entry):
                entry["claimed"] = True  # 이 주문 전화와 맞는 박스 — 다른 주문이 옵션만으로 가져가지 않게

    def eligible(order: dict, entry: dict) -> bool:
        return _same_goguma_kind(order, entry) and (_phone_same(order, entry) or _option_same(order, entry))

    def phone_guard(order: dict, entry: dict) -> bool:
        # 같은 사람이 토스로 여러 박스를 주문했으면 전화가 같아도 옵션이 다른 박스는 그 주문 것이 아니다 — 옵션으로 1:1
        return not (order["option_keys"] and entry.get("option_keys")
                    and toss_name_counts.get(order["name"], 0) > 1 and not _option_same(order, entry))

    tiers = [
        lambda o, e: eligible(o, e) and _phone_same(o, e) and _option_same(o, e) and _address_same(o, e),
        lambda o, e: eligible(o, e) and _phone_same(o, e) and _option_same(o, e),
        lambda o, e: eligible(o, e) and _phone_same(o, e) and phone_guard(o, e) and _address_same(o, e),
        lambda o, e: eligible(o, e) and _phone_same(o, e) and phone_guard(o, e),
        # 전화가 다르면 옵션이 맞는 박스만 — 다른 주문 전화와 맞는 박스(claimed)는 건드리지 않는다.
        # 양쪽 다 전화가 있는데 다르면(같은 옵션의 동명이인·쿠팡 고객 줄) 주소까지 맞아야 한다.
        lambda o, e: eligible(o, e) and not e["claimed"] and _option_same(o, e) and _address_same(o, e),
        lambda o, e: eligible(o, e) and not e["claimed"] and _option_same(o, e) and not _phone_conflict(o, e),
    ]
    # used_entries는 위에서 이미 송장 있는 주문 몫으로 뺀 회신 줄을 담고 있다 — 여기서 비우면 안 된다.
    for allowed in tiers:
        _match_tier(toss_orders, used_entries, allowed)

    matched_pairs = []
    results = list(pre_skipped_results)
    skip_count = len(pre_skipped_results)
    for order in toss_orders:
        matched = order["matched"]
        if matched is None:
            skip_count += 1
            results.append({
                "order_id": str(order["order_id"]),
                "name": order["name_display"],
                "status": "skip",
                "message": _goguma_skip_reason(order, used_entries),
            })
            continue
        matched_pairs.append((order, matched["tracking"], matched.get("courier") or ""))

    # 4. Register tracking numbers via Toss API
    success_count = 0
    fail_count = 0

    for order, tracking, courier in matched_pairs:
        order_product_id = order.get("order_product_id")
        if not order_product_id:
            fail_count += 1
            results.append({
                "order_id": str(order["order_id"]),
                "name": order["name_display"],
                "tracking": tracking,
                "status": "fail",
                "message": "orderProductId 없음",
            })
            continue

        # 해달 파일에 적힌 실제 택배사명 그대로 등록(CJ대한통운/한진택배 등). 없으면 기본값.
        delivery_company = normalize_toss_courier(courier)
        try:
            resp = await toss_client.register_tracking(
                order_product_id=order_product_id,
                delivery_company=delivery_company,
                tracking_number=tracking,
            )
            if resp is None:
                # 재시도를 다 써도 응답이 없으면 클라이언트가 None을 준다 — 성공으로 세면 빠진 송장을 모른다
                fail_count += 1
                logger.error(f"토스 운송장 등록 실패 (orderProductId={order_product_id}): 응답 없음")
                results.append({
                    "order_id": str(order["order_id"]),
                    "name": order["name_display"],
                    "tracking": tracking,
                    "status": "fail",
                    "message": "토스 응답 없음(재시도 소진) — 다시 등록 필요",
                })
                continue
            success_count += 1
            results.append({
                "order_id": str(order["order_id"]),
                "name": order["name_display"],
                "tracking": tracking,
                "status": "success",
                "message": "운송장 등록 완료",
            })
        except httpx.HTTPStatusError as e:
            fail_count += 1
            body = ""
            try:
                body = e.response.text[:500]
            except Exception:
                pass
            err_msg = f"HTTP {e.response.status_code}: {body}" if body else f"HTTP {e.response.status_code}"
            logger.error(
                f"토스 운송장 등록 실패 (orderProductId={order_product_id}): {err_msg}"
            )
            results.append({
                "order_id": str(order["order_id"]),
                "name": order["name_display"],
                "tracking": tracking,
                "status": "fail",
                "message": err_msg,
            })
        except Exception as e:
            fail_count += 1
            err_msg = f"{type(e).__name__}: {e}"
            logger.error(
                f"토스 운송장 등록 실패 (orderProductId={order_product_id}): {err_msg}"
            )
            results.append({
                "order_id": str(order["order_id"]),
                "name": order["name_display"],
                "tracking": tracking,
                "status": "fail",
                "message": err_msg,
            })

    return {
        "haedal_entries": len(haedal_entries),
        "toss_orders": len(toss_orders),
        "success": success_count,
        "fail": fail_count,
        "skip": skip_count,
        "results": results,
    }
