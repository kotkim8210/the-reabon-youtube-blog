import re
from collections import Counter
from collections.abc import Iterable


def match_key(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", "", str(value).strip())


def normalize_courier_name(value: object, default: str = "") -> str:
    if value is None:
        return default
    courier = str(value).strip()
    if not courier:
        return default
    compact = match_key(courier)
    if re.fullmatch(r"(?i)cj대한통운", compact):
        return "CJ 대한통운"
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
