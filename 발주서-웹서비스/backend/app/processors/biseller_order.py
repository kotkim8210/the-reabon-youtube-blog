"""비셀러 발주서 생성 — LA한입갈비(2026-09) + 김장·수산 시즌상품(2026-10-27 확장).

쿠팡 DeliveryList에서 비셀러 소싱 주문을 뽑아 메이크샵 "발주용 양식(대량주문 업로드)"으로 채운다.
  1~3행 헤더(라벨/필드키/필수·읽기전용) · 4행부터 데이터 · 상품은 상품번호(goods_no)로 지정.

매칭 규칙 (위에서 먼저 맞는 것 하나)
1. DeliveryList Q열 '업체상품코드'가 ``BS-<비셀러 상품번호>`` 이면 비셀러 발주 대상.
   2026-10-21부터 등록한 비셀러 소싱 상품(과메기·김장·수산)은 윙 판매자상품코드를 BS-<branduid>로
   통일했다. 메이크샵 상품번호(goods_no)는 비셀러 branduid와 같다
   (2026-10-27 확인: branduid 6120 = 양념LA한입갈비 2세트 = goods_no 6120).
   → 카탈로그(app/data/biseller_catalog.json)에 있으면 회원등급 상품코드·상품명·판매가격까지 채우고,
     없어도 상품번호·옵션번호(0)만으로 발주 행을 만든 뒤 needs_check로 알린다
     (업로드 필수값은 상품번호·옵션번호·수량·주문자·수취인뿐이라 발주 자체는 된다).
   → 앞으로 새 상품을 윙에 등록할 때 판매자상품코드를 BS-<branduid>로 넣기만 하면
     코드 수정 없이 이 발주서에 자동으로 들어온다. 카탈로그는 상품명 표기용이다.
2. LA한입갈비는 BS 코드 없이 등록된 옛 상품이라 종전처럼 상품명/옵션명에서 800g 세트 수를 읽는다.
   쿠팡 '800g 4개' → '양념LA한입갈비 800g+800g+800g+800g (800G*4세트)'
"""

import json
import logging
import re
import zipfile
from datetime import datetime, timezone, timedelta
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Font

from app.config import TEMPLATE_DIR

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

TEMPLATE_NAME = "비셀러_대량주문_원본.xlsx"   # 메이크샵 발주용 양식(2026-09-15)
DATA_START_ROW = 4                         # 1~3행은 헤더
# 발주서에 고정으로 들어가는 주문자 정보 — J·K열.
SENDER_NAME = "(주)아이티소프트"
SENDER_PHONE = "010-5700-7756"

# 비셀러 상품 카탈로그(JSON) — 윙에 등록한 비셀러 상품의 branduid → 상품코드·상품명·플러스회원가.
# 등록 때마다 여기에 추가한다(coupang-season-listing 스킬 마무리 단계). 서버 재시작 없이 매 호출마다 읽는다.
CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "biseller_catalog.json"

# LA한입갈비 카탈로그 — 세트 수 → 메이크샵 상품번호(goods_no). 업로드 필수값이라
# 여기 없는 세트 수는 발주서에 못 넣고 needs_check로 알린다.
# 출처: "엑셀 대량 주문 양식 order_list_2026-09-15" (상품번호·회원등급코드·판매가격).
BISELLER_CATALOG: dict[int, dict] = {
    # 판매가격(H열, 읽기전용)은 2026-10-28 비셀러 공식 주문목록 기준으로 갱신(20,480→21,210 / 37,800→38,750)
    2: {"goods_no": 6120, "code": "PL0006032", "price": 21210,
        "name": "양념LA한입갈비 800g+800g (800G*2세트)"},
    4: {"goods_no": 6121, "code": "PL0006033", "price": 38750,
        "name": "양념LA한입갈비 800g+800g+800g+800g (800G*4세트)"},
}
OPTION_SNO = 0            # 옵션 없는 상품 — 메이크샵 양식의 옵션번호 필수값
DELIVERY_CONDITION = "무료배송"
PRODUCT_LABEL = "비셀러"
GALBI_PRODUCT_LABEL = "LA한입갈비(비셀러)"
# 발주서 파일명에 쓰는 상품명(거래처 표기 없이 상품만)
ORDER_PRODUCT_NAME = "비셀러발주"
GALBI_ORDER_PRODUCT_NAME = "LA한입갈비"

