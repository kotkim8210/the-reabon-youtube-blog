import re
from datetime import datetime, timezone, timedelta
from io import BytesIO

from openpyxl import load_workbook

from app.processors.tracking_match import (
    COUPANG_CJ_NAME,
    coupang_courier_name,
    name_counts,
    option_key_set,
    options_match,
    requires_option_guard,
    unify_bundle_tracking,
)


KST = timezone(timedelta(hours=9))


def normalize(value) -> str:
    """공백 완전 제거 후 문자열 반환 (이름 매칭용)"""
    if value is None:
        return ""
    return re.sub(r'\s+', '', str(value).strip())


def normalize_courier(value) -> str:
    """Orderlist 택배사명을 쿠팡 DeliveryList가 인식하는 표기로 맞춘다."""
    return coupang_courier_name(value)


# 햇 배 선물세트는 제주다팜 다른 품목(롯데)과 달리 CJ대한통운으로 나간다(2026-09-20 사용자 확인).
# 회신에 택배사 칸이 비어 있으면 D열이 빈 채 남아 쿠팡윙 업로드가 실패하므로 이 값으로 채운다.
PEAR_DEFAULT_COURIER = COUPANG_CJ_NAME


def _is_pear_row(option_keys: set[str]) -> bool:
    return any(key.startswith("pear:") for key in option_keys)


# 황금향은 제주다팜이지만 한진택배로 나간다(2026-10-16 사용자 지시). 회신 택배사 칸이 비면 이 값으로 채운다.
def _is_hwanggeum_row(option_keys: set[str]) -> bool:
    return any(key.startswith("hwanggeum:") or "황금향" in key for key in option_keys)


def _phone_digits(value: object) -> str:
    """전화번호를 숫자만으로 정규화 — '010-1234-5678'과 '01012345678'을 동일 취급."""
    return re.sub(r"\D", "", str(value or ""))


def _source_option_values(row) -> list:
    # 거래처 회신 파일마다 옵션 열이 조금씩 달라서, 이름/전화/주소/송장 열을 제외한
    # 자주 쓰는 상품/옵션 후보 열만 모아 동명이인 보호용으로 비교한다.
    return [row[index].value for index in (4, 5, 6, 7, 8, 11, 13, 15) if len(row) > index]


def _source_option_keys(row) -> set[str]:
    values = _source_option_values(row)
    return option_key_set(*values) | _semantic_option_keys(*values)


def _product_families(*values: object) -> set[str]:
    """품목(상품군)만 본다 — 의미키와 달리 등급·kg를 못 읽어도 상품명 낱말로 정한다.
    같은 사람이 다른 거래처 상품(쥬얼리 햇밤 등)도 주문하면 그 줄은 이 회신의 품목이 아니라 송장을 받으면 안 된다
    (2026-11-02 강본아 햇밤 줄이 주소만 보고 황금향 송장을 가져가 나머지가 한 칸씩 밀린 사고).
    제주다팜 품목은 app.product_registry(family_match)에서 정의한다."""
    text = normalize(" ".join(str(value) for value in values if value not in (None, "")))
    from app.product_registry import product_families

    families: set[str] = product_families(text)  # 제주다팜 품목(콜라비·밤호박·홍감자·백도·홍로·감홍·…)
    if "참외" in text and any(token in text for token in ("알뜰", "혼합", "랜덤")):
        families.add("chamoe-altteul")
    if "옥수수" in text:
        families.add("corn")
    if "청사과" in text or "아오리" in text:
        families.add("apple")
    return families


def _phone_eq(row: dict, entry: dict) -> bool:
    return bool(row["phone"]) and row["phone"] == entry["phone"]


def _phone_conflict(row: dict, entry: dict) -> bool:
    """회신 송장과 DeliveryList 줄 양쪽에 전화가 있는데 숫자가 다르다 — 다른 사람(동명이인)일 수 있다."""
    return bool(row["phone"]) and bool(entry["phone"]) and row["phone"] != entry["phone"]


def _address_eq(row: dict, entry: dict) -> bool:
    return bool(row["address"]) and row["address"] == entry["address"]


def _options_eq(row: dict, entry: dict) -> bool:
    return options_match(entry["option_keys"], row["option_keys"])


def _family_eq(row: dict, entry: dict) -> bool:
    """같은 품목인지. 거래처가 등급을 자기 이름으로 회신해(홍감자 '대_3KG' = 우리 '중 3kg')
    등급·kg 키가 안 맞아도 같은 상품이면 '다른 상품 행'으로 보면 안 된다(2026-10-16 리뷰)."""
    return bool(row["families"] & entry["families"])


