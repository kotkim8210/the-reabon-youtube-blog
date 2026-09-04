"""해달 회신 변형 양식 + adminplus popup 리뉴얼 파싱 회귀 (2026-08-03 실사고 2건).

사고 1: 해달이 한진양식 '출고번호' 칸에 택배사(CJ대한통운)를 적고 송장번호는
  옆 칸(특기사항)에 넣어 회신 → 헤더로 감지한 송장 열만 신뢰하는 로직이 전 행을
  빈값 처리("운송장번호를 찾을 수 없습니다").
사고 2: adminplus 상세 popup 마크업 리뉴얼(product_set_row 테이블)로 구 정규식이
  0건 매칭 → 마진방어 어드민 모니터 전부 "옵션 공급가를 읽지 못했습니다" 오류.
"""

from io import BytesIO

from openpyxl import Workbook

from app.processors.goguma_tracking_api import parse_haedal_file
from app.processors.haedal_tracking_parser import (
    detect_haedal_columns,
    find_courier_in_row,
    find_tracking_in_row,
)
from app.supplier_price_monitor import _parse_adminplus_popup_prices

_HANJIN_HEADERS = [
    "받으시는 분", "받으시는 분 전화", "받는분담당자(선택)", "받는분핸드폰(선택)",
    "받는분우편번호(선택)", "받는분총주소", "보내시는 분", "보내시는 분 전화",
    "보내는분담당자(선택)", "보내는분담당자HP(선택)", "보내는분우편번호(선택)", "보내는분총주소",
    "수량", "품목명", "운임Type", "지불조건", "출고번호", "특기사항", "메모1", "메모2", "메모3", "메모4",
]


def _hanjin_reply(rows: list[dict]) -> "Workbook":
    """한진양식 발주서에 해달이 값을 채워 돌려준 형태의 워크북."""
    wb = Workbook()
    ws = wb.active
    ws.append(_HANJIN_HEADERS)
    for r in rows:
        row = [""] * 22
        row[0] = r.get("name", "")
        row[1] = r.get("phone", "0502-1111-2222")   # 안심번호(12자리) — 송장 오인 금지 대상
        row[4] = "18123"
        row[5] = r.get("address", "경기도 오산시 어딘가")
        row[6] = "식품애착"
        row[7] = "010-5700-7756"
        row[12] = 1
        row[13] = r.get("product", "꿀고구마 3Kg (중상)")
        row[15] = r.get("col_p", "선불")   # 지불조건 칸
        row[16] = r.get("col_q", "")   # 출고번호 칸
        row[17] = r.get("col_r", "")   # 특기사항 칸
        row[18] = "문 앞"
        ws.append(row)
    return wb


def _bytes(wb: Workbook) -> bytes:
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── 사고 1: 출고번호 칸=택배사, 특기사항 칸=송장 ──
def test_courier_in_tracking_column_falls_back_to_row_scan():
    wb = _hanjin_reply([
        {"name": "유빈", "col_q": "CJ대한통운", "col_r": "6994-4411-8913"},
        {"name": "김태희", "col_q": "CJ대한통운", "col_r": "6994-4411-8736"},
    ])
    ws = wb.active
    cols = detect_haedal_columns(ws)
    assert cols.tracking is None            # 전 행 무효 → 열 감지 폐기
    assert cols.courier == 17               # 그 칸은 택배사 열로 재해석
    assert find_tracking_in_row(ws, 2, cols.tracking) == "699444118913"
    assert find_courier_in_row(ws, 2, cols.courier) == "CJ대한통운"


def test_parse_haedal_file_end_to_end_with_shifted_columns():
    data = _bytes(_hanjin_reply([
        {"name": "유빈", "col_q": "CJ대한통운", "col_r": "6994-4411-8913"},
        {"name": "이응동", "col_q": "CJ대한통운", "col_r": "6994-4411-9042"},
    ]))
    entries = parse_haedal_file(data)
    assert [(e["name"], e["tracking"], e["delivery_company_code"]) for e in entries] == [
        ("유빈", "699444118913", "CJGLS"),
        ("이응동", "699444119042", "CJGLS"),
    ]


# ── 회귀: 정상 회신(출고번호 칸에 송장)은 기존대로 그 열만 신뢰 ──
def test_valid_tracking_column_still_trusted():
    wb = _hanjin_reply([
        {"name": "김희정", "col_q": "462345127333"},
        {"name": "빈행자", "col_q": ""},   # 빈 행은 건너뜀(행 스캔 추측 금지 유지)
    ])
    ws = wb.active
    cols = detect_haedal_columns(ws)
    assert cols.tracking == 17
    assert find_tracking_in_row(ws, 2, cols.tracking) == "462345127333"
    assert find_tracking_in_row(ws, 3, cols.tracking) == ""  # 안심번호(B열) 오인 금지


