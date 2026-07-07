"""발주 이력 기반 중복발주 방지 헬퍼.

발주서를 생성할 때 포함된 주문번호를 DB(issued_order_items)에 기록하고,
다음 생성 시 '오늘 이전 날짜'에 기록된 주문번호를 입력(DeliveryList/토스 entries)에서
미리 걸러낸다. 같은 날 재생성은 걸러지지 않는다(아침 재출력·추가발주 워크플로 보존).

키는 주문번호(order_id) 단일 기준 — 쿠팡 DeliveryList C열, 토스/올웨이즈/테무 entry의 order_id.
"""
from io import BytesIO

from openpyxl import load_workbook


def normalize_order_id(value) -> str:
    """주문번호를 문자열로 정규화. 엑셀이 숫자로 읽은 경우(float/int) 지수표기·소수점 방지."""
    if value is None:
        return ""
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value)
    return str(value).strip()


def filter_delivery_by_issued(delivery_bytes: bytes, exclude_order_ids: set[str]) -> tuple[bytes, int]:
    """DeliveryList에서 이미 발주된 주문번호(C열) 행을 제거한 bytes와 제거 건수를 반환."""
    if not exclude_order_ids:
        return delivery_bytes, 0
    wb = load_workbook(filename=BytesIO(delivery_bytes))
    ws = wb.active
    to_delete = []
    for row_idx in range(2, ws.max_row + 1):
        order_id = normalize_order_id(ws.cell(row=row_idx, column=3).value)  # C열 = 주문번호
        if order_id and order_id in exclude_order_ids:
            to_delete.append(row_idx)
    if not to_delete:
        return delivery_bytes, 0
    for row_idx in reversed(to_delete):
        ws.delete_rows(row_idx)
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output.read(), len(to_delete)


def filter_entries_by_issued(entries: list[dict], exclude_order_ids: set[str]) -> tuple[list[dict], int]:
    """토스/올웨이즈/테무 entry 목록에서 이미 발주된 order_id를 제거."""
    if not exclude_order_ids or not entries:
        return entries, 0
    kept = [
        entry for entry in entries
        if normalize_order_id(entry.get("order_id")) not in exclude_order_ids
    ]
    return kept, len(entries) - len(kept)


def order_ids_from_stats(*stats_dicts: dict) -> list[str]:
    """프로세서 stats의 options[].orders[]에서 실제 발주서에 기록된 주문번호를 수집."""
    ids: set[str] = set()
    for stats in stats_dicts:
        for bucket in (stats or {}).get("options") or []:
            for order in bucket.get("orders") or []:
                order_id = normalize_order_id(order.get("order_id"))
                if order_id:
                    ids.add(order_id)
    return sorted(ids)
