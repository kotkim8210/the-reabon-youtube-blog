"""Phase 1-C 마이그레이션 패리티 테스트.

DEFAULT_RULE_SEEDS(엔진 규칙)가 기존 하드코딩 변환기와 동일한 출력을 내는지 보증.
캐시 언로드 상태 = 하드코딩 폴백 경로, 로드 상태 = 엔진 경로 — 둘이 같아야 한다.
"""

import app.rules_engine as RE
from app.processors import kolrabi_order as K
from app.processors import myeongi_order as M


def _load_seeds():
    by_supplier: dict[str, list[dict]] = {}
    for i, rule in enumerate(RE.DEFAULT_RULE_SEEDS, start=1):
        by_supplier.setdefault(rule["supplier_key"], []).append({**rule, "id": i, "active": 1})
    suppliers = {s["key"]: s for s in RE.DEFAULT_SUPPLIER_SEEDS}
    RE._set_cache_for_test(by_supplier, suppliers)


def _unload():
    RE._loaded = False
    RE._rules_by_supplier = {}
    RE._suppliers = {}


def teardown_function(_fn):
    _unload()


# (함수, args, 기대 출력) — 기대값은 하드코딩 함수의 실측 출력(2026-07-16 캡처)
PARITY_CASES = [
    (K.convert_quantity, ("3kg 1박스",), "콜라비 정품 3kg"),
    (K.convert_quantity, ("1박스 5kg",), "콜라비 정품 5kg"),
    (K.convert_bamhobak_option, ("제주 미니 밤호박 보우짱", "1박스 로얄 정품 1kg"), "제주 미니밤호박 보우짱 로얄과 1kg"),
    (K.convert_potato_option, ("햇 홍감자", "1박스 1kg(중)"), "홍감자 중 2kg"),
    (K.convert_potato_option, ("햇 홍감자", "1박스 3kg(대)"), "홍감자 특 3kg"),
    (M._jewelry_bamhobak_option, ("제주 미니 밤호박 보우짱", "1박스 로얄 정품 3kg"), "미니 밤호박 보우짱 로얄과 3kg"),
    (M._jewelry_bamhobak_option, ("제주 미니 밤호박 보우짱", "1박스 로얄 정품 10kg"), "미니 밤호박 보우짱 로얄과 10kg"),
    (M._jewelry_baekdo_option, ("햇 백도 딱딱이복숭아", "1박스 중과 1kg"), "백도 딱딱이 복숭아 중과 1kg (5-6과 내외)"),
    (M._jewelry_baekdo_option, ("햇 백도 딱딱이복숭아", "1박스 대과 4kg"), "백도 딱딱이 복숭아 대과 4kg (12-17과 내외)"),
    (M._jewelry_daegeukcheon_option, ("노지 대극천", "1박스 로얄대과 2kg"), "대극천 로얄과 2kg (8-20과 내외)"),
    (M._jewelry_daegeukcheon_option, ("노지 대극천", "1박스 로얄소과 1kg"), "대극천 소과 1kg (11-16과 내외)"),
    (M._jewelry_peach_option, ("신비복숭아", "1kg (중소과)"), "신비 복숭아 1kg (15과 내외)"),
    (M._jewelry_peach_option, ("신비복숭아", "2kg (대과)"), "신비 복숭아 2kg (22과 내외)"),
    (M._jewelry_corn_option, ("초당옥수수", "중품 10개입"), "초당옥수수(중품) 10개"),
    (M._jewelry_corn_option, ("초당옥수수", "특품 20개"), "초당옥수수(특품) 20개"),
    (M._apple_corn_option, ("코털삼촌 애플초당옥수수", "특품 5개입"), "애플초당옥수수(특품) 5개"),
    (M._apple_corn_option, ("애플초당옥수수", "특품 15개"), "애플초당옥수수(특품) 15개"),
]


def test_parity_hardcoded_vs_engine():
    for fn, args, want in PARITY_CASES:
        _unload()
        hardcoded = fn(*args)
        _load_seeds()
        engine = fn(*args)
        assert hardcoded == engine == want, (fn.__name__, args, hardcoded, engine, want)


def test_engine_excludes_keep_collisions_safe():
    """제외어가 오분류를 막는지 — 백도는 신비 규칙에 절대 안 걸림, 못난이 밤호박은 엔진 미스."""
    _load_seeds()
    # 백도 텍스트 → 신비 규칙이 아니라 백도 규칙으로
    r = RE.resolve_any("햇 백도 딱딱이복숭아", "1박스 중과 2kg")
    assert r and r["label"] == "백도 딱딱이복숭아", r
    # 애플초당옥수수 → 일반 초당옥수수 규칙이 아니라 애플 규칙(priority 90)으로
    r2 = RE.resolve_any("코털삼촌 애플초당옥수수", "특품 10개입")
    assert r2 and r2["label"] == "애플초당옥수수", r2
    # 못난이 밤호박은 엔진 미스(폴백이 처리) — 로얄과로 둔갑 금지
    assert RE.convert("jewelryfruit", "미니 밤호박 보우짱 못난이", "1박스 3kg") is None


def test_seed_rules_are_complete_dicts():
    """시드 스키마 무결성 — DB insert에 필요한 키가 전부 있는지."""
    required = {
        "supplier_key", "label", "priority", "name_keywords", "exclude_keywords",
        "grades", "kg_allow", "pair_map", "extra_map", "output_template",
        "require_grade", "require_kg", "notes",
    }
    supplier_keys = {s["key"] for s in RE.DEFAULT_SUPPLIER_SEEDS}
    for rule in RE.DEFAULT_RULE_SEEDS:
        assert required.issubset(rule.keys()), rule.get("label")
        assert rule["supplier_key"] in supplier_keys, rule.get("label")
