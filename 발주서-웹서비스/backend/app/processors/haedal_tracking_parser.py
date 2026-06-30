"""Utilities for parsing 해달/한진 tracking reply workbooks.

거래처 회송 양식이 바뀌어도 헤더명 기반으로 주요 열을 찾는다.
기존 구양식(P~V 숫자 스캔)도 fallback으로 유지한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class HaedalColumns:
    start_row: int = 1
    name: int = 1
    phone: int = 2
    address: int = 6
    product: int = 14
    tracking: int | None = None
    courier: int | None = None


def _key(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", "", str(value).strip()).lower()


def _contains_any(header: str, needles: tuple[str, ...]) -> bool:
    return any(needle in header for needle in needles)


def _valid_tracking(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    # Excel이 숫자로 저장한 경우 462345127333.0 처럼 보일 수 있어 정리한다.
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    digits = re.sub(r"\D", "", text)
    if re.fullmatch(r"\d{10,14}", digits):
        return digits
    return ""


def _tracking_number_candidate(value: object) -> str:
    """Return a likely tracking number from a cell value.

    해달/한진 회신 파일은 송장 헤더가 없거나 엉뚱한 헤더 아래에 12자리
    송장번호가 들어오는 경우가 있다. 전화번호/안심번호/우편번호 오탐을 줄이기 위해
    행 전체 fallback에서는 12자리 숫자 중 '0'으로 시작하지 않는 값만 후보로 본다.
    (안심번호 0502/0503/0504-XXXX-XXXX = 12자리라 운송장으로 오인되던 버그 차단)
    """
    tracking = _valid_tracking(value)
    if re.fullmatch(r"\d{12}", tracking) and not tracking.startswith("0"):
        return tracking
    return ""


def detect_haedal_columns(ws, max_header_rows: int = 10) -> HaedalColumns:
    """Find important columns from Korean headers, with legacy defaults.

    New format example:
    A 수취인명 / C 수취인 주소 / D 상품명 / H 수취인 이동통신 / N 송장번호

    Legacy fallback:
    A name / B phone / F address / N product / P~V tracking scan
    """
    best: dict[str, int] = {}
    best_row = 0
    best_score = 0

    limit = min(getattr(ws, "max_row", 1), max_header_rows)
    for row_idx in range(1, limit + 1):
        found: dict[str, int] = {}
        for col_idx in range(1, getattr(ws, "max_column", 1) + 1):
            header = _key(ws.cell(row=row_idx, column=col_idx).value)
            if not header:
                continue
            if not found.get("tracking") and _contains_any(header, ("송장번호", "운송장번호", "출고번호")):
                found["tracking"] = col_idx
            if (
                not found.get("name")
                and _contains_any(header, ("수취인명", "수령인명", "받는분", "받으시는분", "수하인명", "수령인", "수취인", "받는사람"))
                and not _contains_any(header, ("연락처", "전화", "번호", "주소", "우편", "일자", "메모"))
            ):
                found["name"] = col_idx
            if not found.get("phone") and (
                _contains_any(header, (
                    "수취인이동통신", "수취인휴대", "수취인전화", "수령인전화", "받는분전화", "휴대폰", "전화번호",
                    "수령인연락처", "수취인연락처", "받는분연락처",
                ))
                and not _contains_any(header, ("주문자", "주문인", "발송", "보내는"))
                and "연락처2" not in header  # '수령인연락처2'(보조)는 건너뛰고 '연락처1'(주)를 잡는다
            ):
                found["phone"] = col_idx
            if not found.get("address") and _contains_any(header, ("수취인주소", "수령인주소", "받는분주소", "주소")):
                found["address"] = col_idx
            # '상품명'은 잡되 '상품주문번호'(번호/주문/코드 포함)는 제외 → 상품명 열을 정확히 찾는다
            if not found.get("product") and (
                _contains_any(header, ("상품명", "품명", "제품명"))
                or (_contains_any(header, ("상품", "제품")) and not _contains_any(header, ("번호", "주문", "코드")))
            ):
                found["product"] = col_idx
            if not found.get("courier") and _contains_any(header, ("택배사", "택배회사", "배송사", "택배사명")):
                found["courier"] = col_idx

        score = len(found) + (2 if "tracking" in found else 0)
        if score > best_score:
            best = found
            best_row = row_idx
            best_score = score

    # 헤더가 일부라도 있으면 데이터 시작은 다음 행. 아니면 기존 방식 유지.
    if best:
        return HaedalColumns(
            start_row=best_row + 1,
            name=best.get("name", 1),
            phone=best.get("phone", 2),
            address=best.get("address", 6),
            product=best.get("product", 14),
            tracking=best.get("tracking"),
            courier=best.get("courier"),
        )

    a1 = _key(ws.cell(row=1, column=1).value)
    start_row = 2 if any(token in a1 for token in ("받", "분", "수령", "수취")) else 1
    return HaedalColumns(start_row=start_row)


# 택배사명 식별용 키워드 (택배사 셀은 짧으므로 길이 제한과 함께 쓴다 → 주소/이름 오탐 방지)
_COURIER_HINTS = ("택배", "대한통운", "우체국", "로젠", "한진", "롯데", "현대", "cj", "logen", "epost")


def find_courier_in_row(
    ws,
    row_idx: int,
    courier_col: int | None = None,
    skip_cols: tuple[int, ...] = (),
) -> str:
    """행에서 택배사명을 찾는다.

    택배사 열(헤더 감지)이 있으면 그 값을 쓴다. 없으면(거래처가 엉뚱한 열-예: '지불조건'-에
    택배사를 적은 경우) 짧은 셀 값들 중 택배 키워드가 든 것을 찾는다. 이름/전화/주소/상품/송장
    열은 제외하고, 길이 ≤ 12 인 셀만 봐서 '한진아파트' 같은 주소 오탐을 막는다.
    """
    if courier_col:
        value = ws.cell(row=row_idx, column=courier_col).value
        return str(value).strip() if value is not None else ""

    skip = set(skip_cols)
    for col_idx in range(1, getattr(ws, "max_column", 1) + 1):
        if col_idx in skip:
            continue
        value = ws.cell(row=row_idx, column=col_idx).value
        if value is None:
            continue
        text = str(value).strip()
        compact = re.sub(r"\s+", "", text).lower()
        if not compact or len(compact) > 12:
            continue
        if any(hint in compact for hint in _COURIER_HINTS):
            return text
    return ""


def find_tracking_in_row(ws, row_idx: int, tracking_col: int | None = None) -> str:
    """Return tracking number for a row.

    송장 열(출고번호/송장번호 등)이 감지되면 **그 열만 신뢰**한다.
    비어 있으면 빈값을 반환해 그 행은 건너뛴다 — 절대 행 스캔으로 추측하지 않는다.
    (예전엔 빈 행에서 안심번호(0504-XXXX-XXXX, 12자리)를 운송장으로 오인해
     쿠팡에 잘못 등록 → 출고지연이 발생했음.)

    송장 열을 헤더에서 못 찾은 경우(tracking_col is None)에만 fallback:
      1. 옛 해달 양식 P(16)~V(22) 숫자 스캔
      2. 행 전체에서 12자리 숫자(0으로 시작=전화/안심번호 제외) 중 '4' 우선
    """
    if tracking_col:
        return _valid_tracking(ws.cell(row=row_idx, column=tracking_col).value)

    for col_idx in range(16, 23):  # P(16) ~ V(22), old 해달 reply fallback
        tracking = _valid_tracking(ws.cell(row=row_idx, column=col_idx).value)
        if tracking and not tracking.startswith("0"):
            return tracking

    candidates = []
    for col_idx in range(1, getattr(ws, "max_column", 1) + 1):
        tracking = _tracking_number_candidate(ws.cell(row=row_idx, column=col_idx).value)
        if tracking:
            candidates.append(tracking)
    for tracking in candidates:
        if tracking.startswith("4"):
            return tracking
    return candidates[0] if candidates else ""