_BS_CODE_RE = re.compile(r"^\s*BS[-_ ]?(\d{1,10})\s*$", re.IGNORECASE)


def normalize(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def _compact(*values: object) -> str:
    return re.sub(r"\s+", "", " ".join(normalize(v) for v in values))


# ── 비셀러 업로드 호환: 인라인 문자열 → 공용 문자열표(sharedStrings) ──────────
# openpyxl 3.1은 글자 칸을 t="inlineStr"(칸 안에 직접 기록)로 저장하고 xl/sharedStrings.xml을 만들지 않는다.
# 비셀러(메이크샵) 발주서 업로드는 공용 문자열표만 읽어서, 이런 파일은 1행 제목을 못 찾고
# "상품번호 항목이 없습니다"로 거부한다(2026-10-28 확인). 비셀러 공식 양식·엑셀 저장본은 모두 sharedStrings 사용.
# 사용자가 엑셀에서 '3행 내용 지우기' 후 저장하면 올라가던 것도, 엑셀이 다시 저장하며 이 구조로 바꿔줬기 때문.
_SST_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"
_SST_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings"
_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_ATTRS = r'(?:\s+[\w:]+="[^"]*")*'
_INLINE_CELL_RE = re.compile(
    r'<c(?P<a1>' + _ATTRS + r'?)\s+t="inlineStr"(?P<a2>' + _ATTRS + r')\s*(?:/>|>(?P<body>.*?)</c>)',
    re.S,
)
_IS_RE = re.compile(r"<is>(?P<inner>.*?)</is>", re.S)
_EMPTY_NUM_CELL_RE = re.compile(r'<c(?P<a1>' + _ATTRS + r'?)\s+t="n"(?P<a2>' + _ATTRS + r')\s*/>')


def to_shared_strings(xlsx_bytes: bytes) -> bytes:
    """openpyxl이 만든 xlsx의 인라인 문자열을 엑셀과 같은 공용 문자열표 구조로 바꾼다.

    값·서식·열 너비는 그대로 두고 문자 저장 방식만 바꾼다. 이미 sharedStrings가 있으면 그대로 반환.
    """
    zin = zipfile.ZipFile(BytesIO(xlsx_bytes))
    names = zin.namelist()
    if "xl/sharedStrings.xml" in names:
        return xlsx_bytes

    index: dict[str, int] = {}
    items: list[str] = []
    total = 0

    def _cell(match: re.Match) -> str:
        nonlocal total
        attrs = (match.group("a1") or "") + (match.group("a2") or "")
        inner_match = _IS_RE.search(match.group("body") or "")
        inner = inner_match.group("inner") if inner_match else ""
        if not inner or re.fullmatch(r"<t(?:\s[^>]*)?\s*/>|<t(?:\s[^>]*)?></t>", inner):
            return f"<c{attrs}/>"          # 빈 글자 칸 → 빈 칸
        idx = index.get(inner)
        if idx is None:
            idx = len(items)
            index[inner] = idx
            items.append(inner)
        total += 1
        return f'<c{attrs} t="s"><v>{idx}</v></c>'

    def _empty_num(match: re.Match) -> str:
        return f"<c{(match.group('a1') or '') + (match.group('a2') or '')}/>"

    sheets: dict[str, bytes] = {}
    for name in names:
        if name.startswith("xl/worksheets/") and name.endswith(".xml"):
            text = zin.read(name).decode("utf-8")
            text = _INLINE_CELL_RE.sub(_cell, text)
            text = _EMPTY_NUM_CELL_RE.sub(_empty_num, text)
            sheets[name] = text.encode("utf-8")

    out = BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = sheets.get(info.filename) or zin.read(info.filename)
            if info.filename == "[Content_Types].xml":
                text = data.decode("utf-8")
                if "/xl/sharedStrings.xml" not in text:
                    text = text.replace(
                        "</Types>",
                        f'<Override PartName="/xl/sharedStrings.xml" ContentType="{_SST_CT}" /></Types>',
                    )
                data = text.encode("utf-8")
            elif info.filename == "xl/_rels/workbook.xml.rels":
                text = data.decode("utf-8")
                if "sharedStrings.xml" not in text:
                    rel_id = "rIdSst1"
                    while f'Id="{rel_id}"' in text:
                        rel_id += "x"
                    text = text.replace(
                        "</Relationships>",
                        f'<Relationship Type="{_SST_REL}" Target="sharedStrings.xml" Id="{rel_id}" /></Relationships>',
                    )
                data = text.encode("utf-8")
            zout.writestr(info, data)
        sst = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<sst xmlns="{_MAIN_NS}" count="{total}" uniqueCount="{len(items)}">'
            + "".join(f"<si>{inner}</si>" for inner in items)
            + "</sst>"
        )
        zout.writestr("xl/sharedStrings.xml", sst.encode("utf-8"))
    return out.getvalue()


