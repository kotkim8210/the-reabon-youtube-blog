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
    """경품명 → 발주 품목명 (발주처는 event_supplier로 판정).

    - 백도딱딱이 2·4kg: 제주다팜 발주명 '딱딱이 복숭아 {등급} {kg}kg'
      (2026-07-24 쥬얼리→제주다팜 이관 — 1kg만 쥬얼리 잔류).
    - 복숭아: 거반도·대극천·백도딱딱이(1kg)는 각 전용 품목명(신비 아님!), 신비복숭아만
      거래처 SKU명(_PEACH_COUPANG_SKU, 1·2kg) 또는 '신비복숭아 {kg}kg' 라벨.
      ※ 전용 분기 없이 _peach_label로 폴백하면 백도/대극천 당첨자가 신비로 둔갑함.
    - 그 외(성주참외) → '성주참외 가성비 랜덤과 {kg}kg (R)' (등급 무관)
    """
    text = str(prize or "")
    baekdo = _event_baekdo_product(text)
    if baekdo:
        return baekdo
    if "복숭아" in text:
        from app.processors.kolrabi_order import convert_jeju_baekdo_option
        from app.processors.myeongi_order import (
            _jewelry_baekdo_option,
            _jewelry_daegeukcheon_option,
            _jewelry_geobando_option,
            _jewelry_peach_option,
            _peach_label,
        )
        jeju_baekdo = convert_jeju_baekdo_option(text, "")
        if jeju_baekdo:
            return jeju_baekdo
        return (
            _jewelry_geobando_option(text, "")
            or _jewelry_daegeukcheon_option(text, "")
            or _jewelry_baekdo_option(text, "")
            or _jewelry_peach_option(text, "")
            or _peach_label(text, "")
        )
    kg = _prize_kg(text)
    if not kg:
        return "성주참외 가성비 랜덤과 (R)"
    return f"성주참외 가성비 랜덤과 {kg}kg (R)"


def event_supplier(prize: str) -> str:
    """경품의 발주처: 백도딱딱이는 kg 무관 전량 제주다팜, 나머지는 쥬얼리프룻.

    (2026-08-10) 쥬얼리 백도 발주 중단으로 1kg 당첨자도 제주다팜 2kg 발주.
    """
    if _event_baekdo_product(prize):
        return "jejudapam"
    return "jewelryfruit"


def _find_col(headers: list[str], *needles_groups) -> int | None:
    """헤더 리스트에서 (모든 needle 포함) 조건을 만족하는 첫 컬럼 인덱스."""
    norm = [_norm(h).replace(" ", "") for h in headers]
    for needles in needles_groups:
        for i, h in enumerate(norm):
            if h and all(n in h for n in needles):
                return i
    return None


def parse_winners(csv_bytes: bytes) -> list[dict]:
    text = _decode_csv(csv_bytes)
    rows = [r for r in csv.reader(StringIO(text)) if any(_norm(c) for c in r)]
    if len(rows) < 2:
        raise ValueError("이벤트 당첨자 CSV에 데이터 행이 없습니다.")

    header = rows[0]
    c_prize = _find_col(header, ["경품"], ["상품명"])
    c_name = _find_col(header, ["이름"], ["수령인"], ["받는분"])
    c_phone = _find_col(header, ["연락처"], ["전화"])
    c_addr = _find_col(header, ["주소"])
    c_order = _find_col(header, ["주문아이디"], ["주문번호"], ["주문"])
    c_refund_amt = _find_col(header, ["환불", "금액"], ["취소", "금액"])
    c_refund_date = _find_col(header, ["환불", "날짜"], ["환불", "시간"])

    if c_name is None or c_addr is None:
        raise ValueError("CSV에서 '이름'/'주소' 열을 찾지 못했습니다. 라이브 이벤트 당첨자 원본 CSV인지 확인해주세요.")

    def cell(row, idx):
        return row[idx] if (idx is not None and idx < len(row)) else ""

    entries: list[dict] = []
    skipped_refund = 0
    for row in rows[1:]:
        name = _norm(cell(row, c_name))
        if not name:
            continue

        # 환불/취소 건 제외
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

        prize = _norm(cell(row, c_prize))
        product = event_product_name(prize)
        entries.append({
            "name": name,
            "phone": _norm(cell(row, c_phone)),
            "address": _norm(cell(row, c_addr)),
            "product": product,
            "option": product,
            "qty": "1",
            "memo": "문 앞",
            "order_id": _norm(cell(row, c_order)),
            "supplier": event_supplier(prize),
        })

    # 환불 제외 수는 루프 종료 후 최종값으로 기록 (append 시점 스냅샷이면
    # 환불 행이 명단 끝에 있을 때 집계 누락)
    if entries:
        entries[-1]["_skipped_refund"] = skipped_refund
    return entries


def _labels_for(products: list[str]) -> list[str]:
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
    return labels


def _empty_delivery_bytes() -> bytes:
    """제주다팜 워크북 코어(toss_entries 전용 사용)를 위한 빈 DeliveryList."""
    from io import BytesIO

    from openpyxl import Workbook

    wb = Workbook()
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def process(csv_bytes: bytes) -> list[tuple[bytes, str, dict]]:
    """당첨자 CSV → 발주서 목록. 쥬얼리프룻 + (백도 2·4kg 있으면) 제주다팜 분리 출력."""
    from app.processors.kolrabi_order import process_baekdo
    from app.processors.myeongi_order import _build_jewelry_order_workbook

    entries = parse_winners(csv_bytes)
    skipped_refund = entries[-1].get("_skipped_refund", 0) if entries else 0
    for e in entries:
        e.pop("_skipped_refund", None)

    if not entries:
        raise ValueError("발주할 이벤트 당첨자가 없습니다. (환불/취소 건만 있거나 빈 파일)")

    jewelry_entries = [e for e in entries if e.get("supplier") != "jejudapam"]
    jeju_entries = [e for e in entries if e.get("supplier") == "jejudapam"]
    today = datetime.now(KST).strftime("%Y%m%d")
    results: list[tuple[bytes, str, dict]] = []

    if jewelry_entries:
        output_bytes, _filename, stats = _build_jewelry_order_workbook(jewelry_entries)
        labels = _labels_for([e.get("product", "") for e in jewelry_entries])
        label = "_".join(labels) if labels else "발주"
        filename = f"이벤트당첨_쥬얼리프룻_{label}_발주({today}).xlsx"
        results.append((output_bytes, filename, {
            **stats,
            "supplier": "쥬얼리프룻",
            "product": ("이벤트 " + "·".join(labels)) if labels else "이벤트",
            "winners": len(jewelry_entries),
            "skipped_refund": skipped_refund,
        }))

    if jeju_entries:
        # 백도 2·4kg 당첨자 → 제주다팜 발주서 (2026-07-24 이관과 동일 경로)
        jeju_result = process_baekdo(_empty_delivery_bytes(), toss_entries=jeju_entries)
        if jeju_result:
            jeju_bytes, _fn, jeju_stats = jeju_result
            filename = f"이벤트당첨_제주다팜_백도딱딱이복숭아_발주({today}).xlsx"
            results.append((jeju_bytes, filename, {
                **jeju_stats,
                "supplier": "제주다팜",
                "product": "이벤트 백도딱딱이복숭아(제주다팜)",
                "winners": len(jeju_entries),
                "skipped_refund": 0 if jewelry_entries else skipped_refund,
            }))

    if not results:
        raise ValueError("발주할 이벤트 당첨자가 없습니다.")
    return results
