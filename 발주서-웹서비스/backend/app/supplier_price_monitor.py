from __future__ import annotations

import csv
import logging
import re
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from html import unescape
from io import BytesIO, StringIO
from pathlib import Path
from typing import Literal
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import httpx
from openpyxl import load_workbook

from app.config import PBF_PARTNER_ID, PBF_PARTNER_PASSWORD, TEMPLATE_DIR, UPLOAD_DIR

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))
GOOGLE_SHEET_JBT_FRUIT_CSV = (
    "https://docs.google.com/spreadsheets/d/1g0Bxmz773DqPjCfYgBNyBtlYKxYuLJYY2zasqiC5u7Y/export"
    "?format=csv&gid=1683225896"
)
GOOGLE_SHEET_JBT_FARM_CSV = (
    "https://docs.google.com/spreadsheets/d/1g0Bxmz773DqPjCfYgBNyBtlYKxYuLJYY2zasqiC5u7Y/gviz/tq"
    "?tqx=out:csv&sheet=%EB%86%8D%EC%82%B0%EB%AC%BC"
)
GOOGLE_SHEET_JEJUDAPAM_VEGETABLE_CSV = (
    "https://docs.google.com/spreadsheets/d/1hATLzLK5fjum_ehXG-uSrJ3owllSVKeYV-U5Aox5pHY/export"
    "?format=csv&gid=980271705"
)
GOOGLE_SHEET_JEWELRYFRUIT_KG_CSV = (
    "https://docs.google.com/spreadsheets/d/1Gb8feRt2FCCG0fpmhPKXcW1l061OefDD5UIejOhjcxY/gviz/tq"
    "?tqx=out:csv&gid=1831570299"
)

PRICE_SIGNAL_STYLE = {
    "blue": {
        "font": "2563EB",
        "fill": "DBEAFE",
        "label": "전일 대비 공급가 상승",
    },
    "red": {
        "font": "DC2626",
        "fill": "FEE2E2",
        "label": "전일 대비 공급가 하락",
    },
    "same": {
        "font": "0F172A",
        "fill": "F8FAFC",
        "label": "전일과 동일",
    },
}


@dataclass(frozen=True)
class SupplierOptionConfig:
    label: str
    supplier_option_name: str
    row: int
    sheet_name: str | None = None
    cell: str = "I"


@dataclass(frozen=True)
class SupplierMonitorConfig:
    key: str
    supplier_name: str
    product_name: str
    template_path: Path
    output_prefix: str
    options: tuple[SupplierOptionConfig, ...]
    source_type: Literal["adminplus", "google_sheet"] = "adminplus"
    output_suffix: str = ""
    output_name_pattern: str | None = None
    base_url: str | None = None
    search_value: str | None = None
    sheet_csv_url: str | None = None
    sheet_product_name: str | None = None
    sheet_product_column: str = "D"
    sheet_option_column: str = "E"
    sheet_quantity_column: str | None = None
    sheet_vip_column: str = "H"
    sheet_price_fallback_column: str | None = None
    sheet_previous_column: str | None = None
    skip_missing_options: bool = False

    @property
    def login_url(self) -> str:
        if not self.base_url:
            raise SupplierMonitorError(f"{self.key} monitor is not configured for adminplus login.")
        return f"{self.base_url}/partner/login.chk.php"

    @property
    def product_list_url(self) -> str:
        if not self.base_url:
            raise SupplierMonitorError(f"{self.key} monitor is not configured for adminplus product list.")
        return f"{self.base_url}/partner/"

    @property
    def product_detail_url(self) -> str:
        if not self.base_url:
            raise SupplierMonitorError(f"{self.key} monitor is not configured for adminplus detail page.")
        return f"{self.base_url}/partner/product/prt.grp.detail.pop.php"

    def output_filename(self, now: datetime) -> str:
        if self.output_name_pattern:
            return self.output_name_pattern.format(date=now.strftime("%y%m%d"))
        return f"{self.output_prefix}_{now.strftime('%y%m%d')}{self.output_suffix}.xlsx"


