"""라이브 이벤트 당첨자 CSV → 쥬얼리프룻(pbfcompany) 발주서.

매주 월요일 라이브 이벤트 당첨자 명단(winners CSV)을 올리면
'가성비 랜덤과 {kg}kg' 품목의 쥬얼리 발주서를 생성한다.

입력 CSV 헤더(예):
  경품명, 별명, 개인 식별 정보 확인, 이름, 연락처, 주소, 주문 아이디,
  구매 금액, 환불/취소 금액, 환불/날짜/시간
"""

import csv
import re
from datetime import datetime, timedelta, timezone
from io import StringIO

KST = timezone(timedelta(hours=9))

# 과일 이벤트 카드(콜라비·명이·토마토 화면 공용) 발주 이력 섹션 — 일반 주문 이력과 분리, 재발주 없이 영구 제외.
# 키 = 주문아이디|발주 품목명. 꿀·호박고구마 경품은 고구마 화면이 goguma_event·hobak_goguma_event 섹션에 따로 기록한다.
EVENT_SECTION = "fruit_event"


def is_goguma_prize(text: object) -> bool:
    """꿀·호박·밤고구마 경품인지 — 전부 해달 발주(고구마·호박고구마 화면)라 과일 이벤트 발주서엔 넣지 않는다."""
    return "고구마" in re.sub(r"\s+", "", str(text or ""))


