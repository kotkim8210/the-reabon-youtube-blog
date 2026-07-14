"""규칙 엔진(Phase 1-A) 단위/패리티 테스트 — DB 없이 캐시 주입으로 검증."""

import app.rules_engine as RE
from app.processors.kolrabi_order import convert_potato_option

# init_db 시드와 동일한 규칙 (DB 파싱 후 형태)
POTATO_RULE = {
    "id": 1,
    "supplier_key": "jejudapam",
    "label": "홍감자",
    "priority": 100,
    "name_keywords": ["홍감자"],
    "exclude_keywords": [],
    "grades": ["왕특", "특대", "특", "대", "중", "소"],
    "kg_allow": [],
    "pair_map": {"중|1": "중|2", "대|3": "특|3", "대|5": "특|5"},
    "extra_map": {},
    "output_template": "홍감자 {grade} {kg}kg",
    "require_grade": 1,
    "require_kg": 1,
    "active": 1,
}

CASES = [
    ("햇 홍감자 카스테라 햇감자", "1박스 1kg(중)", "홍감자 중 2kg"),
    ("햇 홍감자 카스테라 햇감자", "1박스 3kg(대)", "홍감자 특 3kg"),
    ("햇 홍감자 카스테라 햇감자", "1박스 5kg(대)", "홍감자 특 5kg"),
    ("햇 홍감자 카스테라 햇감자", "1박스 3kg(중)", "홍감자 중 3kg"),
    ("햇 홍감자 카스테라 햇감자", "1박스 5kg(중)", "홍감자 중 5kg"),
]


def _unload():
    RE._loaded = False
    RE._rules_by_supplier = {}
    RE._suppliers = {}


def _load_potato():
    RE._set_cache_for_test({"jejudapam": [dict(POTATO_RULE)]})


def teardown_function(_fn):
    _unload()


def test_engine_matches_seed_rule():
    _load_potato()
    for pn, opt, want in CASES:
        assert RE.convert("jejudapam", pn, opt) == want, (pn, opt)


def test_parity_engine_vs_hardcoded_fallback():
    """엔진 경로와 하드코딩 폴백 경로가 동일 결과 — PoC 전환 안전성의 핵심."""
    for pn, opt, want in CASES:
        _unload()
        fallback = convert_potato_option(pn, opt)  # 캐시 미로드 → 하드코딩
        _load_potato()
        engine = convert_potato_option(pn, opt)    # 캐시 로드 → 엔진
        assert fallback == engine == want, (pn, opt, fallback, engine)


def test_unloaded_cache_returns_none():
    _unload()
    assert RE.convert("jejudapam", "홍감자", "3kg(대)") is None


def test_exclude_keywords_block_match():
    rule = dict(POTATO_RULE, exclude_keywords=["수미"])
    RE._set_cache_for_test({"jejudapam": [rule]})
    assert RE.convert("jejudapam", "수미 홍감자", "3kg(대)") is None
    assert RE.convert("jejudapam", "햇 홍감자", "3kg(대)") == "홍감자 특 3kg"


def test_priority_order_first_match_wins():
    special = dict(
        POTATO_RULE, id=2, priority=10, label="홍감자-특판",
        name_keywords=["홍감자", "특판"], output_template="특판 홍감자 {kg}kg",
        require_grade=0, pair_map={},
    )
    RE._set_cache_for_test({"jejudapam": [dict(POTATO_RULE), special]})
    # priority 10 규칙이 먼저 — 같은 텍스트라도 특판 템플릿 적용
    assert RE.convert("jejudapam", "홍감자", "3kg(대)") == "특판 홍감자 3kg"


def test_kg_allow_and_require_filters():
    rule = dict(POTATO_RULE, kg_allow=["3", "5"])
    RE._set_cache_for_test({"jejudapam": [rule]})
    assert RE.convert("jejudapam", "홍감자", "10kg(중)") is None  # kg_allow 밖
    assert RE.convert("jejudapam", "홍감자", "박스만") is None    # require_kg인데 kg 없음
    assert RE.convert("jejudapam", "홍감자", "3kg(중)") == "홍감자 중 3kg"
