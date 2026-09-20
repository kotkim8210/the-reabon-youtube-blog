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


def name_counts(names: Iterable[str]) -> Counter[str]:
    return Counter(name for name in names if name)


def requires_option_guard(name: str, delivery_name_counts: Counter[str], candidate_count: int) -> bool:
    return delivery_name_counts.get(name, 0) > 1 or candidate_count > 1