def _norm(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def _decode_csv(csv_bytes: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp949", "euc-kr", "utf-16"):
        try:
            return csv_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("이벤트 당첨자 CSV 인코딩을 읽지 못했습니다. UTF-8 또는 CP949 CSV로 저장해 다시 올려주세요.")


def _prize_kg(prize: str) -> str:
    m = re.search(r"(\d+(?:\.\d+)?)\s*kg", str(prize or ""), re.IGNORECASE)
    if not m:
        return ""
    try:
        f = float(m.group(1))
        return str(int(f)) if f.is_integer() else str(f)
    except ValueError:
        return m.group(1)


def _event_baekdo_product(prize: str) -> str | None:
    """이벤트 당첨 백도(딱복) 경품 → 제주다팜 발주명 '딱딱이 복숭아 {등급} {kg}kg'.

    쥬얼리프룻 백도 발주는 중단(is_myeongi_baekdo_excluded)이라 당첨자도 전량 제주다팜에서
    발주한다. 제주다팜 취급 규격은 2·4kg뿐이라 **1kg 경품은 2kg로 올려서** 발주한다
    (2026-08-10 사용자 확정 — 이벤트 당첨자에만 적용, 일반 쿠팡 주문 경로는 그대로).
    """
    text = str(prize or "")
    compact = text.replace(" ", "")
    if "백도" not in compact and "딱딱이" not in compact:
        return None
    grade = "대과" if "대과" in compact else "중과"
    kg = _prize_kg(text)
    if kg not in ("2", "4"):
        kg = "2"  # 1kg 경품·무표기 → 제주다팜 최소 규격 2kg
    return f"딱딱이 복숭아 {grade} {kg}kg"


def event_product_name(prize: str) -> str:
    """경품명 → 제주다팜 발주 품목명.

    2026-08-17부터 이벤트 당첨자는 **경품 종류와 무관하게 전량 제주다팜 발주**다.
    1) 백도딱딱이: '딱딱이 복숭아 {등급} {kg}kg' (1kg 경품은 최소 규격 2kg로 승급)
    2) 제주다팜 취급 품목(미니밤호박·청사과(아오리)·홍감자 …): 각 변환기가 판매옵션명으로
    3) 그 밖의 경품: **경품명을 그대로** 발주 품목명으로 사용
       — 종전엔 성주참외로 폴백해 미니밤호박·아오리사과 당첨자가 참외로 둔갑했다.
    """
    text = str(prize or "")
    baekdo = _event_baekdo_product(text)
    if baekdo:
        return baekdo

    jbt = _jbt_event_product(text)
    if jbt:
        return jbt

    jewelry = _jewelry_event_product(text)
    if jewelry:
        return jewelry

    jejudapam = _jejudapam_event_product(text)
    if jejudapam:
        return jejudapam

    # 미지원 경품은 경품명 원문 유지 (엉뚱한 상품으로 둔갑시키지 않는다)
    return _norm(text)


def _jbt_event_product(prize: str) -> str | None:
    """제이비티 발주 품목(청사과/아오리) 경품이면 제이비티 판매옵션명. 아니면 None.

    청사과는 2026-08-27 제주다팜 → 제이비티 이관 — 당첨자 발주도 제이비티 양식으로 나간다.
    """
    from app.processors.tomato_order import jbt_apple_option

    return jbt_apple_option(str(prize or ""), "")


def _jewelry_event_product(prize: str) -> str | None:
    """쥬얼리프룻에서만 파는 경품(햇밤)이면 쥬얼리 발주 품목명. 아니면 None.

    제주다팜엔 햇밤이 없다(adminplus 검색 2026-10-26: 밤고구마·미니밤호박뿐) → 햇밤 당첨자는
    쿠팡 주문과 같은 '햇밤 대 {kg}kg'로 쥬얼리프룻 양식 발주서에 따로 낸다.
    """
    from app.processors.myeongi_order import _jewelry_chestnut_option

    return _jewelry_chestnut_option(str(prize or ""), "")


def event_supplier(prize: str) -> str:
    """이벤트 당첨자 발주처.

    기본은 제주다팜이지만, **발주처가 제이비티인 품목(청사과/아오리)은 제이비티**로 보낸다
    (2026-08-31 — 발주처 이관을 이벤트 경로도 따라가야 엉뚱한 거래처로 발주된다).
    쥬얼리프룻에서만 파는 햇밤은 쥬얼리프룻(2026-10-26).
    """
    if _jbt_event_product(prize):
        return "jbt"
    if _jewelry_event_product(prize):
        return "jewelry"
    return "jejudapam"


def _jejudapam_event_product(prize: str) -> str | None:
    """경품명을 제주다팜 발주 품목명으로 변환. 취급 품목이 아니면 None.

    발주서에 거래처가 아는 판매옵션명이 찍혀야 해서, 제주다팜 변환기를 차례로 시도한다.
    (미니밤호박·청사과(아오리)·홍감자·콜라비 …)
    """
    from app.product_registry import EVENT_PRODUCTS

    # 청사과(아오리)는 제이비티 이관 → _jbt_event_product가 먼저 처리한다.
    # 레지스트리 event_rank 순서로 시도. 등급별 판매옵션만 있는 품목(감홍·태추·황금향·시나노골드·부사)은
    # 라이브 경품명이 '감홍사과1.5kg'처럼 등급 없이 오는 경우가 많다 → 등급이 적혀 있으면 그대로,
    # 없으면 기본값 '중과'로 발주(2026-10-26 감홍 당첨자 — 종전엔 경품명 원문이 나가 거래처가 옵션을 몰랐다).
    text = str(prize or "")
    for product in EVENT_PRODUCTS:
        converter = product.converter()
        converted = converter(text, "")
        if not converted and product.event_default_grade:
            converted = converter(text, EVENT_DEFAULT_GRADE)
        if converted:
            return converted
    return None


EVENT_DEFAULT_GRADE = "중과"


def _find_col(headers: list[str], *needles_groups) -> int | None:
    """헤더 리스트에서 (모든 needle 포함) 조건을 만족하는 첫 컬럼 인덱스."""
    norm = [_norm(h).replace(" ", "") for h in headers]
    for needles in needles_groups:
        for i, h in enumerate(norm):
            if h and all(n in h for n in needles):
                return i
    return None


# ── DeliveryList로 개인정보 미기재 당첨자 채우기 (2026-11-23) ──────────────────────
# 라이브 당첨자 중 '개인 식별 정보 확인'을 안 한 사람은 이름·연락처·주소가 비어 온다. 하지만 주문 아이디(G열)는
# 쿠팡 주문번호라, 같은 주문을 DeliveryList(C열 주문번호)에서 찾으면 받는 사람·주소가 있다.
# 같은 사람 판정: 당첨자 이름/별명이 DeliveryList 구매자/수취인 이름과 70% 이상 같으면(사용자 기준).
# 별명이 '제타로스'처럼 이름과 무관하면 비교가 안 되므로, 그때는 구매 금액 = 결제액까지 같을 때만 채운다
# (주문번호는 주문마다 하나라 금액까지 맞으면 같은 주문 — 2026-11-23 실제 명단 2건이 모두 이 경우).
NAME_MATCH_THRESHOLD = 0.7

# 쿠팡 DeliveryList 표준 열(1부터) — 머리글을 못 찾을 때만 쓴다.
_DL_DEFAULT_COLS = {
    "order": 3, "amount": 19, "buyer": 25, "receiver": 27, "phone": 28, "zipcode": 29, "address": 30, "memo": 31,
}
_DL_HEADER_NEEDLES = {
    "order": ("주문번호",),
    "amount": ("결제액",),
    "buyer": ("구매자",),
    "receiver": ("수취인이름",),
    "phone": ("수취인전화번호",),
    "zipcode": ("우편번호",),
    "address": ("수취인주소",),
    "memo": ("배송메세지",),
}


def is_delivery_list(xlsx_bytes: bytes) -> bool:
    """쿠팡 DeliveryList(주문번호·수취인 열이 있는 엑셀)인지 — 여러 파일을 한 칸에 올릴 때 구분용."""
    from io import BytesIO

    from openpyxl import load_workbook

    try:
        wb = load_workbook(filename=BytesIO(xlsx_bytes), read_only=True, data_only=True)
    except Exception:
        return False
    try:
        first = next(wb.active.iter_rows(min_row=1, max_row=1, values_only=True), ())
    finally:
        wb.close()
    header = "".join(_norm(h).replace(" ", "") for h in first if h is not None)
    return "주문번호" in header and "수취인" in header


def build_delivery_lookup(delivery_files: list[bytes] | None) -> dict[str, dict]:
    """DeliveryList 여러 개 → {주문번호: 받는 사람 정보}. 한 주문이 여러 줄이면 결제액은 더한다."""
    from io import BytesIO

    from openpyxl import load_workbook

    from app.processors.issued_orders import normalize_order_id

    lookup: dict[str, dict] = {}
    for data in delivery_files or []:
        wb = load_workbook(filename=BytesIO(data), read_only=True, data_only=True)
        try:
            rows = wb.active.iter_rows(values_only=True)
            header = [(_norm(h).replace(" ", "")) for h in next(rows, ())]
            cols: dict[str, int] = {}
            for field, needles in _DL_HEADER_NEEDLES.items():
                idx = next((i for i, h in enumerate(header) if h and all(n in h for n in needles)), None)
                cols[field] = idx if idx is not None else _DL_DEFAULT_COLS[field] - 1

            def get(row, field):
                i = cols[field]
                return row[i] if i < len(row) else None

            for row in rows:
                oid = normalize_order_id(get(row, "order"))
                if not oid:
                    continue
                try:
                    amount = int(float(str(get(row, "amount") or "0").replace(",", "")))
                except ValueError:
                    amount = 0
                if oid in lookup:
                    lookup[oid]["amount"] += amount
                    continue
                lookup[oid] = {
                    "buyer": _norm(get(row, "buyer")),
                    "receiver": _norm(get(row, "receiver")),
                    "phone": _norm(get(row, "phone")),
                    "zipcode": _norm(get(row, "zipcode")),
                    "address": _norm(get(row, "address")),
                    "memo": _norm(get(row, "memo")),
                    "amount": amount,
                }
        finally:
            wb.close()
    return lookup


def _name_similarity(a: str, b: str) -> float:
    """이름 유사도 0~1. 당첨자 별명이 '유*희'처럼 가려져 오면 '*'는 아무 글자와 같다고 본다."""
    from difflib import SequenceMatcher

    a = re.sub(r"[\s()]", "", str(a or ""))
    b = re.sub(r"[\s()]", "", str(b or ""))
    if not a or not b:
        return 0.0
    if ("*" in a or "*" in b) and len(a) == len(b):
        real = sum(1 for x, y in zip(a, b) if x == y and x != "*")
        if real == 0:
            return 0.0
        return sum(1 for x, y in zip(a, b) if x == y or x == "*" or y == "*") / len(a)
    return SequenceMatcher(None, a, b).ratio()


def _parse_amount(value: object) -> int:
    try:
        return int(float(_norm(value).replace(",", "") or "0"))
    except ValueError:
        return 0


def _match_delivery(order_id: str, names: list[str], amount: int, lookup: dict[str, dict]) -> tuple[dict | None, str]:
    """당첨자 주문번호를 DeliveryList에서 찾아 같은 사람이면 (정보, 근거), 아니면 (None, 못 채운 이유)."""
    record = lookup.get(order_id) if order_id else None
    if record is None:
        return None, "DeliveryList에 같은 주문번호 없음"
    dl_names = [n for n in (record["buyer"], record["receiver"]) if n]
    score = max((_name_similarity(w, d) for w in names for d in dl_names), default=0.0)
    if not record["receiver"] or not record["address"]:
        return None, "DeliveryList에도 받는 사람·주소가 비어 있음"
    if score >= NAME_MATCH_THRESHOLD:
        return record, f"이름 {round(score * 100)}% 일치"
    if amount > 0 and amount == record["amount"]:
        return record, "별명이 이름과 달라 주문번호·결제액 일치로 판정"
    return None, (
        f"DeliveryList 주문번호는 있으나 이름({record['receiver']})·결제액({record['amount']:,}원)이 달라 확인 필요"
    )


def _parse_winners_detail(csv_bytes: bytes, delivery_lookup: dict[str, dict] | None = None) -> dict:
    """당첨자 CSV 1개 → {entries, skipped_refund, incomplete, filled}.

    delivery_lookup(build_delivery_lookup)을 주면 이름·주소가 빈 당첨자를 주문번호로 찾아 채운다.
    """
    text = _decode_csv(csv_bytes)
    rows = [r for r in csv.reader(StringIO(text)) if any(_norm(c) for c in r)]
    if len(rows) < 2:
        raise ValueError("이벤트 당첨자 CSV에 데이터 행이 없습니다.")

    header = rows[0]
    c_prize = _find_col(header, ["경품"], ["상품명"])
    c_name = _find_col(header, ["이름"], ["수령인"], ["받는분"])
    c_nick = _find_col(header, ["별명"], ["닉네임"])
    c_phone = _find_col(header, ["연락처"], ["전화"])
    c_addr = _find_col(header, ["주소"])
    c_order = _find_col(header, ["주문아이디"], ["주문번호"], ["주문"])
    c_amount = _find_col(header, ["구매", "금액"])
    c_refund_amt = _find_col(header, ["환불", "금액"], ["취소", "금액"])
    c_refund_date = _find_col(header, ["환불", "날짜"], ["환불", "시간"])

    if c_name is None or c_addr is None:
        raise ValueError("CSV에서 '이름'/'주소' 열을 찾지 못했습니다. 라이브 이벤트 당첨자 원본 CSV인지 확인해주세요.")

    def cell(row, idx):
        return row[idx] if (idx is not None and idx < len(row)) else ""

    entries: list[dict] = []
    skipped_refund = 0
    incomplete: list[str] = []   # 이름·주소가 비어 발주 불가한 당첨자(고객 확인 필요)
    filled: list[str] = []       # DeliveryList에서 받는 사람·주소를 채운 당첨자
    for row in rows[1:]:
        # 환불/취소 건 제외 — 개인정보가 비었어도 환불이면 채우지 않고 뺀다
        refund_date = _norm(cell(row, c_refund_date))
        refund_amt_raw = _norm(cell(row, c_refund_amt)).replace(",", "")
        refunded = bool(refund_date)
        if not refunded and refund_amt_raw:
            try:
                refunded = float(refund_amt_raw) > 0
            except ValueError:
                refunded = False
        if refunded:
            skipped_refund += 1
            continue

        name = _norm(cell(row, c_name))
        address = _norm(cell(row, c_addr))
        phone = _norm(cell(row, c_phone))
        zipcode = ""
        memo = "문 앞"
        prize = _norm(cell(row, c_prize))
        order_id = _order_id_text(cell(row, c_order))
        if not name or not address:
            nickname = _norm(cell(row, c_nick))
            who = name or nickname or "이름없음"
            reason = ""
            if delivery_lookup is not None:
                record, basis = _match_delivery(
                    order_id, [n for n in (name, nickname) if n], _parse_amount(cell(row, c_amount)), delivery_lookup,
                )
                if record:
                    name, address = record["receiver"], record["address"]
                    phone = record["phone"] or phone
                    zipcode = record["zipcode"]
                    memo = record["memo"] or memo
                    filled.append(f"{who}({order_id}, {prize or '경품미상'}) → {name} · {basis}")
                else:
                    reason = f" · {basis}"
            if not name or not address:
                # 개인정보 미확인/미제공(취소 의심) — 조용히 버리지 말고 화면에 알린다
                missing = "이름·주소" if not name and not address else ("이름" if not name else "주소")
                incomplete.append(
                    f"{who}({order_id or _norm(cell(row, c_order)) or '주문번호없음'}, {prize or '경품미상'}) — {missing} 없음{reason}"
                )
                continue

        product = event_product_name(prize)
        entries.append({
            "name": name,
            "phone": phone,
            "zipcode": zipcode,
            "address": address,
            "product": product,
            "option": product,
            "qty": "1",
            "memo": memo,
            "order_id": order_id,
            "supplier": event_supplier(prize),
        })
    return {"entries": entries, "skipped_refund": skipped_refund, "incomplete": incomplete, "filled": filled}


def parse_winners(csv_bytes: bytes, delivery_lookup: dict[str, dict] | None = None) -> list[dict]:
    """당첨자 CSV → entries (고구마·호박고구마 화면 호환 형식).

    환불 제외 수·확인필요 목록은 마지막 entry의 _skipped_refund·_incomplete에 싣는다.
    """
    detail = _parse_winners_detail(csv_bytes, delivery_lookup)
    entries, incomplete = detail["entries"], detail["incomplete"]
    # 환불 제외 수·확인필요 목록은 루프 종료 후 최종값으로 기록 (append 시점 스냅샷이면
    # 해당 행이 명단 끝에 있을 때 집계 누락)
    if entries:
        entries[-1]["_skipped_refund"] = detail["skipped_refund"]
        entries[-1]["_incomplete"] = incomplete
    elif incomplete:
        # 발주 가능한 당첨자가 하나도 없어도 확인필요 사실은 알려야 한다
        raise ValueError(
            "발주할 이벤트 당첨자가 없습니다. 개인정보 미기재 "
            + str(len(incomplete)) + "건: " + " / ".join(incomplete)
        )
    return entries


def _labels_for(products: list[str]) -> list[str]:
    """발주 품목명들 → 파일명·요약에 쓸 짧은 품목 라벨."""
    labels = []
    if any("참외" in p for p in products):
        labels.append("참외")
    if any("거반도" in p for p in products):
        labels.append("거반도복숭아")
    if any("대극천" in p for p in products):
        labels.append("대극천복숭아")
    if any(("백도" in p) or ("딱딱이" in p) for p in products):
        labels.append("백도딱딱이복숭아")
    if any("신비" in p for p in products):
        labels.append("신비복숭아")
    if any("밤호박" in p for p in products):
        labels.append("미니밤호박")
    if any(("청사과" in p) or ("아오리" in p) for p in products):
        labels.append("청사과")
    if any("홍감자" in p for p in products):
        labels.append("홍감자")
    if any("콜라비" in p for p in products):
        labels.append("콜라비")
    if any("감홍" in p for p in products):
        labels.append("감홍사과")
    if any("태추" in p for p in products):
        labels.append("태추단감")
    if any("황금향" in p for p in products):
        labels.append("황금향")
    if any("시나노" in p for p in products):
        labels.append("시나노골드")
    if any("부사" in p for p in products):
        labels.append("부사사과")
    return labels


def _empty_delivery_bytes() -> bytes:
    """제주다팜 워크북 코어(toss_entries 전용 사용)를 위한 빈 DeliveryList."""
    from io import BytesIO

    from openpyxl import Workbook

    wb = Workbook()
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _order_id_text(value: object) -> str:
    """주문 아이디 정규화.

    라이브 당첨자 CSV를 엑셀로 열었다 저장하면 주문번호가 '3.10263E+12'처럼
    지수표기로 손상된다(유효숫자 소실 → 복원 불가). 그런 값은 발주서에 넣지 않고
    비워서 잘못된 주문번호가 거래처로 나가는 것을 막는다.
    """
    text = _norm(value)
    if not text:
        return ""
    if re.fullmatch(r"\d+(?:\.\d+)?[eE]\+?\d+", text):
        return ""
    return text


def _build_jbt_event_workbook(entries: list[dict], today: str) -> tuple[bytes, str, dict]:
    """제이비티 발주 대상 당첨자 → 제이비티 발주서 양식."""
    from app.processors.tomato_order import _virtual_toss_row, build_main_order_workbook

    rows = [(_virtual_toss_row(entry), "청사과") for entry in entries]
    output_bytes, _filename, stats = build_main_order_workbook(
        filtered_rows=rows,
        has_tomato=False,
        has_chamoe=False,
        has_ddureup=False,
        has_watermelon=False,
        has_apple=True,
    )
    return output_bytes, f"이벤트당첨_제이비티_청사과_발주({today}).xlsx", stats


def process(
    csv_bytes: bytes | list[bytes],
    exclude_keys=None,
    skipped_names: list[str] | None = None,
    skipped_keys: list[str] | None = None,
    issued_keys: list[str] | None = None,
    delivery_files: list[bytes] | None = None,
    csv_names: list[str] | None = None,
) -> list[tuple[bytes, str, dict]]:
    """당첨자 CSV(여러 개 가능) → 발주처별 발주서.

    경품의 실제 발주처를 따라간다(2026-08-31): 청사과(아오리)는 **제이비티 양식**, 햇밤은 쥬얼리프룻,
    그 밖의 경품은 제주다팜 양식. 발주처가 섞이면 파일이 여러 개 나온다.
    당첨자 CSV를 여러 개 주면 한데 모아 발주처별로 한 장씩 만든다(2026-11-23 — 라이브마다 따로 만들던 것).
    delivery_files(DeliveryList)를 주면 이름·주소가 빈 당첨자를 주문번호로 찾아 채운다(_match_delivery).
    그래도 발주할 수 없는 당첨자는 stats['needs_check']로 화면에 표시한다.

    꿀·호박고구마 경품은 해달 발주(고구마·호박고구마 화면 당첨자 칸)라 빼고 needs_check로 알린다
    — 종전엔 경품명 그대로 제주다팜 발주서에 들어가 해달과 이중 발주될 수 있었다(2026-11-16 리뷰).
    exclude_keys: 이전에 발주한 당첨 키(주문아이디|발주 품목명, EVENT_SECTION) — 같은 명단 재업로드 시 영구 제외.
    skipped_names·skipped_keys: 그렇게 뺀 당첨자 이름·키를 담아 준다(화면 표시용).
    issued_keys: 이번 발주서에 실제로 넣은 당첨 키를 담아 준다(호출부가 EVENT_SECTION에 기록).
    """
    from app.processors.issued_orders import KEY_SEP, make_order_key, normalize_order_id
    from app.processors.kolrabi_order import _build_jejudapam_order

    csv_list = [csv_bytes] if isinstance(csv_bytes, (bytes, bytearray)) else list(csv_bytes)
    if not csv_list:
        raise ValueError("라이브 이벤트 당첨자 CSV(winners_raw)를 올려주세요.")
    lookup = build_delivery_lookup(delivery_files) if delivery_files else None
    entries: list[dict] = []
    skipped_refund = 0
    incomplete: list[str] = []
    filled: list[str] = []
    for i, data in enumerate(csv_list):
        try:
            detail = _parse_winners_detail(data, lookup)
        except ValueError as exc:
            if len(csv_list) == 1:
                raise
            name = (csv_names or [])[i] if csv_names and i < len(csv_names) else f"{i + 1}번째 당첨자 파일"
            raise ValueError(f"{name}: {exc}") from exc
        entries.extend(detail["entries"])
        skipped_refund += detail["skipped_refund"]
        incomplete.extend(detail["incomplete"])
        filled.extend(detail["filled"])

    # 같은 명단을 두 번 올린 경우 — 같은 주문아이디·경품은 한 번만
    seen_keys: set[str] = set()
    same_batch_dups: list[str] = []
    unique: list[dict] = []
    for e in entries:
        oid = normalize_order_id(e.get("order_id"))
        key = make_order_key(oid, e.get("product")) if oid else ""
        if key and key in seen_keys:
            same_batch_dups.append(e.get("name") or oid)
            continue
        if key:
            seen_keys.add(key)
        unique.append(e)
    entries = unique

    goguma_names = [
        f"{e.get('name') or '이름없음'}({e.get('product')})" for e in entries if is_goguma_prize(e.get("product"))
    ]
    entries = [e for e in entries if not is_goguma_prize(e.get("product"))]
    goguma_note = (
        f"고구마 경품 {len(goguma_names)}건은 이 발주서에서 뺐습니다 — 꿀고구마는 고구마 화면, "
        f"호박고구마는 호박고구마 화면의 당첨자 칸에서 발주하세요: {', '.join(goguma_names)}"
    ) if goguma_names else ""

    keys = set(exclude_keys or ())
    composite = {k for k in keys if KEY_SEP in k}
    legacy = {k for k in keys if KEY_SEP not in k}
    kept: list[dict] = []
    new_keys: list[str] = []
    dup_names: list[str] = []
    for e in entries:
        oid = normalize_order_id(e.get("order_id"))
        key = make_order_key(oid, e.get("product")) if oid else ""
        if key and (key in composite or oid in legacy):
            dup_names.append(e.get("name") or oid)
            if skipped_keys is not None:
                skipped_keys.append(key if key in composite else oid)
            continue
        kept.append(e)
        if key:
            new_keys.append(key)
    entries = kept
    if skipped_names is not None:
        skipped_names.extend(dup_names)

    if not entries:
        reasons = []
        if dup_names:
            reasons.append(f"이전에 이미 발주한 당첨자 {len(dup_names)}건 제외: {', '.join(dup_names)}")
        if goguma_note:
            reasons.append(goguma_note)
        if incomplete:
            reasons.append(f"개인정보 미기재 {len(incomplete)}건: " + " / ".join(incomplete))
            if lookup is None:
                reasons.append(_DL_HINT)
        if reasons:
            raise ValueError("발주할 이벤트 당첨자가 없습니다. (" + " / ".join(reasons) + ")")
        raise ValueError("발주할 이벤트 당첨자가 없습니다. (환불/취소 건만 있거나 빈 파일)")

    today = datetime.now(KST).strftime("%Y%m%d")
    jbt_entries = [e for e in entries if e.get("supplier") == "jbt"]
    jewelry_entries = [e for e in entries if e.get("supplier") == "jewelry"]
    jeju_entries = [e for e in entries if e.get("supplier") not in ("jbt", "jewelry")]
    results: list[tuple[bytes, str, dict]] = []

    if jeju_entries:
        products = [e.get("product", "") for e in jeju_entries]
        labels = _labels_for(products)
        if not labels:
            raw = _norm(products[0]) if products else "발주"
            labels = ["".join(ch for ch in raw if ch not in '\\/:*?"<>|')[:20].strip() or "발주"]
        label = "_".join(labels)
        result = _build_jejudapam_order(
            _empty_delivery_bytes(),
            lambda *_args: None,   # DeliveryList는 비어 있고 당첨자는 toss_entries로 넣는다
            f"이벤트 {'·'.join(labels)}(제주다팜)",
            f"이벤트당첨_제주다팜_{label}_발주({today}).xlsx",
            jeju_entries,
        )
        if result:
            output_bytes, filename, stats = result
            results.append((output_bytes, filename, {
                **stats,
                "supplier": "제주다팜",
                "winners": len(jeju_entries),
            }))

    if jewelry_entries:
        # 쥬얼리프룻 양식(명이나물 발주서와 동일 템플릿). DeliveryList는 비우고 당첨자를 toss_entries로 넣는다.
        from app.processors import myeongi_order

        output_bytes, _fname, stats = myeongi_order.process(_empty_delivery_bytes(), toss_entries=jewelry_entries)
        label = str(stats.get("product") or "햇밤").replace("+", "_")
        results.append((output_bytes, f"이벤트당첨_쥬얼리프룻_{label}_발주({today}).xlsx", {
            **stats,
            "supplier": "쥬얼리프룻",
            "product": f"이벤트 {stats.get('product') or '햇밤'}(쥬얼리프룻)",
            "winners": len(jewelry_entries),
        }))

    if jbt_entries:
        output_bytes, filename, stats = _build_jbt_event_workbook(jbt_entries, today)
        results.append((output_bytes, filename, {
            **stats,
            "supplier": "제이비티",
            "product": "이벤트 청사과(제이비티)",
            "winners": len(jbt_entries),
        }))

    if not results:
        raise ValueError("발주할 이벤트 당첨자가 없습니다.")

    if issued_keys is not None:
        issued_keys.extend(new_keys)

    # 환불 제외·확인필요는 첫 파일 통계에 싣는다(화면에 한 번만 보이게)
    first_stats = results[0][2]
    first_stats["skipped_refund"] = skipped_refund
    if len(csv_list) > 1:
        first_stats["winner_files"] = len(csv_list)
    if filled:
        first_stats["filled_from_delivery"] = filled
    notes = []
    if incomplete:
        notes.append(f"{len(incomplete)}건 발주 제외(개인정보 미기재): " + " / ".join(incomplete))
        if lookup is None:
            notes.append(_DL_HINT)
    if same_batch_dups:
        notes.append(f"같은 당첨자가 두 번 올라와 {len(same_batch_dups)}건은 한 번만 넣음: {', '.join(same_batch_dups)}")
    if goguma_note:
        notes.append(goguma_note)
    if notes:
        first_stats["needs_check"] = " / ".join(notes)
    return results


_DL_HINT = "DeliveryList(xlsx)를 당첨자 CSV와 같이 올리면 주문번호로 받는 사람·주소를 찾아 채웁니다"
