import re
from collections import Counter
from collections.abc import Iterable


def match_key(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", "", str(value).strip())


# 쿠팡 DeliveryList(택배사 D열)가 인식하는 CJ 표기 — 'CJ'와 '대한통운' 사이 띄어쓰기 필수.
COUPANG_CJ_NAME = "CJ 대한통운"


def _is_cj_courier(compact: str) -> bool:
    """거래처가 CJ를 어떻게 적어도 잡는다: CJ대한통운·CJ 대한통운·씨제이대한통운·대한통운·
    CJ택배·CJ대한통운(주)·CJGLS·cj logistics… ('대한통운'·'씨제이'는 CJ뿐이고,
    'cj'로 시작하는 택배사도 CJ뿐이라 과매칭 없음.)"""
    lowered = compact.lower()
    return "대한통운" in compact or "씨제이" in compact or lowered.startswith("cj")


def normalize_courier_name(value: object, default: str = "") -> str:
    if value is None:
        return default
    courier = str(value).strip()
    if not courier:
        return default
    compact = match_key(courier)
    if _is_cj_courier(compact):
        # 종전엔 정확히 'CJ대한통운'일 때만 바꿔서 '씨제이대한통운'·'CJ택배' 같은 회신은
        # 그대로 D열에 들어가 쿠팡윙 업로드에서 택배사 미인식 (2026-09-20 햇 배 선물세트 CJ 발송 대비).
        return COUPANG_CJ_NAME
    return courier


def coupang_courier_name(value: object, default: str = "") -> str:
    """쿠팡 DeliveryList(택배사 D열)에 넣을 표기.

    쿠팡 송장 일괄등록은 '우체국'만 인식한다. 거래처 회신은 '우체국택배/우체국 택배/
    우체국등기' 등으로 오는데 그대로 넣으면 업로드 시 택배사가 인식되지 않는다
    (2026-07-27 제주다팜 백도 건). 올웨이즈·토스는 '우체국택배'를 쓰므로
    normalize_courier_name은 그대로 두고 쿠팡 쪽에서만 변환한다.
    """
    courier = normalize_courier_name(value, default)
    compact = match_key(courier)
    if "우체국" in compact or re.fullmatch(r"(?i)epost", compact):
        return "우체국"
    # 비셀러는 '롯데(현대)택배'로 회신한다. 쿠팡이 아는 이름은 '롯데택배'뿐이라
    # 괄호 표기 그대로 넣으면 택배사가 인식되지 않는다(2026-09-07).
    if "롯데" in compact:
        return "롯데택배"
    # 해달은 택배사 칸에 '한진'만 적어 보내기도 한다(2026-09-04). 쿠팡 표기는 '한진택배'.
    if "한진" in compact:
        return "한진택배"
    return courier


def option_key_set(*values: object) -> set[str]:
    keys: set[str] = set()
    for value in values:
        key = match_key(value)
        if key:
            keys.add(key)
    return keys


def options_match(source_keys: Iterable[str] | None, target_keys: Iterable[str] | None) -> bool:
    source = {key for key in (source_keys or []) if key}
    target = {key for key in (target_keys or []) if key}
    if not source or not target:
        return False
    if source & target:
        return True
    for left in source:
        for right in target:
            if min(len(left), len(right)) >= 4 and (left in right or right in left):
                return True
    return False


def filled_tracking_rows(ws, tracking_col: int = 5) -> set[int]:
    """운송장 칸(E)이 이미 채워진 DeliveryList 줄 — 매칭 전에 찍어 두고 '이번에 채운 줄'을 가려낸다."""
    return {r for r in range(2, ws.max_row + 1) if match_key(ws.cell(row=r, column=tracking_col).value)}


def amount(value: object) -> float:
    """금액 칸(숫자·'25,800'·'25800원')을 숫자로. 못 읽으면 -1(비교에서 가장 낮게)."""
    digits = re.sub(r"[^\d.]", "", str(value if value is not None else ""))
    try:
        return float(digits) if digits else -1.0
    except ValueError:
        return -1.0


# 크기·등급이 큰 순위(클수록 비쌈). '중대과'·'중소과'·'특대과'가 '대과'·'소과'를 품고 있어 긴 낱말을 먼저 본다.
# 꿀고구마 등급은 정산단가 순(특상 > 중상 > 대 > 한입), 과일은 과 크기 순(특대과 > 대과 > 중대과 > 중과 > 중소과 > 소과).
_SIZE_RANKS = (
    ("특대", 9), ("특상", 8), ("중대", 6), ("대과", 7), ("중상", 5), ("중소", 3), ("중과", 4),
    ("소과", 2), ("한입", 1), ("대", 4), ("중", 3), ("소", 2),
)


def option_rank(price: object, paid: object, option_text: object) -> tuple[float, float, int]:
    """한 묶음에 송장이 여러 개일 때 고를 '더 비싼 옵션'의 순위(2026-11-03 사용자 기준).
    가격이 가장 정확(옵션판매가, 없으면 결제액) → 가격을 모르거나 같으면 무게(kg)가 큰 것 →
    그래도 같으면 크기·등급이 큰 것. 모두 같으면 고르는 쪽(max)이 앞의 것을 쓴다."""
    price_value = amount(price)
    if price_value <= 0:
        price_value = amount(paid)
    text = match_key(option_text).lower()
    weights = [
        float(number) / (1000 if unit == "g" else 1)
        for number, unit in re.findall(r"(\d+(?:\.\d+)?)(kg|g)(?![a-z])", text)
    ]
    size = next((rank for word, rank in _SIZE_RANKS if word in text), 0)
    return (price_value, max(weights, default=-1.0), size)


def unify_bundle_tracking(
    ws,
    prefilled: set[int],
    bundle_col: int = 2,
    tracking_col: int = 5,
    courier_col: int = 4,
    name_col: int = 27,
    option_col: int = 12,
    product_col: int = 11,
    price_col: int = 24,
    paid_col: int = 19,
) -> list[str]:
    """쿠팡은 묶음배송번호(B열) 하나에 송장 하나만 받는다(분리배송이 아니면).
    거래처가 상품마다 박스·송장을 따로 보내 같은 묶음 줄들에 송장이 다르게 들어가면 업로드가 거부돼
    그 주문이 통째로 빠진다(2026-11-02 파소향 꿀고구마 3kg+5kg 한 주문 → 해달 송장 2개 → 미입력).
    사용자 지시: 송장은 하나만, **더 비싼 옵션의 송장**으로(2026-11-03 — 파소향은 5kg 특상 송장).
    이번에 채운 줄끼리 같은 묶음이면 option_rank(옵션판매가 X열·결제액 S열 → 무게 → 크기)가 가장 큰 줄의
    송장·택배사로 맞춘다. 이미 채워져 있던 줄(다른 거래처 회신)은 건드리지 않는다. 반환: 결과 화면 표시용 설명."""
    bundles: dict[str, list[int]] = {}
    for r in range(2, ws.max_row + 1):
        if r in prefilled or not match_key(ws.cell(row=r, column=tracking_col).value):
            continue
        bundle = match_key(ws.cell(row=r, column=bundle_col).value)
        if bundle:
            bundles.setdefault(bundle, []).append(r)

    notes: list[str] = []
    for rows in bundles.values():
        if len({match_key(ws.cell(row=r, column=tracking_col).value) for r in rows}) < 2:
            continue
        # max는 순위가 같으면 앞의 것을 고른다 → 가격·무게·크기가 모두 같으면 첫 줄
        keep = max(rows, key=lambda r: option_rank(
            ws.cell(row=r, column=price_col).value,
            ws.cell(row=r, column=paid_col).value,
            ws.cell(row=r, column=option_col).value or ws.cell(row=r, column=product_col).value,
        ))
        tracking = ws.cell(row=keep, column=tracking_col).value
        courier = ws.cell(row=keep, column=courier_col).value
        others: list[str] = []
        for r in rows:
            cell = ws.cell(row=r, column=tracking_col)
            if match_key(cell.value) == match_key(tracking):
                continue
            if match_key(cell.value) not in others:
                others.append(match_key(cell.value))
            cell.value = tracking
            ws.cell(row=r, column=courier_col).value = courier
        notes.append(
            f"{ws.cell(row=keep, column=name_col).value}(한 주문 송장 {len(others) + 1}개 → "
            f"더 비싼 '{ws.cell(row=keep, column=option_col).value}' 송장 {match_key(tracking)} 하나로, "
            f"{'·'.join(others)}는 같은 주문 다른 박스)"
        )
    return notes


def name_counts(names: Iterable[str]) -> Counter[str]:
    return Counter(name for name in names if name)


def requires_option_guard(name: str, delivery_name_counts: Counter[str], candidate_count: int) -> bool:
    return delivery_name_counts.get(name, 0) > 1 or candidate_count > 1
