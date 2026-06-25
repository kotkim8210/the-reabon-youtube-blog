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


def event_product_name(prize: str) -> str:
    """경품명 → 쥬얼리 발주 품목명.

    - 신비복숭아 → 거래처 SKU명 (예: '신비복숭아 1kg 중소과' → '신비 복숭아 1kg (15과 내외)').
      쿠팡/토스 신비복숭아와 동일 매핑(_PEACH_COUPANG_SKU) 재사용 — 1·2kg은 SKU, 그 외는 라벨.
    - 그 외(성주참외) → '성주참외 가성비 랜덤과 {kg}kg (R)' (등급 무관)
    """
    text = str(prize or "")
    if "복숭아" in text:
        from app.processors.myeongi_order import _jewelry_peach_option, _peach_label
        return _jewelry_peach_option(text, "") or _peach_label(text, "")
    kg = _prize_kg(text)
    if not kg:
        return "성주참외 가성비 랜덤과 (R)"
    return f"성주참외 가성비 랜덤과 {kg}kg (R)"


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
            "_skipped_refund": skipped_refund,
        })

    return entries


def process(csv_bytes: bytes) -> tuple[bytes, str, dict]:
    from app.processors.myeongi_order import _build_jewelry_order_workbook

    entries = parse_winners(csv_bytes)
    skipped_refund = entries[-1].get("_skipped_refund", 0) if entries else 0
    for e in entries:
        e.pop("_skipped_refund", None)

    if not entries:
        raise ValueError("발주할 이벤트 당첨자가 없습니다. (환불/취소 건만 있거나 빈 파일)")

    output_bytes, _filename, stats = _build_jewelry_order_workbook(entries)

    products = [e.get("product", "") for e in entries]
    labels = []
    if any("참외" in p for p in products):
        labels.append("참외")
    if any("복숭아" in p for p in products):
        labels.append("신비복숭아")
    label = "_".join(labels) if labels else "발주"
    today = datetime.now(KST).strftime("%Y%m%d")
    filename = f"이벤트당첨_쥬얼리프룻_{label}_발주({today}).xlsx"
    stats = {
        **stats,
        "supplier": "쥬얼리프룻",
        "product": ("이벤트 " + "·".join(labels)) if labels else "이벤트",
        "winners": len(entries),
        "skipped_refund": skipped_refund,
    }
    return output_bytes, filename, stats
