"""발주 이력 기반 중복발주 방지 헬퍼.

발주서를 생성할 때 포함된 주문번호를 DB(issued_order_items)에 기록하고,
다음 생성 시 '오늘 이전 날짜'에 기록된 주문번호를 입력(DeliveryList/토스 entries)에서
미리 걸러낸다. 같은 날 재생성은 걸러지지 않는다(아침 재출력·추가발주 워크플로 보존).

키는 **주문번호 + 옵션** 복합키 'order_id|옵션(공백제거)'.
한 주문번호로 여러 옵션을 사면(쿠팡은 가능) 주문번호만으로는 구분이 안 돼,
어제 발주한 A옵션 때문에 오늘 새로 산 B옵션까지 통째로 빠졌다
(2026-08-17 김희조 청사과 소과 5kg/대과 5kg 동일 주문번호 사고).

과거에 주문번호 단독으로 기록된 이력(파이프 없는 키)은 그대로 존중해
그 주문번호 전체를 제외한다 — 키 스킴 변경으로 중복발주가 나지 않게 하는 하위호환.
"""
import re
from datetime import date, timedelta
from io import BytesIO

from openpyxl import load_workbook

KEY_SEP = "|"

# 발주서에 넣은 뒤 이만큼 영업일(주말 제외)이 지났는데도 주문이 아직 DeliveryList(미출고 목록)·
# 토스 결제완료에 남아 있으면, 거래처가 그 발주서를 처리하지 않은 것으로 보고 **자동으로 다시 넣는다**.
# 종전엔 '이전 발주분'으로 영원히 제외하고 경고만 띄웠는데, 경고를 못 보고 넘어가 주문이 며칠씩 묻혔다
# (2026-09-09 임재숙 콜라비, 2026-10-08 해달 휴무일에 만든 호박고구마 발주서 2건이 10/12까지 누락).
# 당일·다음 영업일은 그대로 제외한다 — 거래처가 전날 발주분을 출고하고 운송장이 올라가기까지의
# 하루 동안 중복 발주가 나가면 안 되기 때문(2026-08-18 132건 중복 사고).
# 평일만 세고 공휴일은 빼지 않는다: 공휴일을 빼면 10/8(목)→10/12(월)이 1영업일이 돼 같은 사고가 재발한다.
STALE_BUSINESS_DAYS = 2


def business_days_since(issued_ymd: str, today_ymd: str) -> int:
    """issued_ymd 다음 날부터 today_ymd까지의 평일(월~금) 수. 날짜가 깨졌으면 0(=계속 제외)."""
    try:
        d = date.fromisoformat(str(issued_ymd)[:10])
        end = date.fromisoformat(str(today_ymd)[:10])
    except ValueError:
        return 0
    count = 0
    while d < end:
        d += timedelta(days=1)
        if d.weekday() < 5:
            count += 1
    return count


# 발주 마감(KST). 이 시각 이후나 주말에 만든 발주서는 거래처가 다음 영업일에야 받으므로
# 재발주 기산일을 다음 영업일로 본다 — 안 그러면 월요일 16시 발주분이 수요일 아침에 벌써 재발주된다(리뷰 지적).
ISSUE_CUTOFF = (10, 30)


def effective_issue_date(issued_on: str, created_at_utc: str | None) -> str:
    """거래처가 그 발주서를 '받은 날'(기산일). 마감 후·주말 생성이면 다음 영업일, 아니면 issued_on."""
    try:
        base = date.fromisoformat(str(issued_on)[:10])
    except ValueError:
        return str(issued_on)
    late = base.weekday() >= 5
    if created_at_utc:
        try:
            from datetime import datetime, timedelta as _td
            kst = datetime.fromisoformat(str(created_at_utc)[:19]) + _td(hours=9)
            if kst.date() == base and (kst.hour, kst.minute) >= ISSUE_CUTOFF:
                late = True
        except ValueError:
            pass
    if not late:
        return base.isoformat()
    d = base + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.isoformat()


def stale_issued_keys(
    issued_dates: dict[str, str],
    today_ymd: str,
    min_business_days: int = STALE_BUSINESS_DAYS,
) -> set[str]:
    """발주 이력(키 → 발주일) 중 영업일 기준 min_business_days 이상 지난 키 — 자동 재발주 대상."""
    return {
        key for key, ymd in (issued_dates or {}).items()
        if business_days_since(ymd, today_ymd) >= min_business_days
    }


def normalize_order_id(value) -> str:
    """주문번호를 문자열로 정규화. 엑셀이 숫자로 읽은 경우(float/int) 지수표기·소수점 방지."""
    if value is None:
        return ""
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value)
    return str(value).strip()


def normalize_option(value) -> str:
    """옵션 문자열 정규화 — 공백 완전 제거.

    프로세서마다 옵션을 저장하는 형태(공백 축약/제거)가 조금씩 달라, 기록·필터 양쪽에서
    공백을 모두 지운 형태로 맞춰야 같은 옵션이 같은 키가 된다.
    """
    if value is None:
        return ""
    return re.sub(r"\s+", "", str(value).strip())


def make_order_key(order_id, option_text) -> str:
    """'주문번호|옵션' 복합키. 옵션이 없으면 주문번호만(과거 형태와 동일)."""
    oid = normalize_order_id(order_id)
    if not oid:
        return ""
    option = normalize_option(option_text)
    return f"{oid}{KEY_SEP}{option}" if option else oid