# ── 사고 2: adminplus popup 신 마크업 파싱 (+구 마크업 폴백 유지) ──
_NEW_POPUP = """
<table class="product_set_table"><tbody>
<tr class="product_set_row">
  <td class="col_name"><div><p class="set_item_name">콜라비(정품 300~750g) 3kg</p></div></td>
  <td class="col_stock">994</td>
  <td class="col_price">8,100</td>
  <td class="col_price">12,000</td>
  <td class="col_tax">과세</td>
</tr>
<tr class="product_set_row">
  <td class="col_name"><div><p class="set_item_name">딱딱이 복숭아 중과 2kg</p></div></td>
  <td class="col_stock">10</td>
  <td class="col_price">9,400</td>
  <td class="col_price">14,800</td>
  <td class="col_tax">과세</td>
</tr>
<tr class="product_set_row">
  <td class="col_name"><div><p class="set_item_name">품절옵션 1kg</p></div></td>
  <td class="col_stock">0</td>
  <td class="col_price">품절</td>
  <td class="col_price">-</td>
  <td class="col_tax">과세</td>
</tr>
</tbody></table>
"""

_OLD_POPUP = """
<tr><td style='border-left:0px'>명이나물(대명이) 3kg</td><td>기타</td>
<td style='text-align:right;color:black;font-weight:bold'>21,000</td></tr>
"""


def test_parse_new_adminplus_popup():
    prices = _parse_adminplus_popup_prices(_NEW_POPUP)
    # 첫 col_price(공급가)만 취하고, 비숫자(품절) 옵션은 건너뛴다
    assert prices == {"콜라비(정품 300~750g) 3kg": 8100, "딱딱이 복숭아 중과 2kg": 9400}


# 실서버 마크업(2026-08-03 kkangta55 실측): 셀에 보조 클래스가 붙고 공급가에 ￦, 판매가는 '자율'
_LIVE_POPUP = """
<tr class="product_set_row">
  <td class="col_name"><div class="set_item_name_cell"><div class="set_item_info">
    <p class="set_item_name">콜라비(정품 소과 150~270g) 2kg</p></div></div></td>
  <td class="col_stock"><span class='set_stock_badge is_unlimited'><img alt='무제한' src='/x.svg' /></span></td>
  <td class="col_price set_meta_value is_price">￦6,200</td>
  <td class="col_price set_meta_value">자율</td>
  <td class="col_tax"><span class="tax_badge is_free">비과세</span></td>
</tr>
"""


def test_parse_live_adminplus_popup_with_extra_classes():
    # class 정확일치 정규식이 0건 매칭하던 실사고 회귀 — 보조 클래스·￦ 포함 마크업
    assert _parse_adminplus_popup_prices(_LIVE_POPUP) == {"콜라비(정품 소과 150~270g) 2kg": 6200}


def test_parse_old_adminplus_popup_fallback():
    assert _parse_adminplus_popup_prices(_OLD_POPUP) == {"명이나물(대명이) 3kg": 21000}


# ── 사고 3 (2026-09-04 실사고): 지불조건 칸=송장, 출고번호 칸=택배사('한진') ──
# 배포본에만 있던 _resolve_misaligned_tracking_column은 '출고번호(Q)가 비었을 때'만
# P로 옮기게 돼 있어, Q에 '한진'이 적힌 이 회신에서 전 행이 빈값 처리됐다.
def test_courier_in_q_and_tracking_in_p():
    wb = _hanjin_reply([
        {"name": "이태화", "col_p": "463207503463", "col_q": "한진"},
        {"name": "김성희", "col_p": "463207503474", "col_q": "한진"},
    ])
    ws = wb.active
    cols = detect_haedal_columns(ws)
    assert cols.tracking is None      # Q는 송장 열이 아니다
    assert cols.courier == 17         # Q = 택배사 열
    assert find_tracking_in_row(ws, 2, cols.tracking) == "463207503463"
    assert find_courier_in_row(ws, 2, cols.courier) == "한진"


def test_parse_haedal_file_with_tracking_in_payment_column():
    data = _bytes(_hanjin_reply([
        {"name": "이태화", "col_p": "463207503463", "col_q": "한진"},
        {"name": "신명희", "col_p": "463207503485", "col_q": "한진", "product": "꿀고구마 5Kg (중상)"},
    ]))
    entries = parse_haedal_file(data)
    assert [(e["name"], e["tracking"], e["delivery_company_code"]) for e in entries] == [
        ("이태화", "463207503463", "HANJIN"),
        ("신명희", "463207503485", "HANJIN"),
    ]


# ── 배포본에서 회수한 대응: Q가 통째로 비고 P에만 송장이 있는 회신 ──
def test_empty_q_with_tracking_in_p_uses_p_column():
    wb = _hanjin_reply([
        {"name": "정정순", "col_p": "463207503500"},
        {"name": "박순임", "col_p": "463207503511"},
    ])
    ws = wb.active
    cols = detect_haedal_columns(ws)
    assert cols.tracking == 16
    assert find_tracking_in_row(ws, 2, cols.tracking) == "463207503500"