MONITOR_CONFIGS: dict[str, SupplierMonitorConfig] = {
    "myeongi": SupplierMonitorConfig(
        key="myeongi",
        source_type="adminplus",
        base_url="https://pbfcompany.adminplus.co.kr",
        supplier_name="쥬얼리프룻",
        product_name="명이나물(대명이)",
        search_value="명이",
        template_path=TEMPLATE_DIR / "쥬얼리프룻_명이나물(대명이)_소싱현황_원본.xlsx",
        output_prefix="쥬얼리프룻_명이나물(대명이)_V3.1",
        output_name_pattern="쥬얼리프룻 명이나물(대명이) 소싱현환관리_V3.1_{date}.xlsx",
        options=(
            SupplierOptionConfig("명이나물(대명이) 3kg", "명이나물(대명이) 3kg", 8),
            SupplierOptionConfig("명이나물(대명이) 2kg", "명이나물(대명이) 2kg", 9),
            SupplierOptionConfig("명이나물(대명이) 1kg", "명이나물(대명이) 1kg", 10),
            SupplierOptionConfig("명이나물(대명이) 500g", "명이나물(대명이) 500g", 11),
        ),
    ),
    "apple-corn-jewelryfruit": SupplierMonitorConfig(
        key="apple-corn-jewelryfruit",
        source_type="google_sheet",
        supplier_name="쥬얼리프룻",
        product_name="애플초당옥수수",
        sheet_csv_url=GOOGLE_SHEET_JEWELRYFRUIT_KG_CSV,
        sheet_product_name="애플초당옥수수",
        sheet_product_column="E",
        sheet_option_column="F",
        sheet_vip_column="I",
        sheet_price_fallback_column="G",
        sheet_previous_column="G",
        template_path=TEMPLATE_DIR / "초당옥수수_소싱현황_원본.xlsx",
        output_prefix="애플초당옥수수_쥬얼리프룻_V1",
        output_name_pattern="애플초당옥수수 소싱현황관리_V1_{date}.xlsx",
        options=(
            SupplierOptionConfig("애플초당옥수수 특품 5개", "애플초당옥수수(특품) 5개", 16, sheet_name="쥬얼리프룻"),
            SupplierOptionConfig("애플초당옥수수 특품 10개", "애플초당옥수수(특품) 10개", 17, sheet_name="쥬얼리프룻"),
            SupplierOptionConfig("애플초당옥수수 특품 15개", "애플초당옥수수(특품) 15개", 18, sheet_name="쥬얼리프룻"),
            SupplierOptionConfig("애플초당옥수수 특품 20개", "애플초당옥수수(특품) 20개", 19, sheet_name="쥬얼리프룻"),
        ),
    ),
    "kolrabi": SupplierMonitorConfig(
        key="kolrabi",
        source_type="adminplus",
        base_url="https://kkangta55.adminplus.co.kr",
        supplier_name="제주다팜",
        product_name="콜라비(정품)",
        search_value="콜라비",
        template_path=TEMPLATE_DIR / "콜라비_제주다팜_소싱현황_원본.xlsx",
        output_prefix="콜라비_제주다팜_V3.2",
        output_name_pattern="콜라비 소싱현황관리_V3.2_{date}(제주다팜).xlsx",
        options=(
            SupplierOptionConfig("콜라비 정품 3kg", "콜라비(정품 300~750g) 3kg", 8),
            SupplierOptionConfig("콜라비 정품 5kg", "콜라비(정품 300~750g) 5kg", 9),
            SupplierOptionConfig("콜라비 정품 10kg", "콜라비(정품 300~750g) 10kg", 10),
        ),
    ),
    "corn-jbt": SupplierMonitorConfig(
        key="corn-jbt",
        source_type="google_sheet",
        supplier_name="제주다팜",
        product_name="초당옥수수",
        sheet_csv_url=GOOGLE_SHEET_JEJUDAPAM_VEGETABLE_CSV,
        sheet_product_name="초당 옥수수",
        sheet_quantity_column="F",
        sheet_previous_column="I",
        template_path=TEMPLATE_DIR / "초당옥수수_소싱현황_원본.xlsx",
        output_prefix="초당옥수수_제주다팜_V1",
        output_name_pattern="초당옥수수 소싱현황관리_V1_{date}.xlsx",
        options=(
            SupplierOptionConfig("초당옥수수 중품 5개", "초당옥수수(중품) 5개", 8, sheet_name="쥬얼리프룻"),
            SupplierOptionConfig("초당옥수수 중품 10개", "초당옥수수(중품) 10개", 9, sheet_name="쥬얼리프룻"),
            SupplierOptionConfig("초당옥수수 중품 15개", "초당옥수수(중품) 15개", 10, sheet_name="쥬얼리프룻"),
            SupplierOptionConfig("초당옥수수 중품 20개", "초당옥수수(중품) 20개", 11, sheet_name="쥬얼리프룻"),
            SupplierOptionConfig("초당옥수수 특품 5개", "초당옥수수(특품) 5개", 12, sheet_name="쥬얼리프룻"),
            SupplierOptionConfig("초당옥수수 특품 10개", "초당옥수수(특품) 10개", 13, sheet_name="쥬얼리프룻"),
            SupplierOptionConfig("초당옥수수 특품 15개", "초당옥수수(특품) 15개", 14, sheet_name="쥬얼리프룻"),
            SupplierOptionConfig("초당옥수수 특품 20개", "초당옥수수(특품) 20개", 15, sheet_name="쥬얼리프룻"),
        ),
    ),
    "chamoe-altteul": SupplierMonitorConfig(
        key="chamoe-altteul",
        source_type="adminplus",
        base_url="https://kkangta55.adminplus.co.kr",
        supplier_name="제주다팜",
        product_name="알뜰 참외",
        search_value="참외",
        template_path=TEMPLATE_DIR / "성주참외_제주다팜_알뜰과_소싱현황_원본.xlsx",
        output_prefix="성주참외_제주다팜_알뜰과_V3",
        output_name_pattern="성주참외 소싱현황관리_V3_{date}_제주다팜 가정용혼합알뜰과.xlsx",
        options=(
            SupplierOptionConfig("성주참외 알뜰 랜덤과 2kg", "알뜰 참외 [랜덤과] 2kg (2-15입내외) [박스포함]", 11, sheet_name="제이비티"),
            SupplierOptionConfig("성주참외 알뜰 랜덤과 3kg", "알뜰 참외 [랜덤과] 3kg (3-25입내외) [박스포함]", 13, sheet_name="제이비티"),
            SupplierOptionConfig("성주참외 알뜰 랜덤과 5kg", "알뜰 참외 [랜덤과] 5kg (5-45입내외) [박스포함]", 12, sheet_name="제이비티"),
        ),
    ),
    "chamoe-jbt": SupplierMonitorConfig(
        key="chamoe-jbt",
        source_type="google_sheet",
        supplier_name="제이비티",
        product_name="성주참외 로얄과",
        sheet_csv_url=GOOGLE_SHEET_JBT_FRUIT_CSV,
        sheet_product_name="참외",
        template_path=TEMPLATE_DIR / "성주참외_제이비티_소싱현황_원본.xlsx",
        output_prefix="성주참외_제이비티_V3",
        output_name_pattern="성주참외 소싱현황관리_V3_{date}.xlsx",
        options=(
            SupplierOptionConfig("성주참외 로얄과 3kg", "가정용참외(로얄과)3kg(8-13과)", 15, sheet_name="제이비티"),
            SupplierOptionConfig("성주참외 로얄과 5kg", "가정용참외(로얄과)5kg(14-23과)", 17, sheet_name="제이비티"),
        ),
    ),
    "tomato-jbt": SupplierMonitorConfig(
        key="tomato-jbt",
        source_type="google_sheet",
        supplier_name="제이비티",
        product_name="대저토마토(고품위)",
        sheet_csv_url=GOOGLE_SHEET_JBT_FRUIT_CSV,
        sheet_product_name="토마토(고품위)",
        template_path=TEMPLATE_DIR / "대저토마토_제이비티_소싱현황_원본.xlsx",
        output_prefix="대저토마토_제이비티_고품위_V3",
        output_name_pattern="대저토마토 소싱현황관리_V3_{date}(로스3%,소득세16%기준).xlsx",
        skip_missing_options=True,
        options=(
            SupplierOptionConfig("대저 짭짤이 로얄과 1.5kg", "대저짭짤이특품(S)과 1.5kg", 8, sheet_name="제이비티"),
            SupplierOptionConfig("대저 짭짤이 로얄과 2.5kg", "대저짭짤이특품(S)과2.5kg", 9, sheet_name="제이비티"),
            SupplierOptionConfig("대저토마토 특품 L 2.5kg", "대저토마토특품(L)과2.5kg", 11, sheet_name="제이비티"),
            SupplierOptionConfig("대저토마토 특품 M 1.5kg", "대저토마토특품(M)과1.5kg", 12, sheet_name="제이비티"),
            SupplierOptionConfig("대저토마토 특품 M 2.5kg", "대저토마토특품(M)과2.5kg", 13, sheet_name="제이비티"),
        ),
    ),
    "watermelon-jbt": SupplierMonitorConfig(
        key="watermelon-jbt",
        source_type="google_sheet",
        supplier_name="제이비티",
        product_name="수박",
        sheet_csv_url=GOOGLE_SHEET_JBT_FRUIT_CSV,
        sheet_product_name="수박",
        template_path=TEMPLATE_DIR / "수박_제이비티_소싱현황_원본.xlsx",
        output_prefix="수박_제이비티_V3",
        output_name_pattern="수박 소싱현황관리_V3_{date}.xlsx",
        skip_missing_options=True,
        options=(
            SupplierOptionConfig("하우스수박 상품 6kg 이상", "하우스수박(상품)6kg이상", 8),
            SupplierOptionConfig("하우스수박 상품 7kg 이상", "하우스수박(상품)7kg이상", 10),
            SupplierOptionConfig("하우스수박 상품 8kg 이상", "하우스수박(상품)8kg이상", 12),
        ),
    ),
    "dureup-jbt": SupplierMonitorConfig(
        key="dureup-jbt",
        source_type="google_sheet",
        supplier_name="제이비티",
        product_name="남해땅두릅(특품)",
        sheet_csv_url=GOOGLE_SHEET_JBT_FARM_CSV,
        sheet_product_name="두릅(고품위)",
        template_path=TEMPLATE_DIR / "남해땅두릅_제이비티_소싱현황_원본.xlsx",
        output_prefix="남해땅두릅_제이비티_특품_V1",
        output_name_pattern="땅두릅(남해) 소싱현황관리_V1_{date}.xlsx",
        options=(
            SupplierOptionConfig("남해땅두릅 특품 500g", "남해땅두릅(특품)500g", 8, sheet_name="제이비티"),
            SupplierOptionConfig("남해땅두릅 특품 1kg", "남해땅두릅(특품)1kg", 9, sheet_name="제이비티"),
            SupplierOptionConfig("남해땅두릅 특품 2kg", "남해땅두릅(특품)2kg", 10, sheet_name="제이비티"),
        ),
    ),
}

