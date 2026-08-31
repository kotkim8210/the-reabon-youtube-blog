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


def event_supplier(prize: str) -> str:
    """이벤트 당첨자 발주처.

    기본은 제주다팜이지만, **발주처가 제이비티인 품목(청사과/아오리)은 제이비티**로 보낸다
    (2026-08-31 — 발주처 이관을 이벤트 경로도 따라가야 엉뚱한 거래처로 발주된다).
    """
    if _jbt_event_product(prize):
        return "jbt"
    return "jejudapam"


def _jejudapam_event_product(prize: str) -> str | None:
    """경품명을 제주다팜 발주 품목명으로 변환. 취급 품목이 아니면 None.

    발주서에 거래처가 아는 판매옵션명이 찍혀야 해서, 제주다팜 변환기를 차례로 시도한다.
    (미니밤호박·청사과(아오리)·홍감자·콜라비 …)
    """
    from app.processors.kolrabi_order import (
        convert_bamhobak_option,
        convert_hongro_option,
        convert_potato_option,
    )

    # 청사과(아오리)는 제이비티 이관 → _jbt_event_product가 먼저 처리한다.
    text = str(prize or "")
    for converter in (convert_bamhobak_option, convert_hongro_option, convert_potato_option):
        converted = converter(text, "")
        if converted:
            return converted
    return None


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
    incomplete: list[str] = []   # 이름·주소가 비어 발주 불가한 당첨자(고객 확인 필요)
    for row in rows[1:]:
        name = _norm(cell(row, c_name))
        address = _norm(cell(row, c_addr))
        if not name or not address:
            # 개인정보 미확인/미제공(취소 의심) — 조용히 버리지 말고 화면에 알린다
            order_id = _norm(cell(row, c_order)) or "주문번호없음"
            prize_text = _norm(cell(row, c_prize)) or "경품미상"
            missing = "이름·주소" if not name and not address else ("이름" if not name else "주소")
            incomplete.append(f"{name or '이름없음'}({order_id}, {prize_text}) — {missing} 없음")
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
            "address": address,
            "product": product,
            "option": product,
            "qty": "1",
            "memo": "문 앞",
            "order_id": _order_id_text(cell(row, c_order)),
            "supplier": event_supplier(prize),
        })

    # 환불 제외 수·확인필요 목록은 루프 종료 후 최종값으로 기록 (append 시점 스냅샷이면
    # 해당 행이 명단 끝에 있을 때 집계 누락)
    if entries:
        entries[-1]["_skipped_refund"] = skipped_refund
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


def process(csv_bytes: bytes) -> list[tuple[bytes, str, dict]]:
    """당첨자 CSV → 발주처별 발주서.

    경품의 실제 발주처를 따라간다(2026-08-31): 청사과(아오리)는 **제이비티 양식**,
    그 밖의 경품은 제주다팜 양식. 두 발주처가 섞이면 파일이 2개 나온다.
    이름·주소가 비어 발주할 수 없는 당첨자는 stats['needs_check']로 화면에 표시한다.
    """
    from app.processors.kolrabi_order import _build_jejudapam_order

    entries = parse_winners(csv_bytes)
    skipped_refund = entries[-1].get("_skipped_refund", 0) if entries else 0
    incomplete = entries[-1].get("_incomplete", []) if entries else []
    for e in entries:
        e.pop("_skipped_refund", None)
        e.pop("_incomplete", None)

    if not entries:
        raise ValueError("발주할 이벤트 당첨자가 없습니다. (환불/취소 건만 있거나 빈 파일)")

    today = datetime.now(KST).strftime("%Y%m%d")
    jbt_entries = [e for e in entries if e.get("supplier") == "jbt"]
    jeju_entries = [e for e in entries if e.get("supplier") != "jbt"]
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

    # 환불 제외·확인필요는 첫 파일 통계에 싣는다(화면에 한 번만 보이게)
    first_stats = results[0][2]
    first_stats["skipped_refund"] = skipped_refund
    if incomplete:
        first_stats["needs_check"] = (
            f"{len(incomplete)}건 발주 제외(개인정보 미기재): " + " / ".join(incomplete)
        )
    return results
