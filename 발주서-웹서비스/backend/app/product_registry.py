"""제주다팜 상품 레지스트리 — 상품 하나를 한 곳에서 정의한다.

예전엔 제주다팜 상품을 하나 넣을 때 main.py(토스 수집 목록·이력 제외·process_outputs 인자),
tomato_order(토스 수집 분기), kolrabi_order.process_outputs, order_routing, event_order(경품 변환),
tracking_input(품목군·의미키), tomato_tracking(토스 운송장 필터)를 손으로 고쳐야 했고,
하나만 빠져도 그 경로에서 주문이 에러 없이 0건이 됐다(홍로 2026-09 사고, feedback_new_product_checklist).

이제 `JEJU_PRODUCTS`에 항목 하나를 추가하면 위 경로가 전부 이 목록을 돌며 처리한다.
목록 순서 = 발주서 출력 순서 = 토스 수집 판정 순서(앞 항목이 먼저 잡는다)이므로,
판정이 겹치는 상품(감홍 ⊃ '홍사과')은 matcher를 배타적으로 만들 것.

새 상품 추가 순서:
  1. kolrabi_order에 is_jeju_X_order / convert_X_option / process_X 작성(옵션표는 거래처 실측명 그대로)
  2. 아래 JEJU_PRODUCTS에 JejuProduct 한 줄 추가(토스 판매·이벤트·라우팅 여부, 의미키 함수)
  3. 회귀 테스트(test_product_registry가 경로 누락을 잡는다)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from app.processors import kolrabi_order as _ko

SemanticFn = Callable[[str, set], set]


@dataclass(frozen=True)
class TossSpec:
    """토스 주문 수집 규칙. match(상품명, 옵션, 상품명+옵션 공백제거) → 이 상품인가."""

    match: Callable[[str, str, str], bool]
    convert: Callable[[str, str], str | None]
    tag: str  # 토스 주문번호가 없을 때 stable_order_id 접두


@dataclass(frozen=True)
class JejuProduct:
    key: str  # 토스 수집 dict 키 / process_outputs 인자 toss_<key>_entries
    label: str  # 화면·오류 문구용 품목명
    builder: str  # kolrabi_order의 발주서 생성 함수 이름(호출 시점에 찾아 monkeypatch 가능)
    family: str = ""  # 송장 입력 품목군 이름(tracking_input)
    family_match: Callable[[str], bool] | None = None  # 공백 제거된 텍스트 → 이 품목인가
    semantic_keys: SemanticFn | None = None  # (공백 제거 텍스트, 텍스트의 정수 kg 집합) → 의미키
    toss: TossSpec | None = None  # 토스에서도 팔면 수집 규칙
    toss_tracking_keywords: tuple[str, ...] = ()  # 토스 운송장 자동등록 대상 낱말(tomato_tracking)
    routing: Callable[[str, str], bool] | None = None  # 마진방어 발주처 판정(order_routing)에 포함
    event_rank: int | None = None  # 이벤트 경품 변환 순서(작을수록 먼저). None이면 경품 대상 아님
    event_default_grade: bool = False  # 경품명에 등급이 없으면 기본 등급으로 한 번 더 시도
    require_total: bool = False  # True면 발주 건수>0일 때만 출력(콜라비), 아니면 미매칭 경고만 있어도 출력
    enabled: Callable[[], bool] = field(default=lambda: True)  # 시즌아웃 등 발주서 출력 차단

    def build(self, delivery_file_bytes: bytes, toss_entries: list[dict] | None):
        return getattr(_ko, self.builder)(delivery_file_bytes, toss_entries=toss_entries)

    def converter(self) -> Callable[[object, object], str | None]:
        return getattr(_ko, f"convert_{self._conv_name}_option")

    @property
    def _conv_name(self) -> str:
        return _CONVERTER_NAMES.get(self.key, self.key)


_CONVERTER_NAMES = {"baekdo": "jeju_baekdo"}


# ── 토스 수집 규칙 헬퍼 ────────────────────────────────────────────────────────

def _toss_contains(token: str) -> Callable[[str, str, str], bool]:
    return lambda product_name, option, compact: token in compact


def _toss_matcher(matcher_name: str, *, compact_fallback: bool = True) -> Callable[[str, str, str], bool]:
    def match(product_name: str, option: str, compact: str) -> bool:
        matcher = getattr(_ko, matcher_name)
        if matcher(product_name, option):
            return True
        return compact_fallback and matcher(compact, "")

    return match


def _toss_convert(converter_name: str, prefix: str = "") -> Callable[[str, str], str | None]:
    """변환. prefix가 있으면 토스 상품명에 품목 낱말이 빠졌을 때 붙여 한 번 더 시도."""

    def convert(product_name: str, option: str) -> str | None:
        converter = getattr(_ko, converter_name)
        product = converter(product_name, option)
        if not product and prefix:
            product = converter(f"{prefix} {product_name}", option)
        return product

    return convert


def _toss_convert_colrabi(product_name: str, option: str) -> str | None:
    return _ko.convert_quantity(f"{option} {product_name}")  # '콜라비 정품 {kg}kg' (3/5/10kg)


# ── 송장 의미키(tracking_input._semantic_option_keys) ─────────────────────────
# orderlist(거래처 발주명)와 DeliveryList(쿠팡 옵션)의 표기가 달라, 양쪽을 같은 (등급·kg) 키로 묶는다.

def _keys_by_weight(prefix: str) -> SemanticFn:
    return lambda text, weights: {f"{prefix}:{weight}kg" for weight in weights}


def _keys_by_grade_fn(prefix: str, fn_name: str) -> SemanticFn:
    """발주 변환과 같은 (등급, kg) 함수로 키를 만든다 → 별칭('(소)'·'대' 등)까지 일치."""

    def keys(text: str, weights: set) -> set:
        grade, kg = getattr(_ko, fn_name)(text, "")
        return {f"{prefix}:{grade}:{kg}kg"} if kg else set()

    return keys


def _potato_keys(text: str, weights: set) -> set:
    # 홍감자는 발주 매핑(중1→중2, 대3→특3, 대5→특5)으로 orderlist(발주명)와 DeliveryList(쿠팡 원본 옵션)의
    # 등급·kg가 달라진다 → 양쪽 모두 발주명으로 정규화한 키를 쓰면 중량 업 케이스까지 정확히 묶인다.
    converted = _ko.convert_potato_option(text, "")
    return {"potato:" + converted.replace(" ", "")} if converted else set()


def _baekdo_keys(text: str, weights: set) -> set:
    # 제주다팜 백도 2·4kg: 발주명 '딱딱이 복숭아 {등급} {kg}kg'와 쿠팡 '백도… {등급} {kg}kg'의 등급·kg가 같다.
    grade = "대과" if "대과" in text else ("중과" if "중과" in text else "")
    return {f"baekdo:{grade}:{weight}kg" for weight in weights}


def _hongro_keys(text: str, weights: set) -> set:
    # 홍로: 발주명 '가을햇사과(홍사과) 가정용 {등급} 포장재포함 {kg}kg(...)' ↔ 쿠팡 '1박스 {등급} {kg}kg(...)'.
    # '중소과'·'중대과'가 '소과'·'대과'를 포함하므로 긴 것 먼저. 쿠팡 '중과' = 제주다팜 '중대과'.
    grade = next((g for g in _ko._HONGRO_GRADES if g in text), "")
    grade = _ko._HONGRO_GRADE_ALIASES.get(grade, grade)
    kgs = set(re.findall(r"(\d+(?:\.\d+)?)kg", text, flags=re.IGNORECASE))
    return {f"hongro:{grade}:{w}kg" for w in kgs}


def _pear_keys(text: str, weights: set) -> set:
    # 햇 배 선물세트: (보자기 유무·등급·kg) 의미키. '특대과'가 '대과' 포함 → 긴 것 먼저.
    compact = re.sub(r"\s+", "", text)
    if "배선물세트" not in compact:
        return set()
    bojagi = "1" if "보자기" in compact else "0"
    grade = next((g for g in ("특대과", "대과") if g in compact), "")
    kgs = set(re.findall(r"(\d+(?:\.\d+)?)kg", compact, flags=re.IGNORECASE))
    return {f"pear:{bojagi}:{grade}:{w}kg" for w in kgs}


def _contains_any(*tokens: str) -> Callable[[str], bool]:
    return lambda text: any(token in text for token in tokens)


def _is_hongro_text(text: str) -> bool:
    # '감홍사과'에 '홍사과'가 들어 있어 감홍과 배타
    return "감홍" not in text and ("홍로" in text or "홍사과" in text or "가을햇사과" in text)


def _routing_by_converter(converter_name: str) -> Callable[[str, str], bool]:
    return lambda product_name, option_text: bool(getattr(_ko, converter_name)(product_name, option_text))


def _routing_potato(product_name: str, option_text: str) -> bool:
    return bool(_ko.is_jeju_potato_order(product_name, option_text) and _ko.convert_potato_option(product_name, option_text))


# ── 레지스트리 ───────────────────────────────────────────────────────────────
# 순서 = 발주서 출력 순서 = 토스 수집 판정 순서.
# 청사과(아오리)는 2026-08-27 제이비티 이관 — 여기 없음(process_apple은 이력·이벤트 참조용으로만 남음).

JEJU_PRODUCTS: tuple[JejuProduct, ...] = (
    JejuProduct(
        key="colrabi", label="콜라비", builder="process", require_total=True,
        family="kolrabi", family_match=_contains_any("콜라비"), semantic_keys=_keys_by_weight("kolrabi"),
        toss=TossSpec(_toss_contains("콜라비"), _toss_convert_colrabi, "toss-colrabi"),
        toss_tracking_keywords=("콜라비",),
    ),
    JejuProduct(
        key="bamhobak", label="미니밤호박", builder="process_bamhobak",
        family="bamhobak", family_match=_contains_any("밤호박"), semantic_keys=_keys_by_weight("bamhobak"),
        toss=TossSpec(_toss_contains("밤호박"), _toss_convert("convert_bamhobak_option"), "toss-bamhobak"),
        toss_tracking_keywords=("밤호박",),
        routing=_routing_by_converter("convert_bamhobak_option"),
        event_rank=10,
    ),
    JejuProduct(
        key="potato", label="홍감자", builder="process_potato",
        family="potato", family_match=_contains_any("홍감자"), semantic_keys=_potato_keys,
        toss=TossSpec(_toss_contains("홍감자"), _toss_convert("convert_potato_option"), "toss-potato"),
        toss_tracking_keywords=("감자",),
        routing=_routing_potato,
        event_rank=30,
    ),
    JejuProduct(
        # 백도 제주다팜 발주는 2026-08-10을 마지막으로 시즌아웃 → 발주서 출력만 차단(송장·이벤트·마진과 무관)
        key="baekdo", label="백도딱딱이복숭아", builder="process_baekdo",
        enabled=lambda: _ko._baekdo_jeju_season_open(),
        family="baekdo", family_match=_contains_any("백도", "딱딱이"), semantic_keys=_baekdo_keys,
        toss=TossSpec(_toss_contains("백도"), _toss_convert("convert_jeju_baekdo_option"), "toss-baekdo"),
        toss_tracking_keywords=("복숭아",),
        routing=_routing_by_converter("convert_jeju_baekdo_option"),
    ),
    JejuProduct(
        # 홍로사과(가을햇사과) — 청사과(제이비티)·감홍과 배타 판정
        key="hongro", label="홍로사과", builder="process_hongro",
        family="hongro", family_match=_is_hongro_text, semantic_keys=_hongro_keys,
        toss=TossSpec(_toss_matcher("is_jeju_hongro_order", compact_fallback=False),
                      _toss_convert("convert_hongro_option"), "toss-hongro"),
        toss_tracking_keywords=("사과",),
        routing=_routing_by_converter("convert_hongro_option"),
        event_rank=20,
    ),
    JejuProduct(
        key="shinano", label="시나노골드사과", builder="process_shinano",
        family="shinano", family_match=_contains_any("시나노"),
        semantic_keys=_keys_by_grade_fn("shinano", "shinano_grade_and_kg"),
        toss=TossSpec(_toss_matcher("is_jeju_shinano_order"), _toss_convert("convert_shinano_option", "시나노"),
                      "toss-shinano"),
        toss_tracking_keywords=("시나노",),
        routing=_routing_by_converter("convert_shinano_option"),
        event_rank=130, event_default_grade=True,
    ),
    JejuProduct(
        # 황금향(2026-10) — 한진택배 발송(tracking_input._is_hwanggeum_row가 'hwanggeum:' 키로 택배사 기본값)
        key="hwanggeum", label="황금향", builder="process_hwanggeum",
        family="hwanggeum", family_match=_contains_any("황금향"),
        semantic_keys=_keys_by_grade_fn("hwanggeum", "hwanggeum_grade_and_kg"),
        toss=TossSpec(_toss_matcher("is_jeju_hwanggeum_order"), _toss_convert("convert_hwanggeum_option", "황금향"),
                      "toss-hwanggeum"),
        toss_tracking_keywords=("황금향",),
        routing=_routing_by_converter("convert_hwanggeum_option"),
        event_rank=120, event_default_grade=True,
    ),
    JejuProduct(
        key="taechu", label="태추단감", builder="process_taechu",
        family="taechu", family_match=_contains_any("태추"),
        semantic_keys=_keys_by_grade_fn("taechu", "taechu_grade_and_kg"),
        toss=TossSpec(_toss_matcher("is_jeju_taechu_order"), _toss_convert("convert_taechu_option", "태추"),
                      "toss-taechu"),
        toss_tracking_keywords=("태추",),
        routing=_routing_by_converter("convert_taechu_option"),
        event_rank=110, event_default_grade=True,
    ),
    JejuProduct(
        # 감홍사과 — 홍로 판정은 감홍을 제외하므로 홍로 분기에 잡히지 않는다
        key="gamhong", label="감홍사과", builder="process_gamhong",
        family="gamhong", family_match=_contains_any("감홍"),
        semantic_keys=_keys_by_grade_fn("gamhong", "gamhong_grade_and_kg"),
        toss=TossSpec(_toss_matcher("is_jeju_gamhong_order"), _toss_convert("convert_gamhong_option", "감홍"),
                      "toss-gamhong"),
        toss_tracking_keywords=("감홍",),
        routing=_routing_by_converter("convert_gamhong_option"),
        event_rank=100, event_default_grade=True,
    ),
    JejuProduct(
        # 부사사과(2026-11) — 쿠팡 DeliveryList만(토스 미판매, 라우팅·마진은 보류)
        key="busa", label="부사사과", builder="process_busa",
        family="busa", family_match=_contains_any("부사"),
        semantic_keys=_keys_by_grade_fn("busa", "busa_grade_and_kg"),
        event_rank=140, event_default_grade=True,
    ),
    JejuProduct(
        key="pear", label="햇 배 선물세트", builder="process_pear",
        family="pear", family_match=_contains_any("배선물세트"), semantic_keys=_pear_keys,
    ),
)

PRODUCTS_BY_KEY = {product.key: product for product in JEJU_PRODUCTS}
TOSS_PRODUCTS: tuple[JejuProduct, ...] = tuple(p for p in JEJU_PRODUCTS if p.toss)
EVENT_PRODUCTS: tuple[JejuProduct, ...] = tuple(
    sorted((p for p in JEJU_PRODUCTS if p.event_rank is not None), key=lambda p: p.event_rank)
)


def toss_labels() -> str:
    return "·".join(p.label for p in TOSS_PRODUCTS)


def toss_tracking_keywords() -> tuple[str, ...]:
    return tuple(dict.fromkeys(k for p in JEJU_PRODUCTS for k in p.toss_tracking_keywords))


def product_families(text: str) -> set[str]:
    return {p.family for p in JEJU_PRODUCTS if p.family_match and p.family_match(text)}


def semantic_keys(text: str, weights: set) -> set[str]:
    keys: set[str] = set()
    for product in JEJU_PRODUCTS:
        if product.semantic_keys and product.family_match and product.family_match(text):
            keys |= product.semantic_keys(text, weights)
    return keys


def routes_to_jejudapam(product_name: object, option_text: object) -> bool:
    return any(p.routing(product_name, option_text) for p in JEJU_PRODUCTS if p.routing)
