import re
import logging
from datetime import datetime, timezone, timedelta
from io import BytesIO
from collections import defaultdict

from openpyxl import load_workbook

from app import product_registry
from app.processors.tomato_order import (
    JBT_WATERMELON_KGS,
    JBT_WATERMELON_LABEL,
    transform_product,
)
from app.processors.tracking_match import (
    COUPANG_CJ_NAME,
    coupang_courier_name,
    name_counts,
    normalize_courier_name,
    option_key_set,
    options_match,
    requires_option_guard,
)
from app.processors.tracking_input import (
    PEAR_DEFAULT_COURIER,
    _is_hwanggeum_row,
    _is_pear_row,
    _match_tier,
    _product_families,
    _semantic_option_keys,
)
from app.toss.client import toss_client


logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))
# (구)TOSS_DELIVERY_COMPANY="한진택배" 상수는 제거 — 쥬얼리·제주다팜 품목은 롯데 발송이라
# 토스 등록 기본값은 normalize_toss_courier(courier, default="롯데택배")로 지정한다.
TRACKABLE_TOSS_STATUSES = {"PAID", "PREPARING_PRODUCT", "DELIVERING"}

# 토스 운송장 등록 대상 낱말. 쥬얼리(수박·참외·복숭아·감자·햇밤·옥수수)·제이비티(청사과 ⊂ '사과') +
# 제주다팜 품목은 상품 레지스트리(toss_tracking_keywords)에서 — '사과'는 홍로·가을햇사과(제주다팜)와
# 청사과(제이비티)를 모두 덮는다(2026-09-11 홍로 2건이 여기서 걸러져 송장이 안 들어가던 사고).
_TOSS_TRACKING_KEYWORDS = tuple(dict.fromkeys(
    ("수박", "참외", "복숭아", "감자", "옥수수", "사과", "햇밤") + product_registry.toss_tracking_keywords()
))


def phone_digits(value: object) -> str:
    """전화번호 숫자만. 회신은 '0508-7759-7034', 토스 API는 '050877597034'로 내려와
    문자열 그대로 비교하면 같은 주문인데도 절대 안 맞는다(2026-08-07 윤석찬 건)."""
    return re.sub(r"\D", "", str(value or ""))


def normalize(value) -> str:
    """공백 완전 제거 후 문자열 반환 (이름 매칭용)"""
    if value is None:
        return ""
    return re.sub(r'\s+', '', str(value).strip())


def normalize_courier(name: str) -> str:
    """택배사명 정규화 — 쿠팡이 인식하는 형태로 변환.

    예: 'CJ대한통운' -> 'CJ 대한통운' (띄어쓰기 필수)
    """
    return normalize_courier_name(name)


def is_mixed_chamoe_row(product_name: str, option_text: str) -> bool:
    return "성주참외" in product_name and "가정용 혼합과" in option_text


def product_type_for(product_name: str) -> str:
    # 청사과(아오리)는 2026-08-27 제주다팜 → 제이비티 이관. 홍로(가을햇사과)는 제주다팜 유지.
    _compact = re.sub(r"\s+", "", product_name or "")
    if ("청사과" in _compact or "아오리" in _compact) and not any(
        k in _compact for k in ("홍로", "홍사과", "가을햇사과")
    ):
        return "청사과"
    if "토마토" in product_name:
        return "토마토"
    if "참외" in product_name:
        return "참외"
    if "땅두릅" in product_name or "두릅" in product_name:
        return "땅두릅"
    if "수박" in product_name:
        return "수박"
    if "옥수수" in product_name:
        return "옥수수"
    if "복숭아" in product_name:
        return "복숭아"
    return ""


def corn_option_keys(*values: object) -> set[str]:
    text = normalize(" ".join(str(value) for value in values if value not in (None, "")))
    if "옥수수" not in text:
        return set()
    grade = "중품" if "중품" in text else "특품" if "특품" in text else ""
    counts = set(re.findall(r"(\d+)\s*(?:개|입)", text))
    if not grade or not counts:
        return set()
    return {f"corn:{grade}:{count}개" for count in counts}


# 쥬얼리·제이비티 품목 낱말 → 품목군. 제주다팜 품목(콜라비·황금향·시나노…)은 tracking_input._product_families가 안다.
# 이게 없으면 쥬얼리 회신의 수박·햇밤 줄이 품목을 몰라 같은 이름의 토스 콜라비 주문에 송장이 들어갔다(2026-11-16 리뷰).
# 수박·복숭아는 발주 판정처럼 더 잘게 나눈다(_fruit_families).
_JEWELRY_JBT_FAMILY_WORDS = (
    ("참외", "chamoe"),
    ("자두", "plum"),
    ("명이나물", "myeongi"),
    ("감자", "potato"),
    ("토마토", "tomato"),
    ("두릅", "dureup"),
)


