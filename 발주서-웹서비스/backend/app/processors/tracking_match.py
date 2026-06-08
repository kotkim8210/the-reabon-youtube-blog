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
