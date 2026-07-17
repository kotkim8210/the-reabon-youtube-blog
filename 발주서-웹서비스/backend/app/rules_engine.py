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
_COUNT_RE = re.compile(r"(\d+)\s*(?:개입|개|입)")


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


def _extract_count(option_text: str, combined: str) -> str:
    """수량 단위 상품(옥수수 'N개/입') 지원. 없으면 빈 문자열."""
    for source in (option_text, combined):
        m = _COUNT_RE.search(source)
        if m:
            return m.group(1)
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

        template = rule.get("output_template") or ""
        grade = _extract_grade(rule, option_n, combined)
        kg = _extract_kg(option_n, combined)
        count = _extract_count(option_n, combined)
        if rule.get("require_grade") and not grade:
            continue
        if rule.get("require_kg") and not kg:
            continue
        if "{count}" in template and not count:
            # 수량 단위 템플릿인데 'N개/입'을 못 찾음 → 이 규칙은 미매칭
            continue
        kg_allow = [str(k) for k in (rule.get("kg_allow") or [])]
        if kg_allow and kg not in kg_allow:
            continue

        pair_map = rule.get("pair_map") or {}
        mapped = pair_map.get(f"{grade}|{kg}")
        if mapped and "|" in mapped:
            grade, kg = mapped.split("|", 1)

        extra = (rule.get("extra_map") or {}).get(f"{grade}|{kg}", "")
        output = template.format_map(
            _SafeDict(grade=grade, kg=kg, count=count, extra=extra)
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
            "count": count,
        }
    return None


def convert(supplier_key: str, product_name: object, option_text: object) -> str | None:
    """발주 품목명 변환. 미매칭/캐시 미로드면 None(호출부 하드코딩 폴백)."""
    result = resolve(supplier_key, product_name, option_text)
    return result["output"] if result else None


def resolve_any(product_name: object, option_text: object) -> dict | None:
    """전체 발주처를 대상으로 첫 매칭 규칙 해석 (시뮬레이터용).

    발주처는 key 정렬 순으로 평가(결정적). 반환에 supplier_key/supplier_name 포함.
    """
    if not _loaded:
        return None
    for supplier_key in sorted(_rules_by_supplier):
        result = resolve(supplier_key, product_name, option_text)
        if result:
            supplier = _suppliers.get(supplier_key) or {}
            return {
                **result,
                "supplier_key": supplier_key,
                "supplier_name": supplier.get("name") or supplier_key,
            }
    return None


def simulate_delivery(delivery_bytes: bytes, max_rows: int = 500) -> dict:
    """DeliveryList 전 행에 규칙을 적용한 미리보기 (파일 미저장, 발주서 미생성).

    '이 규칙이면 이렇게 발주됩니다'를 보여주는 시뮬레이터의 코어.
    반환: {total, matched, unmatched, truncated, rows[], unmatched_options[]}
    rows: [{row_no, product_name, option, matched, supplier_name, label, output}]
    """
    from io import BytesIO

    from openpyxl import load_workbook

    wb = load_workbook(filename=BytesIO(delivery_bytes), data_only=True, read_only=True)
    ws = wb.active

    rows: list[dict] = []
    matched = 0
    unmatched = 0
    unmatched_options: dict[str, int] = {}
    total = 0
    for row_no, row in enumerate(ws.iter_rows(min_row=2), start=2):
        product_name = _normalize(row[10].value) if len(row) > 10 else ""  # K열
        option = _normalize(row[11].value) if len(row) > 11 else ""        # L열
        if not product_name and not option:
            continue
        total += 1
        result = resolve_any(product_name, option)
        if result:
            matched += 1
        else:
            unmatched += 1
            key = f"{product_name} | {option}".strip(" |")
            unmatched_options[key] = unmatched_options.get(key, 0) + 1
        if len(rows) < max_rows:
            rows.append({
                "row_no": row_no,
                "product_name": product_name,
                "option": option,
                "matched": result is not None,
                "supplier_name": (result or {}).get("supplier_name") or "",
                "label": (result or {}).get("label") or "",
                "output": (result or {}).get("output") or "",
            })
    wb.close()
    return {
        "total": total,
        "matched": matched,
        "unmatched": unmatched,
        "truncated": total > len(rows),
        "rows": rows,
        "unmatched_options": [
            {"text": k, "count": v}
            for k, v in sorted(unmatched_options.items(), key=lambda kv: -kv[1])[:50]
        ],
    }


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


# ── 기본 규칙 시드 (Phase 1-C: 하드코딩 상품의 규칙 데이터화) ─────────────
# 각 규칙은 기존 하드코딩 변환기의 출력과 정확히 일치해야 한다(패리티 테스트로 보증).
# init_db가 (supplier_key, label) 없을 때만 삽입 — 사용자가 화면에서 수정한 규칙은 덮지 않는다.

DEFAULT_SUPPLIER_SEEDS: list[dict] = [
    {"key": "jejudapam", "name": "제주다팜", "courier": "롯데택배", "order_cutoff": "10:00", "delivery_method": "download"},
    {"key": "jewelryfruit", "name": "쥬얼리프룻", "courier": "롯데택배", "order_cutoff": "10:00", "delivery_method": "download"},
]

_GRADES_POTATO = ["왕특", "특대", "특", "대", "중", "소"]

