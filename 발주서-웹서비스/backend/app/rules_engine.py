"""상품 매칭 규칙 엔진 (Phase 1-A).

발주처별 상품 매칭(키워드·제외어·등급/kg 추출·치환맵·출력 템플릿)을
DB(product_rules)에서 읽어 해석한다. 목표: 상품 추가/이관을 코드 배포가 아닌
규칙 데이터 수정으로 처리(운영 비용 절감 + 셀프서비스 상용화의 전제).

프로세서(동기 함수)에서 쓸 수 있도록 convert()는 인메모리 캐시 기반 동기 호출이고,
캐시는 앱 시작 시(lifespan)와 규칙 CRUD 후 refresh_rules()로 갱신한다.
캐시가 로드되지 않았거나 매칭 규칙이 없으면 None을 반환해 호출부가
기존 하드코딩 로직으로 폴백하게 한다(운영 안전 최우선).
"""

import logging
import re
import threading
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))

_lock = threading.Lock()
_rules_by_supplier: dict[str, list[dict]] = {}
_suppliers: dict[str, dict] = {}
_loaded = False
_refreshed_at: str | None = None

_KG_RE = re.compile(r"(\d+(?:\.\d+)?)\s*kg", re.IGNORECASE)


class _SafeDict(dict):
    """output_template에 없는 자리표시자는 빈 문자열로 대체."""

    def __missing__(self, key):  # noqa: D105
        return ""


def _normalize(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def _compact(value: object) -> str:
    return re.sub(r"\s+", "", _normalize(value))


def _fmt_kg(raw: str) -> str:
    """'3.0'→'3', '2.5'→'2.5'."""
    try:
        f = float(raw)
    except (TypeError, ValueError):
        return str(raw)
    return str(int(f)) if f.is_integer() else str(f)


def _extract_grade(rule: dict, option_text: str, combined: str) -> str:
    grades = rule.get("grades") or []
    for source in (option_text, combined):
        for g in grades:
            if g and g in source:
                return g
    return ""


def _extract_kg(option_text: str, combined: str) -> str:
    for source in (option_text, combined):
        m = _KG_RE.search(source)
        if m:
            return _fmt_kg(m.group(1))
    return ""


def resolve(supplier_key: str, product_name: object, option_text: object) -> dict | None:
    """매칭 규칙 해석. 반환: {rule_id, label, output, grade, kg} 또는 None(미매칭).

    캐시 미로드 시에도 None — 호출부는 하드코딩 폴백을 유지한다.
    """
    if not _loaded:
        return None
    rules = _rules_by_supplier.get(supplier_key) or []
    if not rules:
        return None

    name_n = _normalize(product_name)
    option_n = _normalize(option_text)
    combined = f"{name_n} {option_n}".strip()
    compact = _compact(combined)

    for rule in rules:
        keywords = rule.get("name_keywords") or []
        if not any(k and _compact(k) in compact for k in keywords):
            continue
        excludes = rule.get("exclude_keywords") or []
        if any(x and _compact(x) in compact for x in excludes):
            continue

        grade = _extract_grade(rule, option_n, combined)
        kg = _extract_kg(option_n, combined)
        if rule.get("require_grade") and not grade:
            continue
        if rule.get("require_kg") and not kg:
            continue
        kg_allow = [str(k) for k in (rule.get("kg_allow") or [])]
        if kg_allow and kg not in kg_allow:
            continue

        pair_map = rule.get("pair_map") or {}
        mapped = pair_map.get(f"{grade}|{kg}")
        if mapped and "|" in mapped:
            grade, kg = mapped.split("|", 1)

        extra = (rule.get("extra_map") or {}).get(f"{grade}|{kg}", "")
        output = (rule.get("output_template") or "").format_map(
            _SafeDict(grade=grade, kg=kg, extra=extra)
        )
        output = re.sub(r"\s{2,}", " ", output).strip()
        if not output:
            continue
        return {
            "rule_id": rule.get("id"),
            "label": rule.get("label"),
            "output": output,
            "grade": grade,
            "kg": kg,
        }
    return None


def convert(supplier_key: str, product_name: object, option_text: object) -> str | None:
    """발주 품목명 변환. 미매칭/캐시 미로드면 None(호출부 하드코딩 폴백)."""
    result = resolve(supplier_key, product_name, option_text)
    return result["output"] if result else None


async def refresh_rules() -> dict:
    """DB에서 활성 규칙을 다시 읽어 캐시 교체. 반환: 상태 요약."""
    global _rules_by_supplier, _suppliers, _loaded, _refreshed_at
    from app import db as database

    suppliers = await database.list_rule_suppliers(include_inactive=False)
    rules = await database.list_product_rules(active_only=True)

    by_supplier: dict[str, list[dict]] = {}
    for rule in rules:
        by_supplier.setdefault(rule["supplier_key"], []).append(rule)
    for bucket in by_supplier.values():
        bucket.sort(key=lambda r: (int(r.get("priority") or 100), int(r.get("id") or 0)))

    with _lock:
        _suppliers = {s["key"]: s for s in suppliers}
        _rules_by_supplier = by_supplier
        _loaded = True
        _refreshed_at = datetime.now(KST).isoformat(timespec="seconds")
    logger.info(
        "규칙 엔진 캐시 갱신: 발주처 %d곳, 규칙 %d건", len(suppliers), len(rules)
    )
    return get_status()


def get_status() -> dict:
    return {
        "loaded": _loaded,
        "suppliers": len(_suppliers),
        "rules": sum(len(v) for v in _rules_by_supplier.values()),
        "refreshed_at": _refreshed_at,
    }


def get_supplier(supplier_key: str) -> dict | None:
    return _suppliers.get(supplier_key)


def _set_cache_for_test(rules_by_supplier: dict[str, list[dict]], suppliers: dict[str, dict] | None = None) -> None:
    """테스트 전용: DB 없이 캐시 주입."""
    global _rules_by_supplier, _suppliers, _loaded, _refreshed_at
    with _lock:
        _rules_by_supplier = {
            k: sorted(v, key=lambda r: (int(r.get("priority") or 100), int(r.get("id") or 0)))
            for k, v in rules_by_supplier.items()
        }
        _suppliers = suppliers or {}
        _loaded = True
        _refreshed_at = "test"