def _fruit_families(*values: object) -> set[str]:
    """회신 줄·토스 주문의 품목군(등급·kg는 안 본다). 모르면 빈 집합.

    같은 사람의 같은 품목군 주문끼리는 전화(같은 토스 주문 = 같은 안심번호)만으로도 짝지어지므로, 쥬얼리 발주 판정
    (myeongi_order)이 다른 상품으로 보는 것은 다른 군으로 둔다 — 망고수박↔수박, 거반도·대극천·백도↔신비복숭아.
    쥬얼리 발주명 '거반도 1kg (4~10과 내외)'·'대극천 소과 1kg (…)'엔 '복숭아'가 없어 품목을 모르던 것도 이것으로 안다
    (2026-11-16 리뷰: 콜라비+거반도 주문에 거반도 송장이 콜라비로, 신비↔백도 송장이 서로 뒤바뀜).
    """
    from app.processors.myeongi_order import (
        _is_geobando,
        is_jewelry_chestnut_order,
        is_jewelry_daegeukcheon_order,
        is_mango_watermelon_order,
    )

    families = _product_families(*values)
    text = normalize(" ".join(str(value) for value in values if value not in (None, "")))
    families.update(family for word, family in _JEWELRY_JBT_FAMILY_WORDS if word in text)
    if "수박" in text:
        families.add("mango-watermelon" if is_mango_watermelon_order(text, "") else "watermelon")
    # 복숭아는 발주 판정 순서대로 하나만(거반도 → 대극천 → 신비). 백도·딱딱이 복숭아(제주다팜)는 _product_families가 baekdo로 둔다.
    if _is_geobando(text, ""):
        families.add("geobando")
    elif is_jewelry_daegeukcheon_order(text, ""):
        families.add("daegeukcheon")
    elif "복숭아" in text and "baekdo" not in families:
        families.add("shinbi")
    if is_jewelry_chestnut_order(text, ""):  # '햇 밤호박'의 '햇밤'은 햇밤이 아니다(쥬얼리 발주 판정과 같은 함수)
        families.add("chestnut")
    return families


def is_jbt_tracking_target(product_name: str, option_text: str) -> bool:
    if is_mixed_chamoe_row(product_name, option_text):
        return False
    product_type = product_type_for(product_name)
    if product_type in {"토마토", "땅두릅"}:
        return True
    if product_type == "청사과":
        from app.processors.tomato_order import jbt_apple_option
        return bool(jbt_apple_option(product_name, option_text))
    # 신비복숭아는 3·4kg만 제이비티 (1·2kg은 쥬얼리, 800g은 제외)
    if product_type == "복숭아":
        from app.processors.tomato_order import peach_kg, JBT_PEACH_KGS
        return peach_kg(product_name, option_text) in JBT_PEACH_KGS
    # ※ 수박·성주참외는 2026-06부터 쥬얼리팜(myeongi_tracking 등) 운송장 대상 — 제이비티 제외
    if product_type == "옥수수":
        return bool(corn_option_keys(product_name, option_text))
    return False


def _toss_item_text(value) -> str:
    parts: list[str] = []

    def walk(node) -> None:
        if node is None:
            return
        if isinstance(node, dict):
            for child in node.values():
                walk(child)
            return
        if isinstance(node, (list, tuple)):
            for child in node:
                walk(child)
            return
        parts.append(str(node))

    walk(value)
    return " ".join(parts)


def _toss_order_id(item: dict) -> str:
    for key in ("orderNo", "orderId", "orderNumber", "orderSheetId", "paymentKey"):
        value = item.get(key)
        if value:
            return str(value)
    return ""


def _find_reply_col(headers: dict, predicates: list) -> int | None:
    """헤더명(정규화) 우선순위 리스트로 컬럼 번호를 찾는다. (없으면 None)"""
    for pred in predicates:
        for c in sorted(headers):
            h = headers[c]
            if h and pred(h):
                return c
    return None


