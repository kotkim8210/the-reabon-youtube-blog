import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha1
from io import BytesIO

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.styles.colors import Color

KST = timezone(timedelta(hours=9))
JBT_SENDER_NAME = "(주)아이티소프트"
TOSS_WATERMELON_EXCLUDED_STATUS_PATTERNS = ("CANCEL", "RETURN", "REFUND", "EXCHANGE")
TOSS_SHIPPED_STATUS_PATTERNS = ("DELIVER", "SHIP")  # 배송중/배송완료 → 발주 제외
JBT_WATERMELON_KGS = {6, 7, 8}
JBT_WATERMELON_LABEL = "수박 6/7/8kg"


@dataclass
class _VirtualCell:
    value: object = ""


def normalize(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def is_mixed_chamoe(product_name: str, option_text: str) -> bool:
    return "성주참외" in product_name and "가정용 혼합과" in option_text


def delivery_watermelon_kg(product_name: str = "", option_text: str = "") -> int | None:
    text = normalize(f"{product_name} {option_text}")
    # 망고수박은 쥬얼리프룻(myeongi_order) 발주 — 일반수박(제이비티) 로직에서 제외
    if "수박" not in text or "망고" in text:
        return None
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*kg", text, re.IGNORECASE):
        try:
            kg = float(match.group(1))
        except ValueError:
            continue
        if kg.is_integer():
            return int(kg)
    return None


# 신비복숭아 발주처 분리 (2026-06): 1·2kg → 쥬얼리프룻, 3·4kg → 제이비티, 800g 등 그 외 → 제외
JBT_PEACH_KGS = {3, 4}
JEWELRY_PEACH_KGS = {1, 2}


def peach_kg(product_name: str = "", option_text: str = "") -> float | int | None:
    """신비복숭아 주문의 무게(kg)를 반환. 복숭아 아니거나 무게 없으면 None."""
    text = normalize(f"{product_name} {option_text}")
    if "복숭아" not in text:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(kg|g)", text, re.IGNORECASE)
    if not m:
        return None
    amount = float(m.group(1))
    kg = amount / 1000 if m.group(2).lower() == "g" else amount
    return int(kg) if kg.is_integer() else kg


def is_jbt_corn_order(product_name: str = "", option_text: str = "") -> bool:
    text = normalize(f"{product_name} {option_text}")
    return "옥수수" in text and ("중품" in text or "특품" in text)


def stable_order_id(prefix: str, *values) -> str:
    raw = "|".join(normalize(value) for value in values if normalize(value))
    if not raw:
        return ""
    return f"{prefix}:{sha1(raw.encode('utf-8')).hexdigest()[:16]}"


def toss_order_id(item: dict) -> str:
    for key in ("orderNo", "orderId", "orderNumber", "orderSheetId", "paymentKey", "orderProductId"):
        value = item.get(key)
        if value:
            return str(value)
    return ""


def _toss_item_text(value) -> str:
    parts: list[str] = []

    def walk(node) -> None:
        if node is None:
            return
        if isinstance(node, dict):
            for child in node.values():
                walk(child)
            return
        if isinstance(node, (list, tuple)):
            for child in node:
                walk(child)
            return
        parts.append(str(node))

    walk(value)
    return normalize(" ".join(parts))


def is_toss_watermelon_order(item: dict) -> bool:
    text = _toss_item_text(item)
    # 망고수박은 제이비티 일반수박 발주 대상이 아니다
    return "수박" in text and "망고" not in text


def is_toss_peach_order(item: dict) -> bool:
    return "복숭아" in _toss_item_text(item)


def _toss_peach_option(item: dict) -> str:
    """토스 신비복숭아 옵션 → 무게 표기 추출(800g/1kg 등). transform_product가 등급을 결정."""
    option = normalize(item.get("optionName") or "")
    if option:
        return option
    for source in (normalize(item.get("productName") or ""), _toss_item_text(item)):
        m = re.search(r"(\d+\.?\d*)\s*(g|kg)", source, re.IGNORECASE)
        if m:
            return f"{m.group(1)}{m.group(2)}"
    return normalize(item.get("productName") or "")


def _toss_address(item: dict) -> str:
    address = item.get("address") or item.get("receiverAddress1") or ""
    detail = item.get("detailAddress") or item.get("receiverAddress2") or ""
    return normalize(f"{address} {detail}".strip())


def _toss_zipcode(item: dict) -> str:
    zipcode = normalize(item.get("zipCode") or item.get("receiverZipCode") or "")
    if not zipcode:
        return ""
    try:
        return str(int(float(zipcode))).zfill(5)
    except (TypeError, ValueError):
        return zipcode.zfill(5)


def _toss_watermelon_option(item: dict) -> str:
    option = normalize(item.get("optionName") or "")
    if option:
        return option
    product_name = normalize(item.get("productName") or "")
    kg_match = re.search(r"(\d+\.?\d*)\s*kg", product_name, re.IGNORECASE)
    if kg_match:
        return f"{kg_match.group(1)}kg"
    kg_match = re.search(r"(\d+\.?\d*)\s*kg", _toss_item_text(item), re.IGNORECASE)
    if kg_match:
        return f"{kg_match.group(1)}kg"
    return product_name


def _virtual_toss_row(entry: dict) -> list[_VirtualCell]:
    row = [_VirtualCell() for _ in range(31)]
    row[2].value = entry.get("order_id", "")
    row[10].value = entry.get("product_name", "토스 수박")
    row[11].value = entry.get("option", "")
    row[22].value = entry.get("qty", "1")
    row[26].value = entry.get("name", "")
    row[27].value = entry.get("phone", "")
    row[28].value = entry.get("zipcode", "")
    row[29].value = entry.get("address", "")
    row[30].value = entry.get("memo", "")
    return row


async def collect_toss_watermelon_orders(from_date: str, to_date: str) -> list[dict]:
    from app.toss.client import toss_client

    orders = await toss_client.get_orders(
        start_date=from_date,
        end_date=to_date,
        status=None,
    )

    entries: list[dict] = []
    for item in orders:
        if not is_toss_watermelon_order(item):
            continue
        order_status = normalize(item.get("orderProductStatus") or item.get("status") or item.get("orderStatus") or "")
        if order_status and any(pattern in order_status.upper() for pattern in TOSS_WATERMELON_EXCLUDED_STATUS_PATTERNS):
            continue

        option = _toss_watermelon_option(item)
        if delivery_watermelon_kg(_toss_item_text(item), option) not in JBT_WATERMELON_KGS:
            continue

        address = _toss_address(item)
        entries.append(
            {
                "name": item.get("receiverName") or "",
                "phone": item.get("receiverRealPhone") or item.get("receiverPhone") or "",
                "zipcode": _toss_zipcode(item),
                "address": address,
                "qty": str(item.get("quantity") or 1),
                "product_name": item.get("productName") or "토스 수박",
                "option": option,
                "memo": item.get("shippingNote") or "",
                "order_id": toss_order_id(item)
                or stable_order_id(
                    "toss-watermelon",
                    item.get("receiverName"),
                    item.get("receiverRealPhone") or item.get("receiverPhone"),
                    address,
                    option,
                    item.get("quantity") or 1,
                ),
            }
        )

    return entries


def _toss_order_done(item: dict) -> bool:
    """이미 발송된(배송중/배송완료) 또는 송장이 입력된 토스 주문인지 → 발주 제외 대상."""
    status = normalize(item.get("orderProductStatus") or item.get("status") or item.get("orderStatus") or "")
    su = status.upper()
    if status and (any(p in su for p in TOSS_SHIPPED_STATUS_PATTERNS) or "배송" in status):
        return True
    return bool(normalize(item.get("shippingTrackingNumber") or item.get("trackingNumber") or ""))


async def collect_toss_peach_orders(
    from_date: str,
    to_date: str,
    kgs: set | None = None,
) -> list[dict]:
    """토스 API에서 신비복숭아 주문을 수집.

    kgs로 무게를 거른다 (제이비티=3·4kg, 쥬얼리=1·2kg). None이면 전체.
    각 entry에 'kg'(무게)를 포함한다.
    """
    from app.toss.client import toss_client

    orders = await toss_client.get_orders(
        start_date=from_date,
        end_date=to_date,
        status=None,
    )

    entries: list[dict] = []
    for item in orders:
        if not is_toss_peach_order(item):
            continue
        order_status = normalize(item.get("orderProductStatus") or item.get("status") or item.get("orderStatus") or "")
        if order_status and any(pattern in order_status.upper() for pattern in TOSS_WATERMELON_EXCLUDED_STATUS_PATTERNS):
            continue
        # 배송중/배송완료거나 송장 입력된 건은 발주서에서 제외 → 과거 주문 재발주 방지
        if _toss_order_done(item):
            continue

        option = _toss_peach_option(item)
        kg = peach_kg(_toss_item_text(item), option)
        if kgs is not None and kg not in kgs:
            continue
        address = _toss_address(item)
        entries.append(
            {
                "name": item.get("receiverName") or "",
                "phone": item.get("receiverRealPhone") or item.get("receiverPhone") or "",
                "zipcode": _toss_zipcode(item),
                "address": address,
                "qty": str(item.get("quantity") or 1),
                "product_name": item.get("productName") or "토스 신비복숭아",
                "option": option,
                "kg": kg,
                "memo": item.get("shippingNote") or "",
                "order_id": toss_order_id(item)
                or stable_order_id(
                    "toss-peach",
                    item.get("receiverName"),
                    item.get("receiverRealPhone") or item.get("receiverPhone"),
                    address,
                    option,
                    item.get("quantity") or 1,
                ),
            }
        )

    return entries


async def collect_toss_jewelry_orders(from_date: str, to_date: str) -> list[dict]:
    """토스 API에서 쥬얼리팜 발주 대상 주문을 수집.

    대상: 수박 6/7/8kg · 성주참외 · 신비복숭아(소과/대과 등 옵션 그대로) · (블랙)망고수박.
    각 entry에 'product'(쥬얼리 발주 품목명)를 포함한다.
    """
    from app.toss.client import toss_client
    from app.processors.myeongi_order import jewelry_passthrough_product

    orders = await toss_client.get_orders(
        start_date=from_date,
        end_date=to_date,
        status=None,
    )

    entries: list[dict] = []
    for item in orders:
        text = _toss_item_text(item)
        # 수박(망고수박 포함)·성주참외·신비복숭아·홍감자 토스 주문
        if not any(k in text for k in ("수박", "참외", "복숭아", "감자")):
            continue
        order_status = normalize(item.get("orderProductStatus") or item.get("status") or item.get("orderStatus") or "")
        if order_status and any(pattern in order_status.upper() for pattern in TOSS_WATERMELON_EXCLUDED_STATUS_PATTERNS):
            continue
        # 배송중/배송완료거나 송장 입력된 건은 발주서에서 제외 → 과거 주문 재발주 방지
        if _toss_order_done(item):
            continue

        # 신비복숭아·망고수박은 옵션 그대로, 수박/참외는 정규화
        option = normalize(item.get("optionName") or "") or _toss_watermelon_option(item)
        # 신비복숭아 3·4kg은 제이비티 발주(토마토 메뉴)로 → 쥬얼리 수집에서 제외 (1·2kg만 쥬얼리)
        if "복숭아" in text and peach_kg(text, option) not in JEWELRY_PEACH_KGS:
            continue
        # 품목명/무게 매칭은 상품명(K)을 우선으로 본다. 옵션(L)이 비거나 잘못 적혀도
        # 상품명에서 무게·종류를 읽도록 깨끗한 productName을 넘긴다. (없을 때만 전체 text)
        product_name = normalize(item.get("productName") or "") or text
        # 방어: 토스 상품명에 품목 키워드가 누락돼도 전체 주문 텍스트(text)에 있으면 보강한다.
        # (블랙망고수박이 '수박'만 잡혀 일반수박으로 둔갑하는 실수 차단 — 무게는 그대로 추출됨)
        _compact_all = text.replace(" ", "")
        _compact_name = product_name.replace(" ", "")
        for _kw in ("블랙망고수박", "망고수박", "홍감자"):
            if _kw in _compact_all and _kw not in _compact_name:
                product_name = f"{_kw} {product_name}"
                break
        product = jewelry_passthrough_product(product_name, option, JBT_WATERMELON_KGS)
        if not product:
            continue

        address = _toss_address(item)
        entries.append(
            {
                "name": item.get("receiverName") or "",
                "phone": item.get("receiverRealPhone") or item.get("receiverPhone") or "",
                "zipcode": _toss_zipcode(item),
                "address": address,
                "qty": str(item.get("quantity") or 1),
                "product_name": item.get("productName") or "토스 주문",
                "option": option,
                "product": product,
                "memo": item.get("shippingNote") or "",
                "order_id": toss_order_id(item)
                or stable_order_id(
                    "toss-jewelry",
                    item.get("receiverName"),
                    item.get("receiverRealPhone") or item.get("receiverPhone"),
                    address,
                    option,
                    item.get("quantity") or 1,
                ),
            }
        )

    return entries


def parse_alwayz_jbt_rows(alwayz_bytes: bytes) -> tuple[list, dict]:
    """올웨이즈 주문내역(.xlsx)에서 제이비티 발주 대상 행을 추출.

    올웨이즈 컬럼: A=주문아이디, E=상품명, F=옵션, G=수량,
                  O=주소, P=우편번호, S=수령인, T=수령인 연락처
    반환: ([(virtual_row, product_type), ...], flags dict)
    분류 기준은 process_outputs(쿠팡 DeliveryList)와 동일.
    """
    wb = load_workbook(filename=BytesIO(alwayz_bytes), data_only=True)
    ws = wb.active

    rows: list = []
    flags = {
        "tomato": False, "chamoe": False, "ddureup": False,
        "watermelon": False, "corn": False, "peach": False,
    }
    for row in ws.iter_rows(min_row=2):
        product_name = normalize(row[4].value) if len(row) > 4 else ""   # E
        option = normalize(row[5].value) if len(row) > 5 else ""          # F
        name = normalize(row[18].value) if len(row) > 18 else ""          # S
        if not name or not product_name:
            continue

        ptype = None
        if "대저토마토" in product_name:
            ptype = "토마토"; flags["tomato"] = True
        # ※ 성주참외는 쥬얼리팜 발주로 전환 — 제이비티 올웨이즈 파싱에서 제외
        elif "땅두릅" in product_name:
            ptype = "땅두릅"; flags["ddureup"] = True
        # ※ 수박은 쥬얼리팜, 초당옥수수는 제주다팜(kolrabi) 발주로 전환 — 제이비티 올웨이즈 파싱에서 제외
        elif peach_kg(product_name, option) in JBT_PEACH_KGS:
            ptype = "복숭아"; flags["peach"] = True
        if ptype is None:
            continue

        entry = {
            "order_id": normalize(row[0].value) if len(row) > 0 else "",   # A
            "product_name": product_name,
            "option": option,
            "qty": (normalize(row[6].value) if len(row) > 6 else "") or "1",  # G
            "name": name,
            "phone": normalize(row[19].value) if len(row) > 19 else "",    # T
            "zipcode": normalize(row[15].value) if len(row) > 15 else "",  # P
            "address": normalize(row[14].value) if len(row) > 14 else "",  # O
            "memo": "",
        }
        rows.append((_virtual_toss_row(entry), ptype))

    return rows, flags


async def process_toss_watermelon_order(
    from_date: str,
    to_date: str,
    alwayz_bytes: bytes | None = None,
    collect_toss: bool = True,
) -> list[tuple[bytes, str, dict]]:
    """토스+올웨이즈 발주 — 발주처별 발주서 목록 반환.

    쥬얼리프룻(수박·성주참외·신비복숭아 1·2kg) + 제이비티(신비복숭아 3·4kg).
    myeongi_order로 위임한다.
    """
    from app.processors.myeongi_order import process_jewelry_watermelon_order

    return await process_jewelry_watermelon_order(
        from_date, to_date, alwayz_bytes=alwayz_bytes, collect_toss=collect_toss
    )


def transform_product(option_text: str, product_type: str = "") -> str:
    text = normalize(option_text)

    if product_type == "옥수수":
        grade = "중품" if "중품" in text else "특품" if "특품" in text else ""
        count_match = re.search(r"(\d+)\s*(?:개|입)", text)
        if grade and count_match:
            result = f"초당옥수수 {grade} {count_match.group(1)}개"
        else:
            result = text
        return result if result.endswith("_vip") else f"{result}_vip"

    if product_type == "수박":
        kg_match = re.search(r"(\d+\.?\d*)\s*kg", text, re.IGNORECASE)
        if kg_match:
            result = f"하우스수박(상품){kg_match.group(1)}kg이상"
        else:
            result = f"하우스수박(상품){text}".strip()
        return result if result.endswith("_vip") else f"{result}_vip"

    if product_type == "땅두릅":
        weight_match = re.search(r"(\d+\.?\d*)\s*(g|kg)", text, re.IGNORECASE)
        if weight_match:
            amount = weight_match.group(1)
            unit = weight_match.group(2).lower()
            weight_str = f"{amount}{unit}"
            if unit == "g":
                result = f"남해땅두릅(튀김용){weight_str}"
            else:
                result = f"남해땅두릅(특품){weight_str}"
        else:
            result = f"남해땅두릅{text}"
        return result if result.endswith("_vip") else f"{result}_vip"

    if product_type == "복숭아":
        # 신비복숭아: 무게로 등급 결정 (800g→혼합과, 1~4kg→중소과)
        weight_match = re.search(r"(\d+\.?\d*)\s*(g|kg)", text, re.IGNORECASE)
        if weight_match:
            amount = float(weight_match.group(1))
            unit = weight_match.group(2).lower()
            weight_kg = amount / 1000 if unit == "g" else amount
            weight_str = f"{weight_match.group(1)}{unit}"
            grade = "혼합과" if weight_kg < 1.0 else "중소과"
            result = f"신비복숭아({grade}){weight_str}"
        else:
            result = f"신비복숭아{text}"
        return result if result.endswith("_vip") else f"{result}_vip"

    kg_match = re.search(r"(\d+\.?\d*)\s*kg", text, re.IGNORECASE)
    kg_suffix = f" {kg_match.group(1)}kg" if kg_match else ""

    text = re.sub(r"^1박스\s*", "", text)

    if "가정용" in text:
        grade_match = re.search(r"(혼합과|중소과|로얄과)", text)
        grade = grade_match.group(1) if grade_match else ""
        fruit_match = re.search(r"\((\d+-\d+과)\)", text)
        fruit_suffix = f"({fruit_match.group(1)})" if fruit_match else ""
        if grade:
            kg_str = kg_suffix.strip()
            result = f"가정용참외({grade}){kg_str}{fruit_suffix}"
            return result if result.endswith("_vip") else f"{result}_vip"

    if "짭짤이" in text:
        if "로얄" in text or "S~2S" in text or "S-2S" in text:
            kg_str = kg_suffix.strip()
            result = f"대저짭짤이특품(S)과 {kg_str}"
            return result if result.endswith("_vip") else f"{result}_vip"
        return text if text.endswith("_vip") else f"{text}_vip"

    if "특품" in text:
        cleaned = re.sub(r"\d+\.?\d*\s*kg", "", text).strip()
        result = f"대저토마토{cleaned}{kg_suffix}"
        return result if result.endswith("_vip") else f"{result}_vip"

    return text if text.endswith("_vip") else f"{text}_vip"


# 제이비티 합배송 가능 품목 — 이것만 수량 N 그대로 한 행으로 발주.
# 그 외(대저토마토·신비복숭아·남해땅두릅·수박 등 합배송 불가)는 거래처 규칙상
# '수량1 고정' — 수량 N건을 N개 행(각 수량1)으로 분할해 발주한다(수량2 이상은 송장이 따로 나옴).
_JBT_COMBINABLE = ("봉지곶감", "꽃게액젓", "손질꽃게", "장어", "밤", "김치", "꿀오일", "쉐이크선식", "선식", "마")


def _jbt_combinable(product_name: object) -> bool:
    """제이비티 합배송 가능 품목이면 True(수량 유지). 그 외는 False(수량1로 분할)."""
    text = re.sub(r"\s+", "", str(product_name or ""))
    if "토마토" in text:  # '마' 오탐 방지 — 대저토마토는 합배송 불가
        return False
    return any(kw in text for kw in _JBT_COMBINABLE)


def build_main_order_workbook(
    filtered_rows: list[tuple],
    has_tomato: bool,
    has_chamoe: bool,
    has_ddureup: bool,
    has_watermelon: bool,
    has_corn: bool = False,
    has_peach: bool = False,
) -> tuple[bytes, str, dict]:
    wb = Workbook()
    ws = wb.active

    headers = [
        "송장번호",
        "수령인(성함)",
        "수령인(연락처)",
        "수령인(주소)",
        "품목명",
        "수량",
        "배송메세지",
        "보내는분 상호",
        "보내는분 연락처\n(해당업체 연락처)",
        "주문번호",
    ]

    col_widths = {
        "A": 13,
        "B": 12.375,
        "C": 15.5,
        "D": 45,
        "E": 36.75,
        "F": 13,
        "G": 26,
        "H": 15.125,
        "I": 13.375,
        "J": 16.125,
    }
    for col_letter, width in col_widths.items():
        ws.column_dimensions[col_letter].width = width

    fill_theme6 = PatternFill(patternType="solid", fgColor=Color(theme=6, tint=0.4))
    fill_theme9 = PatternFill(patternType="solid", fgColor=Color(theme=9, tint=0.4))
    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )
    header_font = Font(name="맑은 고딕", size=11, bold=True)
    data_font = Font(name="맑은 고딕", size=11)
    sales_groups: dict[str, dict[str, dict]] = {}

    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.border = thin_border
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        if col_idx in (1, 6):
            cell.fill = fill_theme6
        elif col_idx in (2, 3, 4, 5, 7, 8, 9):
            cell.fill = fill_theme9

    out_row = 1  # 헤더가 1행. 데이터는 2행부터(분할로 행 수가 filtered_rows보다 많을 수 있음)
    for row, product_type in filtered_rows:
        name = normalize(row[26].value) if len(row) > 26 else ""
        phone = normalize(row[27].value) if len(row) > 27 else ""
        address = normalize(row[29].value) if len(row) > 29 else ""
        option = normalize(row[11].value) if len(row) > 11 else ""
        qty_value = row[22].value if len(row) > 22 else ""
        memo = normalize(row[30].value) if len(row) > 30 else ""
        order_no = normalize(row[2].value) if len(row) > 2 else ""

        address = address.replace("*", "")
        product = transform_product(option, product_type)
        try:
            qty_int = int(qty_value) if qty_value else 1
        except (TypeError, ValueError):
            qty_int = 1

        if product_type == "토마토":
            product_label = "대저토마토"
        elif product_type == "참외":
            product_label = "성주참외"
        elif product_type == "땅두릅":
            product_label = "남해땅두릅"
        elif product_type == "수박":
            product_label = "수박"
        elif product_type == "옥수수":
            product_label = "초당옥수수"
        elif product_type == "복숭아":
            product_label = "신비복숭아"
        else:
            product_label = "제이비티"

        option_bucket = sales_groups.setdefault(product_label, {}).setdefault(
            option,
            {
                "coupang_option_keyword": option,
                "vendor_option_name": product,
                "quantity": 0,
                "orders": [],
            },
        )
        option_bucket["quantity"] += qty_int
        if order_no:
            option_bucket["orders"].append({"order_id": order_no, "quantity": qty_int})

        # 제이비티 합배송 불가 품목은 수량1로 고정 → 수량 N건을 N개 행(각 수량1)으로 분할.
        # 합배송 가능 품목만 수량 N 그대로 한 행.
        row_qtys = [1] * qty_int if (qty_int >= 2 and not _jbt_combinable(product)) else [qty_int]

        for unit_qty in row_qtys:
            out_row += 1
            mapping = {
                1: "",
                2: name,
                3: phone,
                4: address,
                5: product,
                6: str(unit_qty),
                7: memo,
                8: JBT_SENDER_NAME,
                9: "010-5700-7756",
                10: order_no,
            }
            for col, value in mapping.items():
                cell = ws.cell(row=out_row, column=col, value=value)
                cell.font = data_font
                cell.border = thin_border

    ws.auto_filter.ref = f"A1:K{out_row}"

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    now = datetime.now(KST)
    parts = []
    if has_tomato:
        parts.append("대저토마토")
    if has_chamoe:
        parts.append("성주참외")
    if has_ddureup:
        parts.append("남해땅두릅")
    if has_watermelon:
        parts.append("수박")
    if has_corn:
        parts.append("초당옥수수")
    if has_peach:
        parts.append("신비복숭아")
    product_label = "_".join(parts) if parts else "발주"
    # 신비복숭아 3·4kg(제이비티) 발주가 포함되면 파일명 맨 앞에 '제이비_' 접두
    prefix = "제이비_" if has_peach else ""
    filename = f"{prefix}아이티소프트_{product_label}({now.strftime('%Y%m%d')}).xlsx"
    stats = {
        "total": max(out_row - 1, 0),  # 헤더 제외 실제 발주 행 수(수량1 분할 반영)
        "sales_groups": [
            {"product": label, "options": list(options.values())}
            for label, options in sales_groups.items()
        ],
    }
    return output.read(), filename, stats


