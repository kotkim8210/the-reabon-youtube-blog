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
    송장번호가 들어오는 경우가 있다. 전화번호와 우편번호 오탐을 줄이기 위해
    행 전체 fallback에서는 12자리 숫자만 후보로 본다.
    """
    tracking = _valid_tracking(value)
    if re.fullmatch(r"\d{12}", tracking):
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
            if not found.get("name") and _contains_any(header, ("수취인명", "수령인명", "받는분", "받으시는분", "수하인명")):
                found["name"] = col_idx
            if not found.get("phone") and (
                _contains_any(header, ("수취인이동통신", "수취인휴대", "수취인전화", "수령인전화", "받는분전화", "휴대폰", "전화번호"))
                and not _contains_any(header, ("주문자", "주문인", "발송", "보내는"))
            ):
                found["phone"] = col_idx
            if not found.get("address") and _contains_any(header, ("수취인주소", "수령인주소", "받는분주소", "주소")):
                found["address"] = col_idx
            if not found.get("product") and _contains_any(header, ("상품명", "품명", "제품명", "상품")):
                found["product"] = col_idx

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
        )

    a1 = _key(ws.cell(row=1, column=1).value)
    start_row = 2 if any(token in a1 for token in ("받", "분", "수령", "수취")) else 1
    return HaedalColumns(start_row=start_row)


def find_tracking_in_row(ws, row_idx: int, tracking_col: int | None = None) -> str:
    """Return tracking number from detected header, legacy range, or row scan.

    Priority:
    1. Detected tracking header column
    2. Legacy P(16) ~ V(22) scan
    3. Any 12-digit number in the row, preferring values that start with 4
    """
    if tracking_col:
        tracking = _valid_tracking(ws.cell(row=row_idx, column=tracking_col).value)
        if tracking:
            return tracking

    for col_idx in range(16, 23):  # P(16) ~ V(22), old 해달 reply fallback
        tracking = _valid_tracking(ws.cell(row=row_idx, column=col_idx).value)
        if tracking:
            return tracking

    candidates = []
    for col_idx in range(1, getattr(ws, "max_column", 1) + 1):
        tracking = _tracking_number_candidate(ws.cell(row=row_idx, column=col_idx).value)
        if tracking:
            candidates.append(tracking)
    for tracking in candidates:
        if tracking.startswith("4"):
            return tracking
    if candidates:
        return candidates[0]
    return ""