PAUSED_SUPPLIER_MONITOR_KEYS = {"myeongi", "dureup-jbt"}

MONITOR_CONFIGS["dureup-jbt"] = replace(
    MONITOR_CONFIGS["dureup-jbt"],
    sheet_vip_column="H",
    options=(
        SupplierOptionConfig(
            "\ub0a8\ud574\ub545\ub450\ub985 \ud2b9\ud488 500g",
            "\ub0a8\ud574\ub545\ub450\ub985(\ud2b9\ud488)500g",
            8,
            sheet_name="\uc81c\uc774\ube44\ud2f0",
        ),
        SupplierOptionConfig(
            "\ub0a8\ud574\ub545\ub450\ub985 \ud2b9\ud488 1kg",
            "\ub0a8\ud574\ub545\ub450\ub985(\ud2b9\ud488)1kg",
            9,
            sheet_name="\uc81c\uc774\ube44\ud2f0",
        ),
        SupplierOptionConfig(
            "\ub0a8\ud574\ub545\ub450\ub985 \ud2b9\ud488 2kg",
            "\ub0a8\ud574\ub545\ub450\ub985(\ud2b9\ud488)2kg",
            10,
            sheet_name="\uc81c\uc774\ube44\ud2f0",
        ),
        SupplierOptionConfig(
            "\ub0a8\ud574\ub545\ub450\ub985 \uc7a5\uc544\ucc0c\uc6a9 500g",
            "\ub0a8\ud574\ub545\ub450\ub985(\uc7a5\uc544\ucc0c\uc6a9)500g",
            11,
            sheet_name="\uc81c\uc774\ube44\ud2f0",
        ),
        SupplierOptionConfig(
            "\ub0a8\ud574\ub545\ub450\ub985 \uc7a5\uc544\ucc0c\uc6a9 1kg",
            "\ub0a8\ud574\ub545\ub450\ub985(\uc7a5\uc544\ucc0c\uc6a9)1kg",
            12,
            sheet_name="\uc81c\uc774\ube44\ud2f0",
        ),
        SupplierOptionConfig(
            "\ub0a8\ud574\ub545\ub450\ub985 \uc7a5\uc544\ucc0c\uc6a9 2kg",
            "\ub0a8\ud574\ub545\ub450\ub985(\uc7a5\uc544\ucc0c\uc6a9)2kg",
            13,
            sheet_name="\uc81c\uc774\ube44\ud2f0",
        ),
        SupplierOptionConfig(
            "\ub0a8\ud574\ub545\ub450\ub985 \ud280\uae40\uc6a9 500g",
            "\ub0a8\ud574\ub545\ub450\ub985(\ud280\uae40\uc6a9)500g",
            14,
            sheet_name="\uc81c\uc774\ube44\ud2f0",
        ),
        SupplierOptionConfig(
            "\ub0a8\ud574\ub545\ub450\ub985 \ud280\uae40\uc6a9 1kg",
            "\ub0a8\ud574\ub545\ub450\ub985(\ud280\uae40\uc6a9)1kg",
            15,
            sheet_name="\uc81c\uc774\ube44\ud2f0",
        ),
        SupplierOptionConfig(
            "\ub0a8\ud574\ub545\ub450\ub985 \ud280\uae40\uc6a9 2kg",
            "\ub0a8\ud574\ub545\ub450\ub985(\ud280\uae40\uc6a9)2kg",
            16,
            sheet_name="\uc81c\uc774\ube44\ud2f0",
        ),
    ),
)