# ── 카탈로그(JSON) ────────────────────────────────────────────────
def load_catalog() -> dict[str, dict]:
    """branduid(str) → {goods_no, code, name, price, wing_id, wing_name, wing_option, registered}.

    파일이 없거나 깨져도 발주는 계속된다(상품번호만으로 행을 만든다).
    """
    try:
        if not CATALOG_PATH.exists():
            return {}
        data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("비셀러 카탈로그 읽기 실패(상품번호만으로 계속): %s", CATALOG_PATH)
        return {}
    items = data.get("items") if isinstance(data, dict) and "items" in data else data
    if not isinstance(items, dict):
        return {}
    return {str(k).strip(): v for k, v in items.items() if isinstance(v, dict)}


def upsert_catalog(entries: list[dict]) -> dict:
    """카탈로그에 상품을 추가/갱신한다. 각 entry는 goods_no(필수)·code·name·price·wing_* 를 가진다.

    반환: {"added": n, "updated": n, "total": n}
    """
    items = load_catalog()
    added = updated = 0
    now = datetime.now(KST).strftime("%Y-%m-%d")
    for raw in entries or []:
        goods_no = str(raw.get("goods_no") or raw.get("branduid") or "").strip()
        if not goods_no.isdigit():
            continue
        current = dict(items.get(goods_no) or {})
        is_new = not current
        for key in ("code", "name", "price", "wing_id", "wing_name", "wing_option", "registered", "status"):
            if raw.get(key) not in (None, ""):
                current[key] = raw[key]
        current["goods_no"] = int(goods_no)
        current.setdefault("registered", now)
        items[goods_no] = current
        if is_new:
            added += 1
        else:
            updated += 1
    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_PATH.write_text(
        json.dumps({"updated": now, "items": items}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return {"added": added, "updated": updated, "total": len(items)}


def parse_bs_code(value: object) -> str | None:
    """'BS-12326217' → '12326217'. 비셀러 코드가 아니면 None."""
    match = _BS_CODE_RE.match(str(value or ""))
    return match.group(1) if match else None


def resolve_bs_item(branduid: str, catalog: dict[str, dict] | None = None) -> tuple[dict, bool]:
    """branduid → 발주 행 item. (item, in_catalog)

    카탈로그에 없으면 상품번호만 채운 item을 돌려준다(메이크샵 업로드는 상품번호·옵션번호가 핵심).
    """
    catalog = load_catalog() if catalog is None else catalog
    found = catalog.get(branduid)
    if found:
        return {
            "goods_no": int(found.get("goods_no") or branduid),
            "code": str(found.get("code") or ""),
            "name": str(found.get("name") or ""),
            "price": found.get("price") if found.get("price") not in ("", None) else "",
            "option_sno": int(found.get("option_sno") or OPTION_SNO),
        }, True
    return {
        "goods_no": int(branduid),
        "code": "",
        "name": "",
        "price": "",
        "option_sno": OPTION_SNO,
    }, False


# ── LA한입갈비(세트 수 변환) ──────────────────────────────────────
def is_biseller_galbi_order(product_name: object, option_text: object) -> bool:
    """비셀러 발주 대상(LA한입갈비) 여부."""
    text = _compact(product_name, option_text)
    if "갈비" not in text:
        return False
    return "한입" in text or "LA갈비" in text.upper()


# 수량 단위 표기: 쿠팡 옵션은 '800g 4개', 라이브 이벤트 경품은 'LA한입갈비 800g 1팩'.
_COUNT_UNITS = r"(?:개입|개|팩|세트|봉지|봉|박스)"


def _galbi_count(text: str) -> int | None:
    """비셀러 갈비 표기에서 800g 낱개 개수를 읽는다. 못 읽으면 None."""
    match = (
        re.search(r"800g\s*(\d+)\s*" + _COUNT_UNITS, text, re.IGNORECASE)
        or re.search(r"(\d+)\s*" + _COUNT_UNITS + r"\s*800g", text, re.IGNORECASE)
        or re.search(r"(\d+)\s*" + _COUNT_UNITS, text)
    )
    if not match:
        return None
    count = int(match.group(1))
    return count if count >= 1 else None


def convert_galbi_option(
    product_name: object,
    option_text: object,
    *,
    promote_single: bool = False,
) -> str | None:
    """쿠팡 옵션·이벤트 경품명 → 비셀러 상품명. 개수를 못 읽으면 None.

    promote_single: 1팩짜리를 2세트로 올린다. 비셀러에 1세트 상품이 없어
        라이브 이벤트 당첨자(경품 'LA한입갈비 800g 1팩')는 2세트로 발주한다
        (2026-09-07 사용자 지시). 쿠팡 주문 경로는 그대로 둔다.
    """
    count = galbi_set_count(product_name, option_text, promote_single=promote_single)
    if not count:
        return None
    return f"양념LA한입갈비 {'+'.join(['800g'] * count)} (800G*{count}세트)"


def galbi_set_count(product_name: object, option_text: object, *, promote_single: bool = False) -> int | None:
    """쿠팡 옵션·경품명 → 800g 세트 수. 갈비가 아니거나 개수를 못 읽으면 None."""
    if not is_biseller_galbi_order(product_name, option_text):
        return None
    count = _galbi_count(_compact(product_name, option_text))
    if not count:
        return None
    if promote_single and count == 1:
        count = 2
    return count


def _galbi_item(sets: int | None) -> dict | None:
    found = BISELLER_CATALOG.get(sets) if sets else None
    if not found:
        return None
    return {**found, "option_sno": OPTION_SNO}


# ── DeliveryList → 발주 행 ────────────────────────────────────────
def _row_value(row, idx: int) -> str:
    return normalize(row[idx].value) if len(row) > idx else ""


def _entries_from_delivery(delivery_file_bytes: bytes) -> tuple[list[dict], list[str]]:
    """쿠팡 DeliveryList → 발주 행 목록.

    BS 코드 주문은 전부 넣고(카탈로그 밖이면 needs_check에 알림), 갈비 주문인데 개수를 못 읽으면 미매칭으로 보고.
    """
    dl_ws = load_workbook(filename=BytesIO(delivery_file_bytes), data_only=True).active
    catalog = load_catalog()

    entries: list[dict] = []
    unmatched: list[str] = []
    for row in dl_ws.iter_rows(min_row=2):
        product_name = _row_value(row, 10)
        option = _row_value(row, 11)
        vendor_code = _row_value(row, 16)        # Q열 업체상품코드(윙 판매자상품코드)
        recipient = _row_value(row, 26)
        if not product_name and not option and not vendor_code:
            continue

        branduid = parse_bs_code(vendor_code)
        item: dict | None = None
        kind = ""
        in_catalog = True
        if branduid:
            item, in_catalog = resolve_bs_item(branduid, catalog)
            kind = "bs"
            if not in_catalog:
                unmatched.append(
                    f"{recipient or '이름없음'}({option or product_name}) — 비셀러 카탈로그에 없는 {vendor_code}. "
                    f"상품번호 {branduid}로 발주서에 넣었으니 업로드 전 비셀러 상품이 맞는지 확인"
                )
        elif is_biseller_galbi_order(product_name, option):
            sets = galbi_set_count(product_name, option)
            if not sets:
                unmatched.append(f"{recipient or '이름없음'}({option or product_name}) — 수량 표기를 못 읽음")
                continue
            kind = "galbi"
            item = _galbi_item(sets)
            if not item:
                # 카탈로그(상품번호)에 없는 세트 수는 업로드 자체가 안 되므로 발주서에서 빼고 알린다.
                unmatched.append(
                    f"{recipient or '이름없음'}({option or product_name}) — 비셀러 상품번호가 없는 세트 수({sets}세트)"
                )
                continue
        else:
            continue

        qty_val = row[22].value if len(row) > 22 else ""
        try:
            qty_int = int(float(qty_val)) if qty_val not in (None, "") else 1
        except (ValueError, TypeError):
            qty_int = 1

        zipcode = _row_value(row, 28)
        if zipcode:
            try:
                zipcode = str(int(float(zipcode))).zfill(5)
            except (ValueError, TypeError):
                pass

        entries.append({
            "name": recipient,
            "phone": _row_value(row, 27),
            "zipcode": zipcode,
            "address": _row_value(row, 29),
            "memo": _row_value(row, 30),
            "product": item["name"] or f"{product_name} / {option}".strip(" /"),
            "item": item,
            "kind": kind,
            "in_catalog": in_catalog,
            "qty": qty_int,
            "order_no": _row_value(row, 2),
            "source_option": option or product_name,
            "coupang_product": product_name,
        })
    return entries, unmatched


def _entries_from_winners(winners_bytes: bytes) -> tuple[list[dict], list[str]]:
    """라이브 이벤트 당첨자 CSV → 발주 행 목록.

    당첨자 CSV 파싱(환불 제외·개인정보 미기재 표기)은 event_order.parse_winners를 그대로 쓴다.
    비셀러 품목(LA한입갈비)이 아닌 경품은 다른 발주처 몫이라 needs_check로 알린다.
    """
    from app.processors.event_order import parse_winners

    winners = parse_winners(winners_bytes)
    entries: list[dict] = []
    notes: list[str] = []
    for winner in winners:
        prize = normalize(winner.get("product"))
        sets = galbi_set_count(prize, "", promote_single=True)
        item = _galbi_item(sets)
        if not sets:
            notes.append(f"{winner.get('name') or '이름없음'}({prize or '경품미상'}) — 비셀러 발주 품목이 아님")
            continue
        if not item:
            notes.append(f"{winner.get('name') or '이름없음'}({prize}) — 비셀러 상품번호가 없는 세트 수({sets}세트)")
            continue
        entries.append({
            "name": normalize(winner.get("name")),
            "phone": normalize(winner.get("phone")),
            "zipcode": "",   # 당첨자 CSV에는 우편번호가 없다
            "address": normalize(winner.get("address")),
            "memo": normalize(winner.get("memo")) or "문 앞",
            "product": item["name"],
            "item": item,
            "kind": "galbi",
            "in_catalog": True,
            "qty": 1,
            "order_no": normalize(winner.get("order_id")),
            "source_option": prize,
            "coupang_product": prize,
        })

    if winners:
        last = winners[-1]
        skipped_refund = int(last.get("_skipped_refund") or 0)
        if skipped_refund:
            notes.append(f"환불/취소 {skipped_refund}건 제외")
        notes.extend(last.get("_incomplete") or [])
    return entries, notes


def _drop_issued_winners(
    event_entries: list[dict],
    issued_keys: set[str],
    duplicate_names: list[str] | None = None,
) -> tuple[list[dict], int]:
    """이미 발주된 당첨자(주문번호+경품명)를 걸러낸다 — 같은 CSV 재업로드 시 중복발주 방지."""
    from app.processors import issued_orders

    wrapped = [
        {"order_id": e["order_no"], "option": e["source_option"], "name": e["name"], "_entry": e}
        for e in event_entries
    ]
    kept, dropped = issued_orders.filter_entries_by_issued(
        wrapped, issued_keys, skipped_names=duplicate_names
    )
    return [item["_entry"] for item in kept], dropped


def process(
    delivery_file_bytes: bytes | None = None,
    winners_bytes: bytes | None = None,
    issued_keys: set[str] | None = None,
    duplicate_names: list[str] | None = None,
) -> tuple[bytes, str, dict]:
    """비셀러 발주서 생성.

    winners_bytes: 라이브 이벤트 당첨자 CSV(선택) — 쿠팡 주문 뒤에 이어붙여 한 장으로 낸다
        (2026-09-07 요청: 당첨자 명단도 같은 비셀러 양식으로).
    issued_keys: 이미 발주된 '주문번호|옵션' 키. 당첨자 CSV 쪽 중복발주를 막는다
        (DeliveryList 쪽은 main.py의 filter_delivery_by_issued가 미리 걸러낸다).
    """
    if not delivery_file_bytes and not winners_bytes:
        raise ValueError("DeliveryList 또는 라이브 이벤트 당첨자 CSV 중 하나는 올려야 합니다.")

    entries: list[dict] = []
    needs_check: list[str] = []
    coupang_count = 0
    event_count = 0
    event_duplicate_skipped = 0

    if delivery_file_bytes:
        dl_entries, unmatched = _entries_from_delivery(delivery_file_bytes)
        entries.extend(dl_entries)
        needs_check.extend(unmatched)
        coupang_count = len(dl_entries)

    if winners_bytes:
        event_entries, notes = _entries_from_winners(winners_bytes)
        if issued_keys:
            event_entries, event_duplicate_skipped = _drop_issued_winners(
                event_entries, issued_keys, duplicate_names
            )
        entries.extend(event_entries)
        needs_check.extend(notes)
        event_count = len(event_entries)

    template_path = TEMPLATE_DIR / TEMPLATE_NAME
    if not template_path.exists():
        raise FileNotFoundError(
            f"Template not found: {template_path}. "
            f"Please place the template file in the templates directory."
        )

    tmpl_wb = load_workbook(filename=str(template_path))
    first_sheet_name = tmpl_wb.sheetnames[0]
    for name in tmpl_wb.sheetnames[1:]:
        del tmpl_wb[name]
    ws = tmpl_wb[first_sheet_name]

    # 3행(읽기전용/필수 입력값 안내 라벨)은 값을 비운다 — 이 행에 글자가 있으면 비셀러(메이크샵)
    # 대량주문 업로드가 파일을 인식하지 못한다(2026-10-27 사용자 확인: '내용 지우기' 후에만 업로드됨).
    # 서식(회색 칸)은 그대로 두고 1·2행 헤더는 유지한다.
    for col in range(1, max(ws.max_column, 16) + 1):
        ws.cell(row=3, column=col).value = None

    uploadable = [e for e in entries if e.get("item")]

    font11 = Font(size=11)
    option_totals: dict[str, dict] = {}
    product_totals: dict[str, int] = {}
    for i, entry in enumerate(uploadable):
        out_row = DATA_START_ROW + i
        item = entry["item"]
        if not entry["zipcode"]:
            needs_check.append(f"{entry['name']} — 우편번호 없음(메이크샵 필수값). 업로드 전 N열에 직접 입력")
        mapping = {
            1: i + 1,                   # A 순서
            2: item["goods_no"],        # B 상품번호 (필수)
            3: item["code"],            # C 회원등급 상품코드
            4: item["name"],            # D 상품명
            5: item["option_sno"],      # E 옵션번호 (필수)
            6: "",                      # F 옵션명
            7: DELIVERY_CONDITION,      # G 배송비조건
            8: item["price"],           # H 판매가격
            9: entry["qty"],            # I 수량 (필수)
            10: SENDER_NAME,            # J 주문자 성명 (필수)
            11: SENDER_PHONE,           # K 주문자 전화번호 (필수)
            12: entry["name"],          # L 수취인 성명 (필수)
            13: entry["phone"],         # M 수취인 전화번호 (필수)
            14: entry["zipcode"],       # N 우편번호 (필수)
            15: entry["address"],       # O 수취인 주소 (필수)
            16: entry["memo"],          # P 배송메시지
        }
        for col, value in mapping.items():
            cell = ws.cell(row=out_row, column=col, value=value)
            cell.font = font11

        key = entry["source_option"] or entry["product"]
        bucket = option_totals.setdefault(
            key,
            {
                "coupang_option_keyword": key,
                "vendor_option_name": item["name"] or f"상품번호 {item['goods_no']}",
                "quantity": 0,
                "orders": [],
            },
        )
        bucket["quantity"] += entry["qty"]
        if entry["order_no"]:
            bucket["orders"].append({"order_id": entry["order_no"], "quantity": entry["qty"]})
        label = item["name"] or f"상품번호 {item['goods_no']}"
        product_totals[label] = product_totals.get(label, 0) + entry["qty"]

    if needs_check:
        logger.warning("비셀러 발주 확인필요 %d건: %s", len(needs_check), "; ".join(needs_check))

    output = BytesIO()
    tmpl_wb.save(output)
    # 비셀러 업로드는 공용 문자열표만 읽는다 — openpyxl 인라인 문자열을 엑셀과 같은 구조로 바꿔서 낸다(2026-10-28)
    xlsx_bytes = to_shared_strings(output.getvalue())

    # 파일명은 상품명 + 날짜 (2026-09-09 사용자 요청). 갈비만 있으면 종전 그대로 LA한입갈비(20260909).xlsx,
    # 김장·수산 등 BS 코드 상품이 섞이면 비셀러발주(20261027).xlsx
    galbi_only = bool(uploadable) and all(e.get("kind") == "galbi" for e in uploadable)
    product_name = GALBI_ORDER_PRODUCT_NAME if galbi_only else ORDER_PRODUCT_NAME
    filename = f"{product_name}({datetime.now(KST).strftime('%Y%m%d')}).xlsx"
    stats = {
        "total": len(uploadable),
        "product": GALBI_PRODUCT_LABEL if galbi_only else PRODUCT_LABEL,
        "options": list(option_totals.values()),
    }
    if product_totals:
        stats["발주 품목"] = ", ".join(f"{name} ×{qty}" for name, qty in product_totals.items())
    missing = [e for e in uploadable if not e.get("in_catalog")]
    if missing:
        stats["catalog_missing"] = len(missing)
    if winners_bytes:
        stats["coupang"] = coupang_count
        stats["event"] = event_count
    if event_duplicate_skipped:
        stats["duplicate_skipped"] = event_duplicate_skipped
    if needs_check:
        stats["needs_check"] = needs_check

    return xlsx_bytes, filename, stats