def _compatible(row: dict, entry: dict) -> bool:
    """회신 송장의 품목을 알면 같은 품목 줄에만 넣는다(품목을 모르는 회신은 종전처럼 허용)."""
    return not entry["families"] or _family_eq(row, entry)


def _match_tier(rows: list[dict], used: set[int], allowed) -> None:
    """한 단계 조건(allowed)으로 최대한 많이 짝짓는다(증가 경로). 앞 줄이 여러 송장에 맞으면
    뒤 줄에만 맞는 송장을 양보해, 먼저 나온 줄이 남의 송장을 가로채지 않는다."""
    owner: dict[int, tuple[dict, dict]] = {}  # id(회신 송장) → (DeliveryList 줄, 회신 송장)

    def assign(row: dict, seen: set[int]) -> bool:
        options = [entry for entry in row["candidates"] if id(entry) not in used and allowed(row, entry)]
        for entry in options:  # 빈 송장부터 회신 순서대로(같은 상품 여러 건은 줄 순서 = 회신 순서)
            if id(entry) not in owner:
                owner[id(entry)] = (row, entry)
                return True
        for entry in options:  # 빈 게 없을 때만 앞 줄을 다른 송장으로 옮길 수 있는지 본다
            key = id(entry)
            if key in seen:
                continue
            seen.add(key)
            if assign(owner[key][0], seen):
                owner[key] = (row, entry)
                return True
        return False

    for row in rows:
        if row["matched"] is None:
            assign(row, set())
    for key, (row, entry) in owner.items():
        row["matched"] = entry
        used.add(key)


def _skip_reason(row: dict, used: set[int]) -> str:
    candidates = row["candidates"]
    if not candidates:
        return "회신에 없음"
    same_product = [entry for entry in candidates if _compatible(row, entry)]
    if not same_product:
        return "같은 사람의 다른 상품 행 — 이 회신에 없음"
    if all(id(entry) in used for entry in same_product):
        return "회신 운송장 수 부족"
    if all(_phone_conflict(row, entry) and not _address_eq(row, entry)
           for entry in same_product if id(entry) not in used):
        return "전화·주소 불일치 — 동명이인 의심, 수동 확인"
    return "동명이인 구분 불가 — 수동 확인"


def _semantic_option_keys(*values: object) -> set[str]:
    text = normalize(" ".join(str(value) for value in values if value not in (None, "")))
    if not text:
        return set()

    weights = set(re.findall(r"(\d+)kg", text, flags=re.IGNORECASE))
    from app.product_registry import semantic_keys

    # 제주다팜 품목(콜라비·밤호박·홍감자·백도·홍로·감홍·시나노·황금향·태추·부사·햇 배)은 상품 레지스트리의 의미키
    keys: set[str] = semantic_keys(text, weights)
    if "참외" in text and any(token in text for token in ("알뜰", "혼합", "랜덤")):
        keys.update(f"chamoe-altteul:{weight}kg" for weight in weights)
    # 초당옥수수 동명이인 구분: orderlist는 상품명에, DeliveryList는 옵션에 등급/수량이 있어
    # 통째 문자열 비교로는 안 맞는다. 등급(특품/중품/상품/정품)+수량(N개) 의미키로 양쪽을 맞춘다.
    if "옥수수" in text:
        grade = next((g for g in ("특품", "중품", "상품", "정품") if g in text), "")
        counts = set(re.findall(r"(\d+)\s*개", text))
        keys.update(f"corn:{grade}:{count}개" for count in counts)
    if "청사과" in text or "아오리" in text:
        # 청사과: orderlist(발주명 '청사과 {등급}(가정용) … {kg}kg(…)')와 DeliveryList(쿠팡 옵션)의
        # 표기가 달라 등급(중소과/소과/대과)+kg 의미키로 묶는다. '중소과'가 '소과' 포함 → 긴 것 먼저.
        grade = next((g for g in ("중소과", "소과", "대과") if g in text), "")
        keys.update(f"apple:{grade}:{weight}kg" for weight in weights)
    return keys


def _delivery_option_keys(product_name: object, option_name: object) -> set[str]:
    return option_key_set(product_name, option_name) | _semantic_option_keys(product_name, option_name)