class SupplierMonitorError(RuntimeError):
    pass


def _normalize_option_name(raw: str) -> str:
    text = re.sub(r"<[^>]+>", "", raw or "")
    text = unescape(text).replace("\xa0", " ")
    text = re.sub(r"^\[\d+\]\s*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_price(raw: object) -> int:
    if raw is None:
        raise SupplierMonitorError("공급가를 읽을 수 없습니다.")
    if isinstance(raw, (int, float)):
        return int(raw)
    digits = re.sub(r"[^\d]", "", str(raw))
    if not digits:
        raise SupplierMonitorError(f"숫자 공급가를 찾지 못했습니다: {raw}")
    return int(digits)


def _price_signal(previous_supplier_price: int, supplier_price: int) -> str:
    if previous_supplier_price < supplier_price:
        return "blue"
    if previous_supplier_price > supplier_price:
        return "red"
    return "same"


def _snapshot_lookup_keys(option_name: str, supplier_option_name: str) -> set[tuple[str, str]]:
    return {
        (option_name, supplier_option_name),
        (_normalize_option_name(option_name), _normalize_option_name(supplier_option_name)),
        (
            re.sub(r"\s+", "", _normalize_option_name(option_name)),
            re.sub(r"\s+", "", _normalize_option_name(supplier_option_name)),
        ),
    }


def _supplier_price_lookup(prices: dict[str, int], supplier_option_name: str) -> int | None:
    normalized_name = _normalize_option_name(supplier_option_name)
    compact_name = re.sub(r"\s+", "", normalized_name)
    for key in (supplier_option_name, normalized_name, compact_name):
        if key in prices:
            return prices[key]
    for key, price in prices.items():
        if re.sub(r"\s+", "", _normalize_option_name(key)) == compact_name:
            return price
    partial_matches = [
        price
        for key, price in prices.items()
        if compact_name
        and (
            compact_name in re.sub(r"\s+", "", _normalize_option_name(key))
            or re.sub(r"\s+", "", _normalize_option_name(key)) in compact_name
        )
    ]
    if len(set(partial_matches)) == 1:
        return partial_matches[0]
    return None


def _sheet_product_matches(actual: str, expected: str) -> bool:
    actual_name = _normalize_option_name(actual)
    expected_name = _normalize_option_name(expected)
    if actual_name == expected_name:
        return True
    actual_compact = re.sub(r"\s+", "", actual_name)
    expected_compact = re.sub(r"\s+", "", expected_name)
    return bool(
        actual_compact
        and expected_compact
        and (expected_compact in actual_compact or actual_compact in expected_compact)
    )


def _google_sheet_option_keys(product_name: str, option_name: str, quantity_name: str = "") -> list[str]:
    product = _normalize_option_name(product_name)
    option = _normalize_option_name(option_name)
    quantity = _normalize_option_name(quantity_name)
    keys: list[str] = []

    def add(value: str) -> None:
        cleaned = _normalize_option_name(value)
        if cleaned and cleaned not in keys:
            keys.append(cleaned)

    add(option)
    if option and quantity:
        add(f"{option} {quantity}")

    product_compact = re.sub(r"\s+", "", product)
    product_aliases = [product_compact] if product_compact else []
    for alias in ("애플초당옥수수", "초당옥수수"):
        if alias in product_compact and alias not in product_aliases:
            product_aliases.append(alias)

    grade = ""
    for candidate in ("중품", "특품", "상품", "정품", "대중과", "랜덤과", "로얄과", "중소과"):
        if candidate in option:
            grade = candidate
            break
    count_match = re.search(r"(\d+)\s*개", f"{option} {quantity}")
    count_name = f"{count_match.group(1)}개" if count_match else ""
    normalized_quantity = count_name or quantity
    for product_alias in product_aliases:
        if grade and normalized_quantity:
            add(f"{product_alias}({grade}) {normalized_quantity}")
            add(f"{product_alias} {grade} {normalized_quantity}")
        if option and quantity:
            add(f"{product_alias} {option} {quantity}")
    return keys


def _persist_output(filename: str, payload: bytes) -> Path:
    output_dir = UPLOAD_DIR / "supplier-price-monitor"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename
    output_path.write_bytes(payload)
    return output_path


def _select_sheet(workbook, sheet_name: str | None):
    if sheet_name and sheet_name in workbook.sheetnames:
        return workbook[sheet_name]
    return workbook[workbook.sheetnames[0]]


def _column_index(column_name: str) -> int:
    value = 0
    for char in column_name.upper():
        if not ("A" <= char <= "Z"):
            raise SupplierMonitorError(f"Invalid column name: {column_name}")
        value = value * 26 + (ord(char) - ord("A") + 1)
    return value - 1


async def _login(client: httpx.AsyncClient, config: SupplierMonitorConfig) -> None:
    if not PBF_PARTNER_ID or not PBF_PARTNER_PASSWORD:
        raise SupplierMonitorError("PBF_PARTNER_ID 또는 PBF_PARTNER_PASSWORD가 설정되지 않았습니다.")

    response = await client.post(
        config.login_url,
        data={"admid": PBF_PARTNER_ID, "admpwd": PBF_PARTNER_PASSWORD},
    )
    response.raise_for_status()
    if response.text.strip().lower() != "ok":
        raise SupplierMonitorError("관리자 사이트 로그인에 실패했습니다.")


async def _find_product_code(client: httpx.AsyncClient, config: SupplierMonitorConfig) -> str:
    response = await client.get(
        config.product_list_url,
        params={
            "mod": "product/json",
            "actpage": "prt.list.proc",
            "searchval": config.search_value,
            "page": "1",
            "order": "",
            "by": "",
        },
    )
    response.raise_for_status()
    matches = re.findall(
        r"""prtView\("(?P<pcode>\d+)","2","1"\).*?<div class='pname'>(?P<name>[^<]+)</div>""",
        response.text,
        flags=re.DOTALL,
    )
    for pcode, product_name in matches:
        if _normalize_option_name(product_name) == _normalize_option_name(config.product_name):
            return pcode
    target = re.sub(r"\s+", "", _normalize_option_name(config.product_name))
    partial_matches = []
    for pcode, product_name in matches:
        candidate = re.sub(r"\s+", "", _normalize_option_name(product_name))
        if target and (target in candidate or candidate in target):
            partial_matches.append((pcode, product_name))
    if len(partial_matches) == 1:
        return partial_matches[0][0]
    raise SupplierMonitorError(f"{config.product_name} 상품 코드를 찾지 못했습니다.")


async def _fetch_adminplus_prices(client: httpx.AsyncClient, config: SupplierMonitorConfig, product_code: str) -> dict[str, int]:
    response = await client.get(config.product_detail_url, params={"pcode": product_code})
    response.raise_for_status()

    matches = re.findall(
        r"""<tr[^>]*>\s*<td style='border-left:0px'>(?P<option>.*?)</td>.*?<td style='text-align:right;color:black;font-weight:bold'>(?P<price>.*?)</td>""",
        response.text,
        flags=re.DOTALL,
    )

    prices: dict[str, int] = {}
    for option_name, price in matches:
        normalized_name = _normalize_option_name(option_name)
        if normalized_name:
            prices[normalized_name] = _parse_price(price)
    if not prices:
        raise SupplierMonitorError(f"{config.product_name} 옵션 공급가를 읽지 못했습니다.")
    return prices


async def _fetch_google_sheet_prices(
    client: httpx.AsyncClient,
    config: SupplierMonitorConfig,
) -> tuple[dict[str, int], dict[str, int]]:
    if not config.sheet_csv_url or not config.sheet_product_name:
        raise SupplierMonitorError(f"{config.key} monitor is missing google sheet configuration.")

    response = await client.get(config.sheet_csv_url)
    response.raise_for_status()

    rows = list(csv.reader(StringIO(response.text)))
    if not rows:
        raise SupplierMonitorError("구글시트 데이터가 비어 있습니다.")

    product_index = _column_index(config.sheet_product_column)
    option_index = _column_index(config.sheet_option_column)
    vip_index = _column_index(config.sheet_vip_column)
    quantity_index = _column_index(config.sheet_quantity_column) if config.sheet_quantity_column else None
    fallback_index = _column_index(config.sheet_price_fallback_column) if config.sheet_price_fallback_column else None
    previous_index = _column_index(config.sheet_previous_column) if config.sheet_previous_column else None

    prices: dict[str, int] = {}
    previous_prices: dict[str, int] = {}
    current_product = ""
    current_option = ""
    for row in rows:
        required_indexes = [product_index, option_index, vip_index]
        if quantity_index is not None:
            required_indexes.append(quantity_index)
        if fallback_index is not None:
            required_indexes.append(fallback_index)
        if previous_index is not None:
            required_indexes.append(previous_index)
        if max(required_indexes) >= len(row):
            continue
        product_cell = _normalize_option_name(row[product_index])
        option_cell = _normalize_option_name(row[option_index])
        if product_cell:
            current_product = product_cell
        if option_cell:
            current_option = option_cell
        product_name = current_product
        option_name = current_option
        quantity_name = _normalize_option_name(row[quantity_index]) if quantity_index is not None else ""
        vip_price = row[vip_index]
        if fallback_index is not None and not vip_price.strip():
            vip_price = row[fallback_index]
        if not _sheet_product_matches(product_name, config.sheet_product_name) or not option_name or not vip_price.strip():
            continue
        option_keys = _google_sheet_option_keys(product_name, option_name, quantity_name)
        if not option_keys:
            continue
        parsed_price = _parse_price(vip_price)
        previous_price = None
        if previous_index is not None and row[previous_index].strip():
            try:
                previous_price = _parse_price(row[previous_index])
            except SupplierMonitorError:
                previous_price = None
        for option_key in option_keys:
            prices[option_key] = parsed_price
            if previous_price is not None:
                previous_prices[option_key] = previous_price

    if not prices:
        if config.skip_missing_options:
            return {}, {}
        raise SupplierMonitorError(f"구글시트에서 {config.sheet_product_name} VIP 공급가를 찾지 못했습니다.")
    return prices, previous_prices


def _load_workbooks(config: SupplierMonitorConfig):
    if not config.template_path.exists():
        raise SupplierMonitorError(f"기준 엑셀 파일이 없습니다: {config.template_path.name}")
    editable_wb = load_workbook(filename=str(config.template_path))
    data_wb = load_workbook(filename=str(config.template_path), data_only=True)
    return editable_wb, data_wb


def _worksheet_xml_paths(template_path: Path) -> dict[str, str]:
    main_ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    rel_ns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    package_rel_ns = "{http://schemas.openxmlformats.org/package/2006/relationships}"

    with ZipFile(template_path, "r") as workbook_zip:
        workbook_root = ET.fromstring(workbook_zip.read("xl/workbook.xml"))
        rels_root = ET.fromstring(workbook_zip.read("xl/_rels/workbook.xml.rels"))

    relationships = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rels_root.findall(f"{package_rel_ns}Relationship")
    }

    paths: dict[str, str] = {}
    for sheet in workbook_root.findall(f"{main_ns}sheets/{main_ns}sheet"):
        sheet_name = sheet.attrib["name"]
        relationship_id = sheet.attrib[f"{rel_ns}id"]
        target = relationships[relationship_id].lstrip("/")
        paths[sheet_name] = target if target.startswith("xl/") else f"xl/{target}"
    return paths