DEFAULT_RULE_SEEDS: list[dict] = [
    # ── 제주다팜 ──
    {
        "supplier_key": "jejudapam", "label": "홍감자", "priority": 100,
        "name_keywords": ["홍감자"], "exclude_keywords": [],
        "grades": _GRADES_POTATO, "kg_allow": [],
        "pair_map": {"중|1": "중|2", "대|3": "특|3", "대|5": "특|5"}, "extra_map": {},
        "output_template": "홍감자 {grade} {kg}kg", "require_grade": 1, "require_kg": 1,
        "notes": "2026-07-13 쥬얼리 품절→제주다팜 이관. 매칭 사용자 확정(중1→중2, 대3→특3, 대5→특5).",
    },
    {
        "supplier_key": "jejudapam", "label": "콜라비", "priority": 100,
        "name_keywords": ["콜라비"], "exclude_keywords": [],
        "grades": [], "kg_allow": ["3", "5", "10"],
        "pair_map": {}, "extra_map": {},
        "output_template": "콜라비 정품 {kg}kg", "require_grade": 0, "require_kg": 1,
        "notes": "제주다팜 콜라비 3/5/10kg.",
    },
    {
        "supplier_key": "jejudapam", "label": "미니밤호박 1kg", "priority": 100,
        "name_keywords": ["밤호박"], "exclude_keywords": [],
        "grades": [], "kg_allow": ["1"],
        "pair_map": {}, "extra_map": {},
        "output_template": "제주 미니밤호박 보우짱 로얄과 {kg}kg", "require_grade": 0, "require_kg": 1,
        "notes": "1kg만 제주다팜(3·5·10kg은 쥬얼리).",
    },
    # ── 쥬얼리프룻 ──
    {
        "supplier_key": "jewelryfruit", "label": "미니밤호박 3·5·10kg", "priority": 100,
        "name_keywords": ["밤호박"], "exclude_keywords": ["못난이"],
        "grades": [], "kg_allow": ["3", "5", "10"],
        "pair_map": {}, "extra_map": {},
        "output_template": "미니 밤호박 보우짱 로얄과 {kg}kg", "require_grade": 0, "require_kg": 1,
        "notes": "2026-06 제주다팜→쥬얼리 이관분. 못난이 등급은 제외(하드코딩 폴백이 처리).",
    },
    {
        "supplier_key": "jewelryfruit", "label": "백도 딱딱이복숭아", "priority": 90,
        "name_keywords": ["백도"], "exclude_keywords": [],
        "grades": ["대과", "중과"], "kg_allow": ["1", "2", "4"],
        "pair_map": {},
        "extra_map": {
            "중과|1": "5-6과 내외", "중과|2": "11-14과 내외", "중과|4": "20-26과 내외",
            "대과|1": "3-4과 내외", "대과|2": "6-8과 내외", "대과|4": "12-17과 내외",
        },
        "output_template": "백도 딱딱이 복숭아 {grade} {kg}kg ({extra})", "require_grade": 1, "require_kg": 1,
        "notes": "'복숭아' 계열 — 신비 규칙보다 우선(priority 90).",
    },
    {
        "supplier_key": "jewelryfruit", "label": "대극천 복숭아", "priority": 90,
        "name_keywords": ["대극천"], "exclude_keywords": [],
        "grades": ["로얄대과", "로얄소과", "로얄과", "대과", "소과"], "kg_allow": ["1", "2"],
        "pair_map": {
            "로얄대과|1": "로얄과|1", "로얄대과|2": "로얄과|2",
            "대과|1": "로얄과|1", "대과|2": "로얄과|2",
            "로얄소과|1": "소과|1", "로얄소과|2": "소과|2",
        },
        "extra_map": {
            "로얄과|1": "4-10과 내외", "로얄과|2": "8-20과 내외",
            "소과|1": "11-16과 내외", "소과|2": "21-32과 내외",
        },
        "output_template": "대극천 {grade} {kg}kg ({extra})", "require_grade": 1, "require_kg": 1,
        "notes": "쿠팡 로얄대과→로얄과, 로얄소과→소과 (2026-07 사용자 확정).",
    },
    {
        "supplier_key": "jewelryfruit", "label": "신비복숭아 1·2kg", "priority": 100,
        "name_keywords": ["신비"], "exclude_keywords": ["백도", "거반도", "납작복숭아", "대극천"],
        "grades": ["중소과", "대과"], "kg_allow": ["1", "2"],
        "pair_map": {},
        "extra_map": {
            "중소과|1": "15과 내외", "중소과|2": "30과 내외",
            "대과|1": "11과 내외", "대과|2": "22과 내외",
        },
        "output_template": "신비 복숭아 {kg}kg ({extra})", "require_grade": 1, "require_kg": 1,
        "notes": "1·2kg만 쥬얼리(3·4kg 제이비티). 제외어=복숭아 오분류 방지.",
    },
    {
        "supplier_key": "jewelryfruit", "label": "초당옥수수", "priority": 100,
        "name_keywords": ["초당옥수수"], "exclude_keywords": ["애플", "미백", "흑찰"],
        "grades": ["중품", "특품"], "kg_allow": [],
        "pair_map": {}, "extra_map": {},
        "output_template": "초당옥수수({grade}) {count}개", "require_grade": 1, "require_kg": 0,
        "notes": "수량 단위(N개/입). 애플초당옥수수는 별도 규칙.",
    },
    {
        "supplier_key": "jewelryfruit", "label": "애플초당옥수수", "priority": 90,
        "name_keywords": ["애플초당옥수수"], "exclude_keywords": [],
        "grades": ["특품", "중품"], "kg_allow": [],
        "pair_map": {}, "extra_map": {},
        "output_template": "애플초당옥수수({grade}) {count}개", "require_grade": 1, "require_kg": 0,
        "notes": "일반 초당옥수수보다 우선(priority 90).",
    },
]


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