def process(
    orderlist_bytes: bytes,
    delivery_bytes: bytes,
) -> tuple[bytes, str, dict]:
    """Input tracking numbers from orderlist into DeliveryList.

    Args:
        orderlist_bytes: Raw bytes of the order list Excel file.
            Columns: K=name, M=phone, O=address, Q=courier, R=tracking
        delivery_bytes: Raw bytes of the DeliveryList Excel file.
            Columns: AA=name, AB=phone, AD=address, D=courier, E=tracking (to fill)

    Returns:
        Tuple of (output_bytes, filename, stats_dict).
    """
    # Load orderlist
    ol_wb = load_workbook(filename=BytesIO(orderlist_bytes), data_only=True)
    ol_ws = ol_wb.active

    # Build list of order entries: (name, phone, address, tracking, option_keys, families)
    order_entries = []
    for row in ol_ws.iter_rows(min_row=2):
        name = normalize(row[10].value) if len(row) > 10 else ""     # K = index 10
        phone = normalize(row[12].value) if len(row) > 12 else ""    # M = index 12
        address = normalize(row[14].value) if len(row) > 14 else ""  # O = index 14
        courier = normalize_courier(row[16].value) if len(row) > 16 else "" # Q = index 16
        tracking = normalize(row[17].value) if len(row) > 17 else "" # R = index 17

        if name and tracking:
            order_entries.append({
                "name": name,
                "phone": _phone_digits(phone),
                "address": address,
                "courier": courier,
                "tracking": tracking,
                "option_keys": _source_option_keys(row),
                "families": _product_families(*_source_option_values(row)),
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
    skip_details: list[str] = []  # 미입력 건의 이름·사유 — 조용한 skip 금지

    # Build index of order entries by name for faster lookup
    from collections import defaultdict
    order_by_name = defaultdict(list)
    for entry in order_entries:
        order_by_name[entry["name"]].append(entry)

    rows = []
    for row_idx in range(2, dl_ws.max_row + 1):
        e_value = dl_ws.cell(row=row_idx, column=5).value   # E 운송장 — 빈 칸만 채운다
        product = dl_ws.cell(row=row_idx, column=11).value  # K 상품명
        option = dl_ws.cell(row=row_idx, column=12).value   # L 옵션명
        rows.append({
            "row_idx": row_idx,
            "has_tracking": e_value is not None and normalize(e_value) != "",
            "name": normalize(dl_ws.cell(row=row_idx, column=27).value),       # AA
            "phone": _phone_digits(dl_ws.cell(row=row_idx, column=28).value),  # AB (숫자만 비교)
            "address": normalize(dl_ws.cell(row=row_idx, column=30).value),    # AD
            "option_keys": _delivery_option_keys(product, option),
            "families": _product_families(product, option),
        })
    delivery_name_counts = name_counts(row["name"] for row in rows)

    # 회신 송장의 전화가 DeliveryList 어느 줄(같은 이름)과 맞으면 그 주문 몫 — 약한 신호로 다른 줄에 주지 않는다.
    dl_phones_by_name = defaultdict(set)
    for row in rows:
        if row["phone"]:
            dl_phones_by_name[row["name"]].add(row["phone"])
    for entry in order_entries:
        entry["claimed"] = bool(entry["phone"]) and entry["phone"] in dl_phones_by_name.get(entry["name"], ())

    targets = [row for row in rows if row["name"] and not row["has_tracking"]]
    for row in targets:
        candidates = order_by_name.get(row["name"], [])
        # 폴백: 이름 잘림(쿠팡 열폭 제한 등) 대응 - 접두어 매칭
        if not candidates:
            MIN_PREFIX_LEN = 8
            for order_name, entries in order_by_name.items():
                if len(order_name) < MIN_PREFIX_LEN:
                    continue
                if row["name"].startswith(order_name) or order_name.startswith(row["name"]):
                    candidates = entries
                    break
        row["candidates"] = candidates
        row["matched"] = None

    def needs_guard(row: dict) -> bool:
        return requires_option_guard(row["name"], delivery_name_counts, len(row["candidates"]))

    def phone_guard(row: dict, entry: dict) -> bool:
        # 같은 이름이 여러 줄이고 양쪽 다 옵션 정보가 있는데 하나도 안 맞으면 전화가 같아도 다른 상품
        # (2026-10-16 같은 주문번호 황금향+시나노골드). 회신에 옵션 정보가 없으면 종전처럼 전화로 매칭
        # (2026-07-14 동일인 다건이 옵션 가드에 걸려 전부 skip되던 사고 보호).
        return not (row["option_keys"] and entry["option_keys"]
                    and delivery_name_counts.get(row["name"], 0) > 1
                    and not _options_eq(row, entry) and not _family_eq(row, entry))

    def phone_or_address(row: dict, entry: dict) -> bool:
        # 양쪽에 전화가 있는데 숫자가 다르면 다른 사람일 수 있어 주소(공백 무시)까지 같아야 넣는다.
        # 회신 전화가 비어 있으면 종전처럼 허용(2026-11-16 리뷰 — 부산 김철수 줄에 서울 토스 고객 김철수 송장).
        return not _phone_conflict(row, entry) or _address_eq(row, entry)

    # 줄마다 바로 배정하면 앞 줄이 약한 신호(주소)로 남의 송장을 가져가 뒤 줄이 한 칸씩 밀린다
    # (2026-11-02 강본아: 햇밤 줄이 황금향 송장 → 황금향은 감홍, 감홍은 시나노 송장, 시나노는 빈칸).
    # 그래서 강한 신호부터 단계별로 전체 줄을 짝짓고, 다음 단계는 남은 줄·남은 송장만 본다.
    tiers = [
        # 1) 전화(안심번호, 숫자만) 일치 — 주문마다 번호가 달라 가장 강한 신호.
        #    같은 주소로 여러 상품을 받으면 주소로는 못 가르니 옵션 > 상품군 > 주소 순.
        lambda r, e: _phone_eq(r, e) and _options_eq(r, e) and _address_eq(r, e),
        lambda r, e: _phone_eq(r, e) and _options_eq(r, e),
        lambda r, e: _phone_eq(r, e) and _family_eq(r, e),  # 홍감자 '대_3KG'처럼 거래처 등급명이 달라도 같은 상품
        lambda r, e: _phone_eq(r, e) and _compatible(r, e) and phone_guard(r, e) and _address_eq(r, e),
        lambda r, e: _phone_eq(r, e) and _compatible(r, e) and phone_guard(r, e),
        # 2) 전화로 못 가른 줄 — 다른 줄 전화와 맞는 송장(claimed)은 건드리지 않는다.
        lambda r, e: not e["claimed"] and _compatible(r, e) and _options_eq(r, e) and _address_eq(r, e),
        lambda r, e: not e["claimed"] and _compatible(r, e) and _options_eq(r, e) and phone_or_address(r, e),
        lambda r, e: not e["claimed"] and _compatible(r, e) and not needs_guard(r) and phone_or_address(r, e),
        # 옵션으로도 못 가른 동명이인 → 같은 품목·같은 주소일 때만, 아니면 오배정 위험이라 미입력+표시
        lambda r, e: not e["claimed"] and _compatible(r, e) and needs_guard(r) and _address_eq(r, e),
    ]
    used_entries: set[int] = set()
    for allowed in tiers:
        _match_tier(targets, used_entries, allowed)

    for row in targets:
        matched = row["matched"]
        if matched is None:
            skipped += 1
            skip_details.append(f"{row['name']}({_skip_reason(row, used_entries)})")
            continue
        row_idx = row["row_idx"]
        dl_ws.cell(row=row_idx, column=5).value = matched["tracking"]
        courier = normalize_courier(matched.get("courier"))
        if not courier and _is_pear_row(row["option_keys"]):
            courier = PEAR_DEFAULT_COURIER  # 햇 배 선물세트 = CJ대한통운 발송
        if not courier and _is_hwanggeum_row(row["option_keys"]):
            from app.processors.kolrabi_order import HWANGGEUM_COURIER
            courier = HWANGGEUM_COURIER  # 황금향 = 한진택배 발송
        if courier:
            dl_ws.cell(row=row_idx, column=4).value = courier
        filled += 1

    # 한 주문(묶음)에 상품이 여럿이면 회신 송장도 여럿 → 쿠팡은 하나만 받으니 첫 송장으로 통일(2026-11-02 파소향)
    bundle_notes = unify_bundle_tracking(dl_ws, {row["row_idx"] for row in rows if row["has_tracking"]})

    # Save to bytes
    output = BytesIO()
    dl_wb.save(output)
    output.seek(0)

    now = datetime.now(KST)
    filename = f"DeliveryList_제주다팜_운송장입력완료_{now.strftime('%Y%m%d')}.xlsx"
    stats = {"filled": filled, "skipped": skipped}
    if skip_details:
        stats["skipped_names"] = ", ".join(skip_details)
    if bundle_notes:
        stats["한주문송장통일"] = ", ".join(bundle_notes)

    return output.read(), filename, stats