def _replace_numeric_cell_value(sheet_xml: bytes, cell_ref: str, value: int) -> bytes:
    xml_text = sheet_xml.decode("utf-8")
    pattern = re.compile(
        rf'(<c\b(?=[^>]*\br="{re.escape(cell_ref)}")[^>]*>)(.*?)(</c>)',
        flags=re.DOTALL,
    )

    def replace_cell(match: re.Match[str]) -> str:
        opening_tag = re.sub(r'\s+t="[^"]*"', "", match.group(1))
        body = match.group(2)
        body = re.sub(r"<is\b[^>]*>.*?</is>", "", body, flags=re.DOTALL)
        body = re.sub(r"<f\b[^>]*>.*?</f>", "", body, flags=re.DOTALL)
        if re.search(r"<v>.*?</v>", body, flags=re.DOTALL):
            body = re.sub(r"<v>.*?</v>", f"<v>{value}</v>", body, count=1, flags=re.DOTALL)
        else:
            body = f"{body}<v>{value}</v>"
        return f"{opening_tag}{body}{match.group(3)}"

    updated_xml, changed_count = pattern.subn(replace_cell, xml_text, count=1)
    if changed_count != 1:
        raise SupplierMonitorError(f"엑셀 템플릿에서 {cell_ref} 셀을 찾지 못했습니다.")
    return updated_xml.encode("utf-8")