def _split_exclusions(exclude_keys: set[str]) -> tuple[set[str], set[str]]:
    """제외 집합을 (복합키, 주문번호 단독 레거시키)로 나눈다."""
    composite = {k for k in exclude_keys if KEY_SEP in k}
    legacy = {k for k in exclude_keys if KEY_SEP not in k}
    return composite, legacy


def filter_delivery_by_issued(
    delivery_bytes: bytes,
    exclude_order_ids: set[str],
    skipped_names: list[str] | None = None,
    skipped_keys: list[str] | None = None,
    reissue_keys: set[str] | None = None,
    reissued: list[tuple[str, str]] | None = None,
) -> tuple[bytes, int]:
    """DeliveryList에서 이미 발주된 주문번호(C열) 행을 제거한 bytes와 제거 건수를 반환.

    skipped_names를 넘기면 제거된 행의 수취인 이름(AA열)을 담아준다 —
    무엇이 왜 빠졌는지 사용자에게 보여 침묵 제외를 방지.
    reissue_keys: 자동 재발주 대상 키(영업일 2일↑ 지났는데 아직 미출고). 그 행은 **지우지 않고**
    남기되 reissued에 (받는분, 키)를 담아 화면에 '미출고 재발주'로 표시한다.
    """
    if not exclude_order_ids and not reissue_keys:
        return delivery_bytes, 0
    composite, legacy = _split_exclusions(exclude_order_ids or set())
    re_composite, re_legacy = _split_exclusions(reissue_keys or set())
    wb = load_workbook(filename=BytesIO(delivery_bytes))
    ws = wb.active
    to_delete = []
    for row_idx in range(2, ws.max_row + 1):
        order_id = normalize_order_id(ws.cell(row=row_idx, column=3).value)  # C열 = 주문번호
        if not order_id:
            continue
        option = ws.cell(row=row_idx, column=12).value  # L열 = 옵션
        if not normalize_option(option):
            option = ws.cell(row=row_idx, column=11).value  # 옵션이 비면 K열 상품명
        # 복합키(주문번호+옵션)가 맞거나, 과거 주문번호 단독 기록이면 제외
        key = make_order_key(order_id, option)
        if key in composite or order_id in legacy:
            to_delete.append(row_idx)
            if skipped_names is not None:
                name = str(ws.cell(row=row_idx, column=27).value or "").strip()  # AA열 = 수취인이름
                skipped_names.append(name or order_id)
            if skipped_keys is not None:
                skipped_keys.append(key if key in composite else order_id)
        elif reissued is not None and (key in re_composite or order_id in re_legacy):
            name = str(ws.cell(row=row_idx, column=27).value or "").strip()
            reissued.append((name or order_id, key if key in re_composite else order_id))
    if not to_delete:
        return delivery_bytes, 0
    for row_idx in reversed(to_delete):
        ws.delete_rows(row_idx)
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output.read(), len(to_delete)


def filter_entries_by_issued(
    entries: list[dict],
    exclude_order_ids: set[str],
    skipped_names: list[str] | None = None,
    reissue_keys: set[str] | None = None,
    reissued: list[tuple[str, str]] | None = None,
) -> tuple[list[dict], int]:
    """토스/올웨이즈/테무/쿠팡API entry 목록에서 이미 발주된 order_id를 제거.

    reissue_keys에 해당하는 entry는 남기고 reissued에 (이름, 키)를 담는다(filter_delivery_by_issued와 동일).
    """
    if not entries or (not exclude_order_ids and not reissue_keys):
        return entries, 0
    composite, legacy = _split_exclusions(exclude_order_ids or set())
    re_composite, re_legacy = _split_exclusions(reissue_keys or set())
    kept = []
    for entry in entries:
        order_id = normalize_order_id(entry.get("order_id"))
        # 옵션 원문과 변환된 발주명 두 형태 모두로 대조한다 — 쿠팡 API 경로는 예전에 변환명으로 기록했고
        # 지금은 원문(DeliveryList L열과 동일)으로 기록하므로, 둘 다 봐야 과거 기록·교차 경로가 전부 걸린다.
        keys = [make_order_key(order_id, opt) for opt in (entry.get("option"), entry.get("product")) if order_id and opt]
        keys = list(dict.fromkeys(k for k in keys if k)) or ([make_order_key(order_id, None)] if order_id else [])
        hit = next((k for k in keys if k in composite), "")
        if order_id and (hit or order_id in legacy):
            if skipped_names is not None:
                skipped_names.append(str(entry.get("name") or entry.get("order_id") or "").strip())
            continue
        re_hit = next((k for k in keys if k in re_composite), "")
        if order_id and reissued is not None and (re_hit or order_id in re_legacy):
            name = str(entry.get("name") or "").strip()
            reissued.append((name or order_id, re_hit or order_id))
        kept.append(entry)
    return kept, len(entries) - len(kept)


def order_ids_from_stats(*stats_dicts: dict) -> list[str]:
    """프로세서 stats에서 발주서에 실제 기록된 '주문번호|옵션' 복합키를 수집.

    옵션은 bucket의 coupang_option_keyword(=DeliveryList 옵션 원문)를 쓴다 —
    다음 발주 때 DeliveryList L열과 대조하는 값이라 같은 출처여야 맞는다.
    """
    keys: set[str] = set()
    for stats in stats_dicts:
        for bucket in (stats or {}).get("options") or []:
            option = bucket.get("coupang_option_keyword") or bucket.get("vendor_option_name")
            for order in bucket.get("orders") or []:
                key = make_order_key(order.get("order_id"), option)
                if key:
                    keys.add(key)
    return sorted(keys)