def parse_reply_file(tomato_reply_bytes: bytes) -> list[dict]:
    """거래처 회신 파일 파싱 — 헤더명 기반 자동감지.

    지원 양식 (헤더 라벨로 컬럼 자동 인식):
      - 제이비티 회신: 송장번호/수령인/연락처/주소/품목명/택배사
      - 쥬얼리 orderlist: 운송장번호/수령인/수령인연락처1/주소/상품명/옵션/택배사
      - 신비복숭아 회신: 운송장번호/수령인명/수령인연락처/주소/주문상품명/주문옵션명/택배사
    헤더가 없으면 제이비티 고정 레이아웃(A=송장,B=수령인,C=연락처,D=주소,E=품목,K=택배사)으로 폴백.
    """
    tr_wb = load_workbook(filename=BytesIO(tomato_reply_bytes), data_only=True)
    tr_ws = tr_wb.active

    headers = {
        c: normalize(tr_ws.cell(row=1, column=c).value)
        for c in range(1, tr_ws.max_column + 1)
    }

    col_tracking = _find_reply_col(headers, [
        lambda h: "운송장" in h,
        lambda h: "송장" in h,
    ])
    col_name = _find_reply_col(headers, [
        lambda h: h == "수령인명",
        lambda h: h == "수령인",
        lambda h: ("수령인" in h or "수취인" in h) and "연락처" not in h and "전화" not in h,
        lambda h: h in ("받는분성명", "성함", "이름", "받는분"),
    ])
    col_phone = _find_reply_col(headers, [
        lambda h: "수령인" in h and "연락처" in h and "1" in h,
        lambda h: "수령인" in h and ("연락처" in h or "전화" in h),
        lambda h: "연락처" in h or "전화" in h,
    ])
    col_addr = _find_reply_col(headers, [lambda h: "주소" in h])
    col_courier = _find_reply_col(headers, [lambda h: "택배" in h])
    col_product = _find_reply_col(headers, [lambda h: "상품명" in h, lambda h: "품목" in h])
    col_option = _find_reply_col(headers, [lambda h: "옵션" in h])

    header_based = col_tracking is not None and col_name is not None

    def cell(r, c):
        return tr_ws.cell(row=r, column=c).value if c else None

    entries = []
    for row_idx in range(2, tr_ws.max_row + 1):
        if header_based:
            tracking = normalize(cell(row_idx, col_tracking))
            name = normalize(cell(row_idx, col_name))
            phone = normalize(cell(row_idx, col_phone))
            address = normalize(cell(row_idx, col_addr))
            product = cell(row_idx, col_product)
            option_extra = cell(row_idx, col_option)
            courier_raw = cell(row_idx, col_courier)
        else:
            # 헤더 라벨이 없는 제이비티 고정 레이아웃 폴백
            tracking = normalize(tr_ws.cell(row=row_idx, column=1).value)
            name = normalize(tr_ws.cell(row=row_idx, column=2).value)
            phone = normalize(tr_ws.cell(row=row_idx, column=3).value)
            address = normalize(tr_ws.cell(row=row_idx, column=4).value)
            product = tr_ws.cell(row=row_idx, column=5).value
            option_extra = None
            courier_raw = tr_ws.cell(row=row_idx, column=11).value
        courier = str(courier_raw).strip() if courier_raw else ""

        if not name or not tracking:
            continue

        semantic_keys = corn_option_keys(product, option_extra) | _semantic_option_keys(product, option_extra)
        entries.append({
            "name": name,
            "phone": phone,
            "address": address,
            "tracking": tracking,
            "courier": courier,
            "phone_digits": phone_digits(phone),
            # 등급·kg 의미키(백도·콜라비·밤호박·홍감자 등)까지 넣어야 회신 발주명과
            # 토스 옵션 표기('2kg, 1박스, 중과')가 서로 매칭된다.
            "option_keys": option_key_set(product, option_extra) | semantic_keys,
            "semantic_keys": semantic_keys,
            # 품목군 — 토스 송장 등록은 이 줄과 같은 품목의 토스 주문에만 넣는다(2026-11-16 리뷰)
            "families": _fruit_families(product, option_extra),
        })

    return entries


def _address_key(value: object) -> str:
    """주소 비교용 — 공백·쉼표·괄호 표기 차이는 같은 주소로 본다."""
    return re.sub(r"[\s,()\[\]]", "", str(value or ""))


def _toss_default_courier(families: set[str], option_keys: set[str]) -> str:
    """회신 택배사 칸이 비었을 때 쓸 품목별 발송 택배사(토스 표기). 쿠팡 송장 입력과 같은 판정을 쓴다 —
    햇밤(myeongi_order.is_jewelry_chestnut_order → 품목군 chestnut)·햇 배 선물세트(tracking_input)=CJ대한통운,
    황금향(tracking_input)=한진택배, 나머지 쥬얼리·제주다팜 품목=롯데택배.
    품목은 주문 품목군(상품명·옵션, 거기에 품목 낱말이 없을 때만 주문 전체 글자)과 상품명·옵션 키로만 본다 —
    배송메모의 '햇밤'·'황금향' 낱말로 콜라비 주문이 CJ·한진으로 등록되면 안 된다(2026-11-16 리뷰).
    (2026-11-16 리뷰: 쥬얼리 회신 햇밤 줄 택배사 칸이 비어 토스 햇밤 주문이 '롯데택배 + CJ 송장'으로 등록됨)"""
    from app.processors.kolrabi_order import HWANGGEUM_COURIER
    from app.processors.toss_auto import normalize_toss_courier

    if "chestnut" in families:
        return normalize_toss_courier(COUPANG_CJ_NAME)
    if "pear" in families or _is_pear_row(option_keys):
        return normalize_toss_courier(PEAR_DEFAULT_COURIER)
    if "hwanggeum" in families or _is_hwanggeum_row(option_keys):
        return normalize_toss_courier(HWANGGEUM_COURIER)
    return "롯데택배"


# ── 토스 주문 ↔ 회신 송장 짝짓기 (order = 토스 주문, entry = 회신 줄) ──
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
    """양쪽 다 전화가 있는데 다르다 — 토스·쿠팡 안심번호는 주문마다 달라 다른 주문일 가능성이 크다."""
    a, b = _phone_key(order["phone_digits"]), _phone_key(_entry_phone(entry))
    return bool(a and b) and a != b


def _address_same(order: dict, entry: dict) -> bool:
    return bool(order["address_key"]) and order["address_key"] == entry["address_key"]


def _option_same(order: dict, entry: dict) -> bool:
    # options_match는 상품명 부분 일치('콜라비정품' ⊂ '콜라비정품3kg')도 같다고 본다 — 등급·kg 의미키가 분명히
    # 다르면(콜라비 5kg ↔ 3kg) 다른 박스라 옵션 일치로 치지 않는다(2026-11-16 리뷰).
    return options_match(entry.get("option_keys"), order.get("option_keys")) and not _option_conflict(order, entry)


def _family_same(order: dict, entry: dict) -> bool:
    return bool(order["families"] & entry["families"])


def _family_ok(order: dict, entry: dict) -> bool:
    """회신 줄의 품목군과 겹치는 토스 주문만 후보. 회신 줄 품목을 모르면(상품 칸 없음) _signal_ok가 전화·주소를 요구한다."""
    return not entry["families"] or _family_same(order, entry)


