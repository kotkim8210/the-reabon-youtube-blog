"""꿀고구마 해달 발주서 파일명 = '해달 발주서 한진양식_알제이시스템즈_꿀고구마(yymmdd).xlsx' (2026-10-07 요청).

호박고구마(아이티소프트) 발주서와 같은 해달로 함께 나가므로 파일명에 상품명을 붙여 구분한다.
"""

import asyncio
import re
from io import BytesIO

from openpyxl import Workbook

from app.processors import goguma_auto, goguma_order

KKUL_NAME = re.compile(r"해달 발주서 한진양식_알제이시스템즈_꿀고구마\(\d{6}\)\.xlsx")


def test_goguma_page_api_order_filename(monkeypatch):
    async def fake_collect(_from, _to):
        return [{
            "name": "테스트", "phone": "010-0000-0000", "zipcode": "12345", "address": "서울 어딘가",
            "quantity": 1, "product": "꿀고구마 3Kg (중상)", "memo": "", "order_id": "T1",
        }]

    monkeypatch.setattr(goguma_auto, "collect_orders", fake_collect)
    _bytes, filename, stats = asyncio.run(goguma_auto.process_from_api("2026-10-06", "2026-10-07"))
    assert KKUL_NAME.fullmatch(filename), filename
    assert stats["total"] == 1


def test_goguma_deliverylist_order_filename():
    wb = Workbook()
    ws = wb.active
    ws.append(["헤더"] * 31)
    row = [""] * 31
    row[2], row[10], row[11], row[22], row[26] = "C1", "해남 황금 꿀고구마", "1박스 황금 꿀고구마 3Kg (중상)", 1, "테스트"
    ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    _bytes, filename, _stats = goguma_order.process(buf.getvalue())
    assert KKUL_NAME.fullmatch(filename), filename