def _force_excel_recalculation(workbook_xml: bytes) -> bytes:
    xml_text = workbook_xml.decode("utf-8")

    def set_attr(tag: str, attr: str, value: str) -> str:
        if re.search(rf'\s{attr}="[^"]*"', tag):
            return re.sub(rf'\s{attr}="[^"]*"', f' {attr}="{value}"', tag)
        if tag.endswith("/>"):
            return f'{tag[:-2]} {attr}="{value}"/>'
        return f'{tag[:-1]} {attr}="{value}">'

    def replace_calc_pr(match: re.Match[str]) -> str:
        tag = match.group(0)
        for attr, value in (("calcMode", "auto"), ("fullCalcOnLoad", "1"), ("forceFullCalc", "1")):
            tag = set_attr(tag, attr, value)
        return tag

    updated_xml, changed_count = re.subn(r"<calcPr\b[^>]*/?>", replace_calc_pr, xml_text, count=1)
    if changed_count:
        return updated_xml.encode("utf-8")
    return xml_text.replace(
        "</workbook>",
        '<calcPr calcMode="auto" fullCalcOnLoad="1" forceFullCalc="1"/></workbook>',
    ).encode("utf-8")


def _patch_workbook_values(config: SupplierMonitorConfig, updates: list[tuple[str, str, int]]) -> bytes:
    sheet_paths = _worksheet_xml_paths(config.template_path)
    updates_by_path: dict[str, list[tuple[str, int]]] = {}
    for sheet_name, cell_ref, value in updates:
        sheet_path = sheet_paths.get(sheet_name)
        if not sheet_path:
            raise SupplierMonitorError(f"엑셀 템플릿에서 시트를 찾지 못했습니다: {sheet_name}")
        updates_by_path.setdefault(sheet_path, []).append((cell_ref, value))

    output_buffer = BytesIO()
    with ZipFile(config.template_path, "r") as source_zip, ZipFile(output_buffer, "w") as target_zip:
        for item in source_zip.infolist():
            item_data = source_zip.read(item.filename)
            if item.filename in updates_by_path:
                for cell_ref, value in updates_by_path[item.filename]:
                    item_data = _replace_numeric_cell_value(item_data, cell_ref, value)
            elif item.filename == "xl/workbook.xml":
                item_data = _force_excel_recalculation(item_data)
            target_zip.writestr(item, item_data)

    return output_buffer.getvalue()