def _option_conflict(order: dict, entry: dict) -> bool:
    """양쪽 다 등급·kg 의미키가 있는데 하나도 안 겹치면 분명히 다른 박스다."""
    return bool(order["semantic_keys"] and entry["semantic_keys"]
                and not order["semantic_keys"] & entry["semantic_keys"])


def _signal_ok(order: dict, entry: dict) -> bool:
    """이름만으로는 안 넣는다 — 전화(숫자)·주소·옵션 의미키 중 하나는 맞아야 같은 주문으로 본다.
    주소만 같은 건 같은 집의 다른 주문일 수 있어, 같은 이름이 여럿이거나 등급·kg가 분명히 다르면 주소로는 묶지 않는다.
    회신 줄에 상품 정보가 없으면 옵션을 볼 수 없으니 전화 또는 주소가 맞아야 한다."""
    if _phone_same(order, entry):
        return True
    if entry["families"] and _option_same(order, entry):
        # 양쪽 다 전화가 있는데 다르면 같은 상품·같은 옵션의 동명이인(쿠팡 고객 줄 등)일 수 있다 — 주소까지 맞아야 한다
        if not _phone_conflict(order, entry) or _address_same(order, entry):
            return True
    return _address_same(order, entry) and not order["guarded"] and not _option_conflict(order, entry)


def _toss_skip_reason(order: dict, used: set[int]) -> str:
    same_product = [entry for entry in order["candidates"] if _family_ok(order, entry)]
    if not same_product:
        if not order["families"]:
            return "토스 상품 품목 확인 불가 — 수동 확인"
        return "다른 상품 송장뿐 — 이 회신에 없음"
    signal = [entry for entry in same_product if _signal_ok(order, entry)]
    if not signal:
        if any(entry["families"] and _option_same(order, entry) and _phone_conflict(order, entry)
               for entry in same_product):
            return "전화 다름(옵션만 같음) — 수동 확인"
        if any(entry["name"] == order["name"] for entry in same_product):
            return "이름만 같음(전화·주소·옵션 다름) — 수동 확인"
        return "주소만 같음 — 수동 확인"
    if all(id(entry) in used for entry in signal):
        return "회신 운송장 수 부족"
    return "동명이인 구분 불가 — 수동 확인"


def _match_toss_orders(
    toss_orders: list[dict],
    reply_entries: list[dict],
    tracked_orders: list[dict] = (),
) -> tuple[list[tuple[dict, dict]], list[str]]:
    """회신 송장 ↔ 토스 주문을 1:1로 짝짓는다. 반환: (짝 목록, 후보가 있었는데 못 넣은 주문의 '이름(사유)').

    후보는 수령인명(없으면 전화, 그것도 없으면 주소)으로 잡고, 품목군이 겹치며 전화·주소·옵션 중 하나는 맞아야 한다.
    주문마다 바로 배정하면 앞 주문이 약한 신호로 남의 송장을 가져가 뒤바뀌므로(2026-11-16 리뷰: 황금향↔시나노)
    tracking_input처럼 강한 신호부터 단계별로 전체를 짝짓고, 다음 단계는 남은 주문·남은 송장만 본다.
    tracked_orders = 이미 송장이 있는 토스 주문(등록 대상 아님, 'tracking_key' 포함) — 그 송장 줄을 먼저 빼고
    이름 수·전화 선점에도 넣는다(같은 회신을 다시 올려도 같은 송장이 다른 주문에 또 들어가지 않게).
    """
    from app.processors.toss_auto import _tracking_key

    entry_by_name = defaultdict(list)
    entry_by_phone = defaultdict(list)
    entry_by_address = defaultdict(list)
    entry_by_tracking = defaultdict(list)
    for entry in reply_entries:
        # parse_reply_file 밖에서 온 줄(키 없음)은 '품목 모름'으로 다룬다
        entry["families"] = set(entry.get("families") or ())
        entry["semantic_keys"] = set(entry.get("semantic_keys") or ())
        entry["address_key"] = _address_key(entry.get("address"))
        entry["claimed"] = False
        entry_by_name[entry["name"]].append(entry)
        if entry.get("phone_digits"):
            entry_by_phone[entry["phone_digits"]].append(entry)
        if entry["address_key"]:
            entry_by_address[entry["address_key"]].append(entry)
        entry_by_tracking[_tracking_key(entry.get("tracking"))].append(entry)

    # 이미 토스에 등록된 송장의 회신 줄은 그 주문 몫으로 먼저 뺀다 — 실패 건 재시도로 같은 회신을 다시 올리면
    # 진짜 주인이 빠진 그 줄이 동명이인·같은 사람의 다른 주문에 또 등록됐다(2026-11-16 리뷰). 합포장으로 같은 송장
    # 줄이 여럿이면 주문마다 하나만(그 주문과 가장 잘 맞는 줄) 차지해, 남은 줄은 같은 상자의 재시도 주문이 받는다.
    used: set[int] = set()
    for order in tracked_orders:
        same = [entry for entry in entry_by_tracking.get(order["tracking_key"], []) if id(entry) not in used]
        if same:
            best = max(same, key=lambda e: (_family_same(order, e), _option_same(order, e), _phone_same(order, e)))
            used.add(id(best))

    toss_name_counts = name_counts(order["name"] for order in [*toss_orders, *tracked_orders])
    for order in [*toss_orders, *tracked_orders]:
        candidates = entry_by_name.get(order["name"], [])
        if not candidates and order["phone_digits"]:
            candidates = entry_by_phone.get(order["phone_digits"], [])
        if not candidates and order["address_key"]:
            candidates = entry_by_address.get(order["address_key"], [])
        order["candidates"] = candidates
        order["matched"] = None
        # 같은 이름이 여럿(동일인 다건·동명이인)이면 주소만으로는 못 가른다 — 전화나 옵션이 맞아야 한다
        order["guarded"] = requires_option_guard(order["name"], toss_name_counts, len(candidates))
        for entry in candidates:
            if _phone_same(order, entry) and _family_ok(order, entry):
                entry["claimed"] = True  # 이 주문 전화와 맞는 같은 품목 송장 — 다른 주문이 약한 신호로 가져가지 않게

    def ok(order: dict, entry: dict) -> bool:
        return _family_ok(order, entry) and _signal_ok(order, entry)

    tiers = [
        # 1) 전화(숫자만) 일치 — 토스 안심번호는 주문마다 달라 가장 강한 신호. 같은 번호 여러 상품은 옵션 > 품목군 > 주소 순.
        lambda o, e: ok(o, e) and _phone_same(o, e) and _option_same(o, e) and _address_same(o, e),
        lambda o, e: ok(o, e) and _phone_same(o, e) and _option_same(o, e),
        lambda o, e: ok(o, e) and _phone_same(o, e) and _family_same(o, e),
        lambda o, e: ok(o, e) and _phone_same(o, e) and _address_same(o, e),
        lambda o, e: ok(o, e) and _phone_same(o, e),
        # 2) 전화로 못 가른 주문 — 다른 주문 전화와 맞는 송장(claimed)은 건드리지 않는다.
        lambda o, e: ok(o, e) and not e["claimed"] and _option_same(o, e) and _address_same(o, e),
        lambda o, e: ok(o, e) and not e["claimed"] and _option_same(o, e),
        lambda o, e: ok(o, e) and not e["claimed"] and _family_same(o, e) and _address_same(o, e),
        lambda o, e: ok(o, e) and not e["claimed"] and _address_same(o, e),
    ]
    for allowed in tiers:
        _match_tier(toss_orders, used, allowed)

    pairs: list[tuple[dict, dict]] = []
    skip_details: list[str] = []
    for order in toss_orders:
        if order["matched"] is not None:
            pairs.append((order, order["matched"]))
        elif order["candidates"]:
            # 회신에 아예 없는 토스 주문(다른 거래처 몫·아직 미발송)은 조용히 넘기고, 후보가 있었는데 못 넣은 건만 이유를 남긴다
            skip_details.append(f"{order['name_display'] or order['name']}({_toss_skip_reason(order, used)})")
    return pairs, skip_details