def build_jbt_peach_workbook(peach_rows: list) -> tuple[bytes, str, dict] | None:
    """신비복숭아 3·4kg 행들[(virtual_row, '복숭아'), ...] → 제이비티 발주서. 비면 None."""
    if not peach_rows:
        return None
    return build_main_order_workbook(
        filtered_rows=peach_rows,
        has_tomato=False,
        has_chamoe=False,
        has_ddureup=False,
        has_watermelon=False,
        has_corn=False,
        has_peach=True,
    )


def process_outputs(
    delivery_file_bytes: bytes,
    toss_watermelon_entries: list[dict] | None = None,
    toss_peach_entries: list[dict] | None = None,
) -> list[tuple[bytes, str, dict]]:
    dl_wb = load_workbook(filename=BytesIO(delivery_file_bytes), data_only=True)
    dl_ws = dl_wb.active
    toss_watermelon_entries = toss_watermelon_entries or []
    toss_peach_entries = toss_peach_entries or []

    filtered_rows = []
    has_tomato = False
    has_chamoe = False
    has_ddureup = False
    has_watermelon = False
    has_corn = False
    has_peach = False

    for row in dl_ws.iter_rows(min_row=2):
        product_name = normalize(row[10].value) if len(row) > 10 else ""
        option = normalize(row[11].value) if len(row) > 11 else ""

        if "대저토마토" in product_name:
            has_tomato = True
            filtered_rows.append((row, "토마토"))
        # ※ 성주참외(로얄/중소/알뜰)는 2026-06부터 쥬얼리팜 발주로 전환 — 제이비티 제외
        elif "땅두릅" in product_name:
            has_ddureup = True
            filtered_rows.append((row, "땅두릅"))
        # ※ 수박(6/7/8kg)은 쥬얼리팜(myeongi), 초당옥수수는 제주다팜(kolrabi_order)으로 발주 이관 — 제이비티 제외
        elif peach_kg(product_name, option) in JBT_PEACH_KGS:
            # 신비복숭아 3·4kg만 제이비티(중소과). 1·2kg은 쥬얼리프룻, 800g은 제외.
            has_peach = True
            filtered_rows.append((row, "복숭아"))

    for entry in toss_watermelon_entries:
        has_watermelon = True
        filtered_rows.append((_virtual_toss_row(entry), "수박"))

    for entry in toss_peach_entries:
        has_peach = True
        filtered_rows.append((_virtual_toss_row(entry), "복숭아"))

    results: list[tuple[bytes, str, dict]] = []
    if filtered_rows:
        results.append(
            build_main_order_workbook(
                filtered_rows=filtered_rows,
                has_tomato=has_tomato,
                has_chamoe=has_chamoe,
                has_ddureup=has_ddureup,
                has_watermelon=has_watermelon,
                has_corn=has_corn,
                has_peach=has_peach,
            )
        )

    return results


def process(
    delivery_file_bytes: bytes,
    toss_watermelon_entries: list[dict] | None = None,
) -> tuple[bytes, str, dict]:
    results = process_outputs(delivery_file_bytes, toss_watermelon_entries=toss_watermelon_entries)
    if not results:
        raise ValueError("제이비티 발주로 출력할 대저토마토·성주참외(중소/로얄)·남해땅두릅·수박 주문을 찾지 못했습니다.")
    return results[0]