async def _collect_supplier_prices(config: SupplierMonitorConfig) -> tuple[dict[str, int], dict[str, int]]:
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        if config.source_type == "google_sheet":
            return await _fetch_google_sheet_prices(client, config)

        await _login(client, config)
        product_code = await _find_product_code(client, config)
        return await _fetch_adminplus_prices(client, config, product_code), {}


def _find_monitor_config(key: str) -> SupplierMonitorConfig | None:
    aliases = {key, key.replace("_", "-"), key.replace("-", "_")}
    for alias in aliases:
        if alias in MONITOR_CONFIGS:
            return MONITOR_CONFIGS[alias]
    return None


def is_supplier_monitor_paused(key: str) -> bool:
    config = _find_monitor_config(key)
    monitor_key = config.key if config else key.replace("_", "-")
    return monitor_key in PAUSED_SUPPLIER_MONITOR_KEYS


def active_supplier_monitor_keys() -> tuple[str, ...]:
    return tuple(key for key in MONITOR_CONFIGS if key not in PAUSED_SUPPLIER_MONITOR_KEYS)


async def run_supplier_monitor(key: str) -> tuple[dict, bytes, str]:
    config = _find_monitor_config(key)
    if not config:
        raise SupplierMonitorError(f"지원하지 않는 공급가 모니터입니다: {key}")
    if is_supplier_monitor_paused(config.key):
        raise SupplierMonitorError(f"{config.product_name} 공급가 모니터링은 품절로 일시중지 중입니다.")

    supplier_prices, source_previous_prices = await _collect_supplier_prices(config)
    editable_wb, data_wb = _load_workbooks(config)
    now = datetime.now(KST)
    run_date = now.date().isoformat()

    from app import db as database

    previous_snapshot_rows = await database.latest_supplier_price_snapshots_before_run_date(
        config.key,
        run_date,
    )
    previous_price_map: dict[tuple[str, str], int] = {}
    for snapshot in previous_snapshot_rows:
        option_name = str(snapshot.get("option_name") or "")
        supplier_option_name = str(snapshot.get("supplier_option_name") or option_name)
        supplier_price = int(snapshot.get("supplier_price") or 0)
        if supplier_price <= 0:
            continue
        for lookup_key in _snapshot_lookup_keys(option_name, supplier_option_name):
            previous_price_map.setdefault(lookup_key, supplier_price)

    rows: list[dict] = []
    workbook_updates: list[tuple[str, str, int]] = []
    for option in config.options:
        editable_ws = _select_sheet(editable_wb, option.sheet_name)
        data_ws = _select_sheet(data_wb, option.sheet_name)
        cell_ref = f"{option.cell}{option.row}"
        workbook_price = _parse_price(data_ws[cell_ref].value)
        supplier_price = _supplier_price_lookup(supplier_prices, option.supplier_option_name)
        if supplier_price is None:
            if config.skip_missing_options:
                logger.info(
                    "Skip missing supplier option for %s: %s",
                    config.key,
                    option.supplier_option_name,
                )
                continue
            raise SupplierMonitorError(f"옵션 공급가를 찾지 못했습니다: {option.supplier_option_name}")

        previous_supplier_price = None
        for lookup_key in _snapshot_lookup_keys(option.label, option.supplier_option_name):
            if lookup_key in previous_price_map:
                previous_supplier_price = previous_price_map[lookup_key]
                break
        if previous_supplier_price is None:
            previous_supplier_price = _supplier_price_lookup(source_previous_prices, option.supplier_option_name)
        if previous_supplier_price is None:
            previous_supplier_price = supplier_price

        signal = _price_signal(previous_supplier_price, supplier_price)
        style = PRICE_SIGNAL_STYLE[signal]
        workbook_updates.append((editable_ws.title, cell_ref, supplier_price))

        rows.append(
            {
                "option_name": option.label,
                "supplier_option_name": option.supplier_option_name,
                "sheet_name": option.sheet_name or editable_ws.title,
                "sheet_row": option.row,
                "cell": cell_ref,
                "spreadsheet_price": previous_supplier_price,
                "workbook_price": workbook_price,
                "comparison_basis": "previous_supplier_snapshot",
                "has_previous_snapshot": bool(previous_snapshot_rows),
                "supplier_price": supplier_price,
                "diff": supplier_price - previous_supplier_price,
                "signal": signal,
                "signal_label": style["label"],
            }
        )

    output_filename = config.output_filename(now)
    output_bytes = _patch_workbook_values(config, workbook_updates)
    _persist_output(output_filename, output_bytes)

    summary = {
        "key": config.key,
        "title": "공급가 단가변경 바로 알림",
        "supplier_name": config.supplier_name,
        "product_name": config.product_name,
        "checked_at": now.isoformat(),
        "output_filename": output_filename,
        "total_items": len(rows),
        "changed_items": sum(1 for row in rows if row["diff"] != 0),
        "blue_count": sum(1 for row in rows if row["signal"] == "blue"),
        "red_count": sum(1 for row in rows if row["signal"] == "red"),
        "same_count": sum(1 for row in rows if row["signal"] == "same"),
        "rows": rows,
    }
    await database.save_supplier_price_snapshot(summary)
    await database.save_supplier_price_monitor_run(config.key, summary)
    return summary, output_bytes, output_filename