async def process_toss_watermelon_tracking(tomato_reply_bytes: bytes) -> dict:
    """거래처 회신의 운송장번호를 토스 주문에 API로 자동 등록.

    대상: 수박·성주참외·신비복숭아 등 토스 주문. 회신 수령인명(없으면 전화·주소)으로 후보를 잡고,
    품목군이 겹치며 전화·주소·옵션 중 하나는 맞아야 등록한다(_match_toss_orders).
    결제완료(PAID) 주문은 register_tracking이 상품준비중으로 자동 전환 후 등록한다.
    """
    reply_entries = parse_reply_file(tomato_reply_bytes)
    if not reply_entries:
        return {
            "toss_orders": 0,
            "toss_success": 0,
            "toss_fail": 0,
            "toss_skip": 0,
            "toss_error": "거래처 회신 파일에서 운송장번호를 찾을 수 없습니다.",
        }

    now = datetime.now(KST)
    from_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    to_date = now.strftime("%Y-%m-%d")

    # 조회 실패를 빈 목록으로 보면 '대상 주문 없음'처럼 조용히 끝난다 — 실패는 실패로 멈춘다(2026-11-16 리뷰)
    try:
        toss_orders_raw = await toss_client.get_orders(
            start_date=from_date,
            end_date=to_date,
            status=None,
        )
    except Exception as exc:
        raise ValueError(f"토스 주문 조회 실패: {exc}") from exc
    if toss_orders_raw is None:
        raise ValueError("토스 주문 조회 실패: 응답 없음 — 잠시 후 다시 시도하세요.")

    toss_orders = []
    tracked_orders = []  # 이미 송장 있는 주문 — 등록은 안 하고 짝짓기에서 그 송장 줄을 먼저 뺀다
    pre_skip_count = 0  # 이미 송장 있음·등록 불가 상태
    seen_order_product_ids = set()

    from app.processors.myeongi_order import jewelry_external_product
    from app.processors.toss_auto import _tracking_key

    for item in toss_orders_raw:
        text = _toss_item_text(item)
        # 우리 취급 토스 주문에 송장 등록 (회신 수령인명으로 매칭).
        # 쥬얼리(수박·참외·복숭아·감자) + 제주다팜(밤호박·콜라비·초당옥수수·홍로사과)
        # + 제이비티(청사과)까지 포함해야 각 페이지에서 토스 주문이 끌려와 운송장이 등록된다.
        # '사과'는 홍로사과·가을햇사과(제주다팜)와 청사과(제이비티)를 모두 덮는다 —
        # 2026-09-11 홍로 주문 2건이 여기서 걸러져 송장이 안 들어가던 사고.
        # '햇밤'(쥬얼리, 2026-10)은 '밤호박'과 겹치지 않아 따로 넣는다.
        if not any(k in text for k in _TOSS_TRACKING_KEYWORDS):
            continue

        option = str(item.get("optionName") or "")
        # 매칭 보조용 라벨 (복숭아 3·4kg 등 jewelry_external_product가 None이면 상품명 사용)
        label = jewelry_external_product(text, option, JBT_WATERMELON_KGS) or normalize(item.get("productName") or "")

        order_product_id = item.get("orderProductId")
        if not order_product_id or order_product_id in seen_order_product_ids:
            continue
        seen_order_product_ids.add(order_product_id)

        existing_tracking = normalize(item.get("shippingTrackingNumber") or item.get("trackingNumber") or "")
        order_status = str(item.get("orderProductStatus") or item.get("status") or item.get("orderStatus") or "").strip().upper()
        order_id = _toss_order_id(item)
        receiver_name = item.get("receiverName") or ""
        receiver_phone = item.get("receiverRealPhone") or item.get("receiverPhone") or ""
        address = item.get("address") or item.get("receiverAddress1") or ""
        detail_address = item.get("detailAddress") or item.get("receiverAddress2") or ""
        full_address = f"{address} {detail_address}".strip()

        if not existing_tracking and order_status and order_status not in TRACKABLE_TOSS_STATUSES:
            pre_skip_count += 1
            continue

        product_name = item.get("productName")
        semantic_keys = _semantic_option_keys(product_name, option)
        option_keys = option_key_set(option, label, product_name) | semantic_keys
        # 품목군 — 상품명·옵션에 품목 낱말이 없을 때만 주문 전체 글자(배송메모 포함)로
        families = _fruit_families(product_name, option) or _fruit_families(text)
        order = {
            "order_product_id": order_product_id,
            "order_id": order_id,
            "name": normalize(receiver_name),
            "phone": normalize(receiver_phone),
            "phone_digits": phone_digits(receiver_phone),
            "address": normalize(full_address),
            "address_key": _address_key(full_address),
            "name_display": receiver_name,
            # 회신 택배사 칸이 비면 쓸 품목별 발송 택배사 — 황금향=한진, 햇밤·햇 배=CJ, 나머지 쥬얼리·제주다팜=롯데
            "expected_courier": _toss_default_courier(families, option_keys),
            "option_keys": option_keys,
            "semantic_keys": semantic_keys,
            "families": families,
        }
        if existing_tracking:
            pre_skip_count += 1
            order["tracking_key"] = _tracking_key(existing_tracking)
            tracked_orders.append(order)
            continue
        toss_orders.append(order)

    matched_pairs, skip_details = _match_toss_orders(toss_orders, reply_entries, tracked_orders)
    skip_count = pre_skip_count + len(toss_orders) - len(matched_pairs)

    success_count = 0
    fail_count = 0
    courier_counts: dict[str, int] = {}
    courier_warnings: list[str] = []
    fail_details: list[str] = []

    from app.processors.toss_auto import normalize_toss_courier

    for order, entry in matched_pairs:
        tracking = entry["tracking"]
        courier = entry.get("courier") or ""
        # 회신 택배사명을 토스 정식명으로 정규화('한진'→'한진택배' 등). 회신에 값이 있으면 그 값,
        # 비면 품목별 기본값(expected_courier). (과거 제이비티 시절 한진 기본값 탓에 수박 건이 한진으로
        # 등록돼 배송완료가 추적 안 되던 2026-06-15 사고 재발 방지)
        expected = order.get("expected_courier") or "롯데택배"
        delivery_company = normalize_toss_courier(courier, default=expected)
        display = order.get("name_display") or order.get("name")
        if delivery_company != expected:
            # 품목의 원래 발송 택배사(대부분 롯데, 황금향은 한진, 햇밤은 CJ)와 다르게 등록되는 건 이상 신호 → 눈에 보이게
            courier_warnings.append(
                f"{display} → {delivery_company} {tracking} (회신 택배사 '{courier}')"
            )
        try:
            response = await toss_client.register_tracking(
                order_product_id=order["order_product_id"],
                delivery_company=delivery_company,
                tracking_number=tracking,
            )
            # 재시도를 다 써도 응답이 없으면 클라이언트가 None을 준다 — 성공으로 세면 빠진 송장을 모른다
            reason = "" if response is not None else "토스 응답 없음(재시도 소진)"
        except Exception as exc:
            reason = str(exc).strip() or type(exc).__name__
        if reason:
            fail_count += 1
            fail_details.append(f"{display} {tracking}({reason[:80]})")
            logger.error(
                f"토스 {JBT_WATERMELON_LABEL} 운송장 등록 실패 "
                "(orderProductId=%s, orderId=%s): %s",
                order.get("order_product_id"),
                order.get("order_id"),
                reason,
            )
            continue
        success_count += 1
        courier_counts[delivery_company] = courier_counts.get(delivery_company, 0) + 1

    stats = {
        # 조회된 과일 토스 주문 = 성공 + 실패 + 건너뜀(이미 송장·등록 불가 상태·짝 없음) — 건너뜀을 두 번 세지 않는다
        "toss_orders": len(toss_orders) + pre_skip_count,
        "toss_success": success_count,
        "toss_fail": fail_count,
        "toss_skip": skip_count,
    }
    if courier_counts:
        stats["toss_couriers"] = ", ".join(f"{k} {v}건" for k, v in sorted(courier_counts.items()))
    if courier_warnings:
        stats["toss_courier_warnings"] = " / ".join(courier_warnings)
    if skip_details:
        stats["토스 미등록 사유"] = " / ".join(skip_details)
    if fail_details:
        stats["토스 등록 실패"] = " / ".join(fail_details)
    return stats



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
    tomato_entries = parse_reply_file(tomato_reply_bytes)

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
    has_watermelon = False
    has_corn = False
    has_peach = False
    delivery_name_counts = name_counts(
        normalize(dl_ws.cell(row=row_idx, column=27).value)
        for row_idx in range(2, dl_ws.max_row + 1)
    )

    for row_idx in range(2, dl_ws.max_row + 1):
        # Column E = 5 (tracking number destination)
        e_cell = dl_ws.cell(row=row_idx, column=5)

        # Only fill empty E cells
        if e_cell.value is not None and normalize(e_cell.value) != "":
            continue

        product_name = str(dl_ws.cell(row=row_idx, column=11).value or "")
        option_text = str(dl_ws.cell(row=row_idx, column=12).value or "")
        if not is_jbt_tracking_target(product_name, option_text):
            continue

        dl_name = normalize(dl_ws.cell(row=row_idx, column=27).value)     # AA
        dl_phone = normalize(dl_ws.cell(row=row_idx, column=28).value)    # AB
        dl_address = normalize(dl_ws.cell(row=row_idx, column=30).value)  # AD
        dl_option_keys = option_key_set(
            option_text,
            transform_product(option_text, product_type_for(product_name)),
        ) | corn_option_keys(product_name, option_text)
        if not dl_option_keys:
            dl_option_keys = option_key_set(product_name)

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

        if requires_option_guard(dl_name, delivery_name_counts, len(candidates)):
            available = [
                (i, c) for i, c in available
                if options_match(c.get("option_keys"), dl_option_keys)
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
            dl_ws.cell(row=row_idx, column=4).value = coupang_courier_name(courier_val) if courier_val else ""
            used_entries.add(id(matched))
            filled += 1

            # K열(11) = 상품명 → 제이비티 발주 상품 판별
            if "토마토" in product_name:
                has_tomato = True
            if "참외" in product_name:
                has_chamoe = True
            if "땅두릅" in product_name:
                has_ddureup = True
            if "수박" in product_name:
                has_watermelon = True
            if "옥수수" in product_name:
                has_corn = True
            if "복숭아" in product_name:
                has_peach = True
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
    if has_watermelon:
        parts.append("수박")
    if has_corn:
        parts.append("초당옥수수")
    if has_peach:
        parts.append("신비복숭아")
    product_label = "_".join(parts) if parts else "발주"
    filename = f"송장파일_{product_label}({now.strftime('%Y%m%d')}).xlsx"
    stats = {
        "filled": filled,
        "skipped": skipped,
        "tomato_entries": len(tomato_entries),
    }

    return output.read(), filename, stats


def _phone_digits(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


def process_alwayz_tracking(
    tomato_reply_bytes: bytes,
    alwayz_bytes: bytes,
) -> tuple[bytes, str, dict]:
    """제이비티 회신 파일의 운송장번호를 올웨이즈 주문내역 파일에 입력.

    회신: A=송장번호, B=수령인, C=연락처, D=주소, K=택배사 (parse_reply_file)
    올웨이즈: O(15)=주소, S(19)=수령인, T(20)=연락처,
             U(21)=택배사 ←입력, W(23)=운송장번호 ←입력
    매칭: 이름 → (전화번호 숫자비교 → 주소 → 첫 후보) 순.
    """
    reply_entries = parse_reply_file(tomato_reply_bytes)
    if not reply_entries:
        raise ValueError("제이비티 회신 파일에서 운송장번호를 찾을 수 없습니다.")

    entry_by_name = defaultdict(list)
    entry_by_phone = defaultdict(list)
    for entry in reply_entries:
        if entry["name"]:
            entry_by_name[entry["name"]].append(entry)
        digits = _phone_digits(entry.get("phone"))
        if digits:
            entry_by_phone[digits].append(entry)

    al_wb = load_workbook(filename=BytesIO(alwayz_bytes))
    al_ws = al_wb.active

    used: set[int] = set()
    filled = 0
    skipped = 0

    for row_idx in range(2, al_ws.max_row + 1):
        w_cell = al_ws.cell(row=row_idx, column=23)   # W = 운송장번호
        if w_cell.value is not None and normalize(w_cell.value) != "":
            continue

        al_name = normalize(al_ws.cell(row=row_idx, column=19).value)   # S
        if not al_name:
            continue
        al_phone = _phone_digits(al_ws.cell(row=row_idx, column=20).value)  # T
        al_address = normalize(al_ws.cell(row=row_idx, column=15).value)    # O

        candidates = [c for c in entry_by_name.get(al_name, []) if id(c) not in used]

        # 이름 매칭 실패 시 전화번호 fallback (CS 수취인 변경 대응)
        if not candidates and al_phone:
            candidates = [c for c in entry_by_phone.get(al_phone, []) if id(c) not in used]

        if not candidates:
            skipped += 1
            continue

        matched = None
        for c in candidates:
            if al_phone and _phone_digits(c.get("phone")) == al_phone and c.get("address") == al_address:
                matched = c
                break
        if matched is None:
            for c in candidates:
                if al_phone and _phone_digits(c.get("phone")) == al_phone:
                    matched = c
                    break
        if matched is None:
            for c in candidates:
                if al_address and c.get("address") == al_address:
                    matched = c
                    break
        if matched is None:
            matched = candidates[0]

        w_cell.value = matched["tracking"]
        courier = matched.get("courier") or ""
        al_ws.cell(row=row_idx, column=21).value = normalize_courier(courier) if courier else "롯데택배"  # U
        used.add(id(matched))
        filled += 1

    output = BytesIO()
    al_wb.save(output)
    output.seek(0)

    now = datetime.now(KST)
    filename = f"올웨이즈_운송장입력완료_{now.strftime('%Y%m%d')}.xlsx"
    stats = {
        "filled": filled,
        "skipped": skipped,
        "reply_entries": len(reply_entries),
    }
    return output.read(), filename, stats


def process_toss_excel_tracking(
    tomato_reply_bytes: bytes,
    toss_export_bytes: bytes,
) -> tuple[bytes, str, dict]:
    """거래처 회신의 운송장번호를 토스 '엑셀 일괄발송' 파일에 채워서 반환.

    토스 주문배송관리 다운로드 파일 구조:
      - 헤더행: A열='주문번호', 그 외 '송장번호','택배사','수령인명','수령인 연락처','배송지'
      - 헤더 다음 '수정 가능/불가' 라벨행 → 건너뜀
      - 이후 주문 데이터행
    회신(제이비티/쥬얼리 orderlist)은 parse_reply_file로 자동 감지.
    매칭: 수령인명 → 연락처(숫자) → 첫 후보. 이미 송장 있으면 스킵.
    채운 파일을 토스 셀러센터 '엑셀 일괄발송'에 그대로 업로드하면 된다.
    """
    reply_entries = parse_reply_file(tomato_reply_bytes)
    if not reply_entries:
        raise ValueError("거래처 회신 파일에서 운송장번호를 찾을 수 없습니다.")

    entry_by_name = defaultdict(list)
    entry_by_phone = defaultdict(list)
    for entry in reply_entries:
        if entry["name"]:
            entry_by_name[entry["name"]].append(entry)
        digits = _phone_digits(entry.get("phone"))
        if digits:
            entry_by_phone[digits].append(entry)

    wb = load_workbook(filename=BytesIO(toss_export_bytes))
    ws = wb.active

    # 헤더행 탐색 (A열 == '주문번호')
    header_row = None
    for r in range(1, min(ws.max_row, 12) + 1):
        if normalize(ws.cell(row=r, column=1).value) == "주문번호":
            header_row = r
            break
    if header_row is None:
        raise ValueError(
            "토스 주문 엑셀에서 헤더(주문번호 행)를 찾지 못했습니다. "
            "토스 셀러센터 '주문배송관리'에서 받은 엑셀인지 확인해주세요."
        )

    col: dict[str, int] = {}
    for c in range(1, ws.max_column + 1):
        h = normalize(ws.cell(row=header_row, column=c).value)
        if h and h not in col:
            col[h] = c

    def _need(name: str) -> int:
        if name not in col:
            raise ValueError(f"토스 주문 엑셀에 '{name}' 열이 없습니다.")
        return col[name]

    c_tracking = _need("송장번호")
    c_name = _need("수령인명")
    c_courier = col.get("택배사")
    c_phone = col.get("수령인 연락처")

    # 데이터 시작행: 헤더 다음의 '수정 가능/불가' 라벨행은 건너뜀
    data_start = header_row + 1
    label = normalize(ws.cell(row=data_start, column=1).value).replace(" ", "")
    if label in ("수정가능", "수정불가"):
        data_start += 1

    used: set[int] = set()
    filled = 0
    skipped = 0

    for r in range(data_start, ws.max_row + 1):
        name = normalize(ws.cell(row=r, column=c_name).value)
        if not name:
            continue
        if normalize(ws.cell(row=r, column=c_tracking).value):
            skipped += 1  # 이미 송장 있음
            continue
        phone = _phone_digits(ws.cell(row=r, column=c_phone).value) if c_phone else ""

        candidates = [c for c in entry_by_name.get(name, []) if id(c) not in used]
        if not candidates and phone:
            candidates = [c for c in entry_by_phone.get(phone, []) if id(c) not in used]
        if not candidates:
            skipped += 1
            continue

        matched = None
        if phone:
            for c in candidates:
                if _phone_digits(c.get("phone")) == phone:
                    matched = c
                    break
        if matched is None:
            matched = candidates[0]

        ws.cell(row=r, column=c_tracking).value = matched["tracking"]
        if c_courier:
            courier = matched.get("courier") or ""
            ws.cell(row=r, column=c_courier).value = normalize_courier(courier) if courier else "롯데택배"
        used.add(id(matched))
        filled += 1

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    now = datetime.now(KST)
    filename = f"토스_운송장입력완료_{now.strftime('%Y%m%d')}.xlsx"
    stats = {
        "filled": filled,
        "skipped": skipped,
        "reply_entries": len(reply_entries),
    }
    return output.read(), filename, stats