async def refresh_supplier_price_snapshots(keys: tuple[str, ...] | None = None) -> dict[str, str]:
    target_keys = keys or active_supplier_monitor_keys()
    results: dict[str, str] = {}
    from app import db as database

    for key in target_keys:
        if is_supplier_monitor_paused(key):
            results[key] = "paused"
            continue
        try:
            await run_supplier_monitor(key)
            results[key] = "ok"
        except Exception as exc:
            logger.warning("Supplier price snapshot refresh failed for %s: %s", key, exc)
            await database.save_supplier_price_monitor_run(key, status="error", error_message=str(exc))
            results[key] = f"error: {exc}"
    return results


async def run_myeongi_monitor() -> tuple[dict, bytes, str]:
    return await run_supplier_monitor("myeongi")


async def run_kolrabi_monitor() -> tuple[dict, bytes, str]:
    return await run_supplier_monitor("kolrabi")


async def run_chamoe_altteul_monitor() -> tuple[dict, bytes, str]:
    return await run_supplier_monitor("chamoe-altteul")


if __name__ == "__main__":
    import asyncio
    import json

    monitor_key = sys.argv[1] if len(sys.argv) > 1 else "myeongi"
    summary, _, _ = asyncio.run(run_supplier_monitor(monitor_key))
    print(json.dumps(summary, ensure_ascii=False))
