"""쿠팡 쪽 송장 짝짓기 — 이름만 같으면 남의 주문에 송장을 넣던 문제 (2026-11-16 리뷰 2순위).

1) 꿀고구마 쿠팡 API 송장등록(goguma_tracking_api): 해달 회신 줄 ↔ 쿠팡 주문(결제완료·상품준비중)을 이름만으로 짝지어
   ① 토스 고객 김민지 송장이 다른 쿠팡 김민지(결제완료) 주문에 확인 처리·등록됐고
   ② 같은 회신 파일을 다시 올리면 같은 사람의 새 주문에 옛 송장이 들어갔다.
   → 이름 + (전화 일치 또는 옵션 일치) 필수, 결제완료는 전화가 맞을 때만 확인 처리, 이미 다른 주문에 들어간 송장은 skip.
2) 제주다팜 송장입력(tracking_input) 6~8단계: 회신·DeliveryList 양쪽 전화가 다르면 주소까지 같아야 넣는다.
"""

import asyncio
from io import BytesIO

import pytest
from openpyxl import Workbook, load_workbook

from app.processors import goguma_tracking_api as gta
from app.processors import tracking_input

GOGUMA = "[해남직송] 재구매1위 고당도 선별 해남 꿀고구마 베니하루카"
ADDR_A = "서울특별시 강남구 테헤란로 1"
ADDR_B = "부산광역시 해운대구 센텀중앙로 2"

_HANJIN_HEADERS = [
    "받으시는 분", "받으시는 분 전화", "받는분담당자(선택)", "받는분핸드폰(선택)", "받는분우편번호(선택)",
    "받는분총주소", "보내시는 분", "보내시는 분 전화", "보내는분담당자(선택)", "보내는분담당자HP(선택)",
    "보내는분우편번호(선택)", "보내는분총주소", "수량", "품목명", "운임Type", "지불조건", "출고번호", "특기사항",
]


def _haedal_reply(rows: list[tuple[str, str, str, str, str]]) -> bytes:
    """해달 한진양식 회신: (받으시는 분, 전화, 총주소, 품목명, 출고번호=송장)."""
    wb = Workbook()
    ws = wb.active
    ws.append(_HANJIN_HEADERS)
    for name, phone, address, product, tracking in rows:
        row = [""] * len(_HANJIN_HEADERS)
        row[0], row[1], row[4], row[5] = name, phone, "12345", address
        row[6], row[7], row[12], row[13] = "식품애착", "010-5700-7756", 1, product
        row[15], row[16] = "선불", tracking
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _shipment(box: int, name: str, phone: str, option: str, address: str, invoice: str | None = None) -> dict:
    """쿠팡 발주서 목록 조회(ordersheets) 응답의 shipment 하나."""
    return {
        "shipmentBoxId": box,
        "orderId": box * 10,
        "receiver": {"name": name, "safeNumber": phone, "addr1": address, "addr2": ""},
        "invoiceNumber": invoice,
        "orderItems": [{
            "vendorItemId": box * 100,
            "vendorItemName": f"{GOGUMA}, 1박스, 황금 꿀고구마 {option}",
            "sellerProductName": GOGUMA,
            "salesPrice": 21900,
            "orderPrice": 21900,
        }],
    }


def _bundle(box: int, name: str, phone: str, address: str, items: list[tuple[str, int]]) -> dict:
    """상품 여러 개가 한 묶음(shipmentBoxId)인 shipment — items: (옵션, 판매가)."""
    shipment = _shipment(box, name, phone, items[0][0], address)
    shipment["orderItems"] = [{
        "vendorItemId": box * 100 + idx,
        "vendorItemName": f"{GOGUMA}, 1박스, 황금 꿀고구마 {option}",
        "sellerProductName": GOGUMA,
        "salesPrice": price,
        "orderPrice": price,
    } for idx, (option, price) in enumerate(items)]
    return shipment


class FakeCoupang:
    """쿠팡 주문 상태를 흉내 낸다 — 확인 처리하면 결제완료→상품준비중, 송장을 올리면 배송지시(DEPARTURE)+송장번호."""

    def __init__(self, shipments: dict[str, list[dict]]):
        self.shipments = {status: list(rows) for status, rows in shipments.items()}
        self.confirm_calls: list[list[int]] = []
        self.upload_calls: list[list[tuple[int, str]]] = []
        self.list_none_status: str | None = None    # 이 상태 조회는 응답 없음(재시도 소진)
        self.list_raise_status: str | None = None   # 이 상태 조회는 예외

    def move(self, box: int, src: str, dst: str, **changes) -> None:
        for shipment in list(self.shipments.get(src, [])):
            if shipment["shipmentBoxId"] == box:
                self.shipments[src].remove(shipment)
                shipment.update(changes)
                self.shipments.setdefault(dst, []).append(shipment)

    async def get_order_sheets(self, created_at_from=None, created_at_to=None, order_status=None,
                               max_per_page=50, next_token=None):
        if order_status == self.list_raise_status:
            raise RuntimeError("쿠팡 API 재시도 소진")
        if order_status == self.list_none_status:
            return None
        return {"code": 200, "message": "OK", "data": list(self.shipments.get(order_status, [])), "nextToken": ""}

    async def confirm_orders(self, shipment_box_ids):
        self.confirm_calls.append(sorted(shipment_box_ids))
        for box in shipment_box_ids:
            self.move(box, "ACCEPT", "INSTRUCT")
        return {"code": 200}

    async def upload_invoices(self, dtos):
        self.upload_calls.append([(dto["shipmentBoxId"], dto["invoiceNumber"]) for dto in dtos])
        # 묶음(shipmentBoxId) 단위로 받는다 — 같은 묶음 상품 여러 개(송장 하나)는 한 번에 등록된다
        ready = {s["shipmentBoxId"] for s in self.shipments.get("INSTRUCT", [])}
        response = []
        for dto in dtos:
            ok = dto["shipmentBoxId"] in ready
            response.append({
                "shipmentBoxId": dto["shipmentBoxId"],
                "succeed": ok,
                "resultCode": "OK" if ok else "INVALID_STATUS",
                "resultMessage": "" if ok else "상품준비중 상태가 아닙니다",
            })
        for dto in dtos:
            if dto["shipmentBoxId"] in ready:
                self.move(dto["shipmentBoxId"], "INSTRUCT", "DEPARTURE", invoiceNumber=dto["invoiceNumber"])
        return {"code": 200, "data": {"responseCode": 0, "responseList": response}}


@pytest.fixture
def run(monkeypatch):
    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr(gta.asyncio, "sleep", _no_sleep)

    def _run(client: FakeCoupang, reply: bytes) -> dict:
        monkeypatch.setattr(gta, "coupang_goguma_client", client)
        return asyncio.run(gta.process_tracking_api(reply))

    return _run


# ── ① 토스 고객 김민지 송장이 다른 쿠팡 김민지(결제완료) 주문에 확인 처리·등록 ──
def test_toss_namesake_tracking_not_confirmed_or_registered_on_other_coupang_order(run):
    reply = _haedal_reply([("김민지", "010-1111-2222", ADDR_A, "꿀고구마 5Kg (특상)", "412345678901")])
    client = FakeCoupang({"ACCEPT": [_shipment(9001, "김민지", "0504-9999-0000", "3Kg (중상)", ADDR_B)]})
    result = run(client, reply)
    assert client.confirm_calls == [] and client.upload_calls == []      # 고객 즉시취소가 막히지 않게 확인 처리도 안 함
    assert (result["success"], result["fail"], result["skip"]) == (0, 0, 1)
    assert "전화·옵션 불일치" in result["results"][0]["message"]


def test_accept_order_with_same_option_but_other_phone_is_not_confirmed(run):
    """결제완료 주문은 전화가 맞을 때만 확인 처리 — 이름·옵션·주소가 같아도 전화가 다르면 건드리지 않는다."""
    reply = _haedal_reply([("김민지", "010-1111-2222", ADDR_A, "꿀고구마 5Kg (특상)", "412345678901")])
    client = FakeCoupang({"ACCEPT": [_shipment(9002, "김민지", "0504-9999-0000", "5Kg (특상)", ADDR_A)]})
    result = run(client, reply)
    assert client.confirm_calls == [] and client.upload_calls == []
    assert result["skip"] == 1 and "결제완료" in result["results"][0]["message"]


def test_instruct_namesake_same_option_other_phone_and_address_skipped(run):
    """상품준비중이어도 전화·주소가 다 다르면 동명이인 — 옵션만 같다고 넣지 않는다."""
    reply = _haedal_reply([("김민지", "010-1111-2222", ADDR_A, "꿀고구마 5Kg (특상)", "412345678901")])
    client = FakeCoupang({"INSTRUCT": [_shipment(9003, "김민지", "0504-9999-0000", "5Kg (특상)", ADDR_B)]})
    result = run(client, reply)
    assert client.upload_calls == []
    assert result["skip"] == 1 and "동명이인" in result["results"][0]["message"]


# ── ② 같은 회신 파일 재실행 — 같은 사람의 새 주문에 옛 송장 ──
def _yoon_reply() -> bytes:
    return _haedal_reply([("윤재주문", "0504-1000-0001", ADDR_A, "꿀고구마 5Kg (특상)", "412300000001")])


def _yoon_client() -> FakeCoupang:
    return FakeCoupang({
        "INSTRUCT": [_shipment(7001, "윤재주문", "0504-1000-0001", "5Kg (특상)", ADDR_A)],
        "ACCEPT": [_shipment(7002, "윤재주문", "0504-1000-0002", "5Kg (특상)", ADDR_A)],   # 같은 사람의 새 주문
    })


def test_rerun_same_reply_does_not_put_old_tracking_on_new_accept_order(run):
    client = _yoon_client()
    first = run(client, _yoon_reply())
    assert first["success"] == 1 and client.upload_calls == [[(7001, "412300000001")]]
    assert client.confirm_calls == []                                    # 새 결제완료 주문은 1차에도 안 건드림

    second = run(client, _yoon_reply())
    assert client.upload_calls == [[(7001, "412300000001")]]              # 재실행 땐 아무것도 안 올림
    assert client.confirm_calls == []
    assert (second["success"], second["skip"]) == (0, 1)
    assert "이미 등록된 송장" in second["results"][0]["message"]
    assert second["results"][0]["tracking"] == "412300000001"


def test_rerun_blocked_even_when_new_order_is_already_instruct(run):
    """새 주문을 Wing에서 먼저 확인(상품준비중)해 둬도 이미 다른 주문에 들어간 송장은 넣지 않는다."""
    client = _yoon_client()
    run(client, _yoon_reply())
    client.move(7002, "ACCEPT", "INSTRUCT")
    second = run(client, _yoon_reply())
    assert client.upload_calls == [[(7001, "412300000001")]]
    assert second["skip"] == 1 and "이미 등록된 송장" in second["results"][0]["message"]


def test_rerun_after_delivery_completed_still_blocked(run):
    """옛 주문이 배송완료로 넘어가도 그 송장은 다시 쓰지 않는다."""
    client = FakeCoupang({
        "FINAL_DELIVERY": [_shipment(7101, "윤재주문", "0504-1000-0001", "5Kg (특상)", ADDR_A, invoice="412300000001")],
        "INSTRUCT": [_shipment(7102, "윤재주문", "0504-1000-0002", "5Kg (특상)", ADDR_A)],
    })
    result = run(client, _yoon_reply())
    assert client.upload_calls == []
    assert result["skip"] == 1 and "이미 등록된 송장" in result["results"][0]["message"]


# ── 동명이인·같은 사람 여러 주문·하이픈 전화 ──
def test_namesakes_split_one_to_one_by_phone(run):
    reply = _haedal_reply([   # 회신 순서는 쿠팡 주문 순서와 반대
        ("김민지", "0504-2222-0002", ADDR_B, "꿀고구마 5Kg (특상)", "412300000022"),
        ("김민지", "0504-1111-0001", ADDR_A, "꿀고구마 5Kg (특상)", "412300000011"),
    ])
    client = FakeCoupang({"INSTRUCT": [
        _shipment(8001, "김민지", "0504-1111-0001", "5Kg (특상)", ADDR_A),
        _shipment(8002, "김민지", "0504-2222-0002", "5Kg (특상)", ADDR_B),
    ]})
    result = run(client, reply)
    assert sorted(client.upload_calls[0]) == [(8001, "412300000011"), (8002, "412300000022")]
    assert result["success"] == 2


def test_same_person_two_accept_orders_one_to_one_and_confirmed(run):
    """같은 사람 2건(주문마다 안심번호가 다름) — 전화로 1:1, 둘 다 전화가 맞으니 확인 처리."""
    reply = _haedal_reply([
        ("박지성", "0504-3333-0002", ADDR_A, "꿀고구마 3Kg (중상)", "412300000032"),
        ("박지성", "0504-3333-0001", ADDR_A, "꿀고구마 5Kg (특상)", "412300000031"),
    ])
    client = FakeCoupang({"ACCEPT": [
        _shipment(8101, "박지성", "0504-3333-0001", "5Kg (특상)", ADDR_A),
        _shipment(8102, "박지성", "0504-3333-0002", "3Kg (중상)", ADDR_A),
    ]})
    result = run(client, reply)
    assert client.confirm_calls == [[8101, 8102]]
    assert sorted(client.upload_calls[0]) == [(8101, "412300000031"), (8102, "412300000032")]
    assert result["success"] == 2


def test_same_person_new_order_not_in_reply_is_skipped(run):
    """회신에 1건만 있는데 쿠팡에 같은 사람 주문이 2건 — 전화가 맞는 주문만, 나머지는 skip."""
    reply = _haedal_reply([("박지성", "0504-3333-0001", ADDR_A, "꿀고구마 5Kg (특상)", "412300000031")])
    client = FakeCoupang({"INSTRUCT": [
        _shipment(8103, "박지성", "0504-3333-0009", "5Kg (특상)", ADDR_A),   # 회신에 없는 새 주문(먼저 나옴)
        _shipment(8104, "박지성", "0504-3333-0001", "5Kg (특상)", ADDR_A),
    ]})
    result = run(client, reply)
    assert client.upload_calls == [[(8104, "412300000031")]]
    assert (result["success"], result["skip"]) == (1, 1)


def test_hyphen_phone_matches_digits_and_accept_is_confirmed(run):
    reply = _haedal_reply([("최하이픈", "0504-4444-0001", ADDR_A, "꿀고구마 5Kg (특상)", "412300000041")])
    client = FakeCoupang({"ACCEPT": [_shipment(8201, "최하이픈", "050444440001", "5Kg (특상)", ADDR_A)]})
    result = run(client, reply)
    assert client.confirm_calls == [[8201]]
    assert client.upload_calls == [[(8201, "412300000041")]]
    assert result["success"] == 1 and result["results"][0]["message"] == "운송장 등록 완료"


def test_instruct_name_and_option_without_reply_phone_still_registered(run):
    """회신에 전화가 없으면 이름+옵션으로 짝짓는다(상품준비중)."""
    reply = _haedal_reply([("이옵션", "", ADDR_B, "꿀고구마 5Kg (특상)", "412300000051")])
    client = FakeCoupang({"INSTRUCT": [_shipment(8301, "이옵션", "0504-5555-0001", "5Kg (특상)", ADDR_A)]})
    result = run(client, reply)
    assert client.upload_calls == [[(8301, "412300000051")]]
    assert result["success"] == 1


def test_instruct_other_phone_same_address_not_registered(run):
    """전화(주문별 안심번호)가 양쪽 다 있는데 다르면 이름·옵션·주소가 같아도 다른 주문 — 같은 사람의 다른 주문이나
    토스 주문 송장일 수 있다(2026-11-16 재검토: 주소가 같으면 넣던 조건 삭제)."""
    reply = _haedal_reply([("이주소", "0504-5555-0009", ADDR_A, "꿀고구마 5Kg (특상)", "412300000052")])
    client = FakeCoupang({"INSTRUCT": [_shipment(8302, "이주소", "0504-5555-0002", "5Kg (특상)", ADDR_A)]})
    result = run(client, reply)
    assert client.upload_calls == []
    assert (result["success"], result["skip"]) == (0, 1)
    assert "전화 불일치" in result["results"][0]["message"]


def test_toss_line_of_same_person_not_put_on_new_coupang_order(run):
    """같은 사람이 토스·쿠팡에서 같은 옵션을 같은 주소로 주문 — 회신엔 토스 줄(010)과 쿠팡 X 줄만 있고 쿠팡 새 주문 Y는
    아직 회신에 없다. 토스 송장이 Y에 들어가면 안 된다."""
    reply = _haedal_reply([
        ("최혼합", "010-1234-5678", ADDR_A, "꿀고구마 5Kg (특상)", "412377770001"),    # 토스 주문
        ("최혼합", "0504-6000-0001", ADDR_A, "꿀고구마 5Kg (특상)", "412377770002"),   # 쿠팡 X
    ])
    client = FakeCoupang({"INSTRUCT": [
        _shipment(6901, "최혼합", "0504-6000-0001", "5Kg (특상)", ADDR_A),   # X
        _shipment(6902, "최혼합", "0504-6000-0002", "5Kg (특상)", ADDR_A),   # Y (아직 해달에 안 보낸 새 주문)
    ]})
    result = run(client, reply)
    assert client.upload_calls == [[(6901, "412377770002")]]
    assert (result["success"], result["skip"]) == (1, 1)
    skipped = next(r for r in result["results"] if r["status"] == "skip")
    assert skipped["order_id"] == "69020" and "전화 불일치" in skipped["message"]


# ── ② 재실행 — 한 주문 송장이 여러 개(묶음·분할 회신)면 쿠팡엔 하나만 올라가 나머지는 쿠팡 어디에도 없다 ──
PASO_PHONE = "0502-4663-2343"


def _paso_reply() -> bytes:
    return _haedal_reply([
        ("파소향", PASO_PHONE, ADDR_A, "꿀고구마 3Kg (중상)", "412311110001"),
        ("파소향", PASO_PHONE, ADDR_A, "꿀고구마 5Kg (특상)", "412311110002"),
    ])


@pytest.mark.parametrize("new_phone", ["0502-4663-9999", ""])
def test_rerun_bundle_cheaper_box_tracking_not_put_on_new_order(run, new_phone):
    """묶음(3kg+5kg)은 더 비싼 5kg 송장만 올라간다. 같은 회신을 다시 올려도 남은 3kg 송장이 같은 사람의 새 상품준비중
    주문(같은 옵션·주소)에 들어가면 안 된다 — 새 주문 안심번호가 달라도, 비어 있어도(출고된 주문의 안심번호 몫)."""
    client = FakeCoupang({"INSTRUCT": [
        _bundle(6001, "파소향", PASO_PHONE, ADDR_A, [("3Kg (중상)", 13800), ("5Kg (특상)", 21900)]),
    ]})
    first = run(client, _paso_reply())
    assert client.upload_calls == [[(6001, "412311110002"), (6001, "412311110002")]]
    assert first["success"] == 2

    client.shipments["INSTRUCT"].append(_shipment(6002, "파소향", new_phone, "3Kg (중상)", ADDR_A))
    second = run(client, _paso_reply())
    assert len(client.upload_calls) == 1                                   # 재실행 땐 아무것도 안 올림
    assert (second["success"], second["skip"]) == (0, 1)
    assert "출고된 다른 주문 몫" in second["results"][0]["message"]
    assert second["results"][0]["tracking"] == "412311110001"


def test_rerun_split_reply_extra_box_tracking_not_put_on_new_order(run):
    """해달이 한 주문을 박스 두 개·송장 두 줄로 회신 — 1차엔 첫 송장만 올라가고, 재실행 때 남은 송장이 같은 사람의
    새 주문에 들어가면 안 된다."""
    reply = _haedal_reply([
        ("서분할", "0504-8100-0001", ADDR_A, "꿀고구마 5Kg (특상)", "412381000001"),
        ("서분할", "0504-8100-0001", ADDR_A, "꿀고구마 5Kg (특상)", "412381000002"),
    ])
    client = FakeCoupang({"INSTRUCT": [_shipment(7701, "서분할", "0504-8100-0001", "5Kg (특상)", ADDR_A)]})
    first = run(client, reply)
    assert first["success"] == 1 and client.upload_calls == [[(7701, "412381000001")]]

    client.shipments["INSTRUCT"].append(_shipment(7702, "서분할", "0504-8100-0002", "5Kg (특상)", ADDR_A))
    second = run(client, reply)
    assert client.upload_calls == [[(7701, "412381000001")]]
    assert (second["success"], second["skip"]) == (0, 1)
    assert "출고된 다른 주문 몫" in second["results"][0]["message"]


def test_same_order_other_box_still_registered_when_first_box_shipped(run):
    """정상: 같은 주문(같은 안심번호)의 다른 묶음은 앞 묶음이 이미 출고돼 있어도 등록한다 — 막는 건 다른 주문뿐."""
    reply = _haedal_reply([
        ("나눔배송", "0504-8200-0001", ADDR_A, "꿀고구마 3Kg (중상)", "412382000001"),
        ("나눔배송", "0504-8200-0001", ADDR_A, "꿀고구마 5Kg (특상)", "412382000002"),
    ])
    shipped = _shipment(7801, "나눔배송", "0504-8200-0001", "3Kg (중상)", ADDR_A, invoice="412382000001")
    pending = _shipment(7802, "나눔배송", "0504-8200-0001", "5Kg (특상)", ADDR_A)
    pending["orderId"] = shipped["orderId"]
    client = FakeCoupang({"DEPARTURE": [shipped], "INSTRUCT": [pending]})
    result = run(client, reply)
    assert client.upload_calls == [[(7802, "412382000002")]]
    assert result["success"] == 1


def test_repeat_customer_new_tracking_registered_despite_old_shipped_order(run):
    """정상: 재구매 고객 — 지난 주문(다른 안심번호·옛 송장)이 배송 중이어도 새 회신 송장은 새 주문에 등록한다."""
    reply = _haedal_reply([("재구매", "0504-8300-0002", ADDR_A, "꿀고구마 5Kg (특상)", "412383000002")])
    client = FakeCoupang({
        "DELIVERING": [_shipment(7901, "재구매", "0504-8300-0001", "5Kg (특상)", ADDR_A, invoice="412383000001")],
        "INSTRUCT": [_shipment(7902, "재구매", "0504-8300-0002", "5Kg (특상)", ADDR_A)],
    })
    result = run(client, reply)
    assert client.upload_calls == [[(7902, "412383000002")]]
    assert result["success"] == 1 and result["results"][0]["message"] == "운송장 등록 완료"


def test_instruct_without_coupang_phone_still_registered_by_name_and_option(run):
    """정상: 쿠팡 쪽 전화가 비어 있으면(안심번호 없음) 종전처럼 이름+옵션으로 등록 — 출고된 다른 사람 주문과 무관."""
    reply = _haedal_reply([("빈전화", "0504-8400-0001", ADDR_A, "꿀고구마 5Kg (특상)", "412384000001")])
    client = FakeCoupang({
        "DEPARTURE": [_shipment(8601, "다른사람", "0504-8400-0009", "5Kg (특상)", ADDR_B, invoice="412384000009")],
        "INSTRUCT": [_shipment(8602, "빈전화", "", "5Kg (특상)", ADDR_A)],
    })
    result = run(client, reply)
    assert client.upload_calls == [[(8602, "412384000001")]]
    assert result["success"] == 1


def test_tracking_already_on_same_box_is_not_blocked(run):
    """송장이 들어간 게 같은 묶음이면(상태가 아직 안 바뀐 채 재실행) 막지 않는다 — 다른 주문일 때만 skip."""
    reply = _yoon_reply()
    client = FakeCoupang({"INSTRUCT": [
        _shipment(7201, "윤재주문", "0504-1000-0001", "5Kg (특상)", ADDR_A, invoice="4123-0000-0001"),
    ]})
    result = run(client, reply)
    assert client.upload_calls == [[(7201, "412300000001")]]
    assert result["success"] == 1


def test_only_shipped_orders_means_no_pending_orders(run):
    """출고 상태 주문은 짝짓기 대상이 아니다 — 결제완료·상품준비중이 없으면 종전처럼 '주문 없음'."""
    client = FakeCoupang({"DEPARTURE": [
        _shipment(7301, "윤재주문", "0504-1000-0001", "5Kg (특상)", ADDR_A, invoice="412300000001"),
    ]})
    with pytest.raises(ValueError, match="결제완료 또는 상품준비중"):
        run(client, _yoon_reply())
    assert client.confirm_calls == [] and client.upload_calls == []


def test_phone_match_with_changed_receiver_name_still_registered(run):
    """CS로 수취인 이름이 바뀌어도 전화(안심번호)가 같으면 종전처럼 등록 + 표시."""
    reply = _haedal_reply([("홍길동", "0504-6666-0001", ADDR_A, "꿀고구마 5Kg (특상)", "412300000061")])
    client = FakeCoupang({"ACCEPT": [_shipment(8401, "홍길순", "0504-6666-0001", "5Kg (특상)", ADDR_A)]})
    result = run(client, reply)
    assert client.confirm_calls == [[8401]] and client.upload_calls == [[(8401, "412300000061")]]
    assert "전화번호 매칭" in result["results"][0]["message"]


# ── 외부 API 실패: 확인·업로드 실패는 그 건만 실패로, 주문 목록 조회 실패는 중단 ──
class _ConfirmFails(FakeCoupang):
    def __init__(self, shipments, mode: str):
        super().__init__(shipments)
        self.mode = mode

    async def confirm_orders(self, shipment_box_ids):
        self.confirm_calls.append(sorted(shipment_box_ids))
        if self.mode == "raise":
            raise RuntimeError("쿠팡 API 재시도 소진")
        return None


@pytest.mark.parametrize("mode", ["none", "raise"])
def test_confirm_failure_counts_that_order_as_fail_and_continues(run, mode):
    reply = _haedal_reply([
        ("정결제", "0504-7777-0001", ADDR_A, "꿀고구마 5Kg (특상)", "412300000071"),
        ("한준비", "0504-7777-0002", ADDR_B, "꿀고구마 3Kg (중상)", "412300000072"),
    ])
    client = _ConfirmFails({
        "ACCEPT": [_shipment(8501, "정결제", "0504-7777-0001", "5Kg (특상)", ADDR_A)],
        "INSTRUCT": [_shipment(8502, "한준비", "0504-7777-0002", "3Kg (중상)", ADDR_B)],
    }, mode)
    result = run(client, reply)
    assert client.confirm_calls == [[8501]]
    assert client.upload_calls == [[(8502, "412300000072")]]            # 확인 못 한 결제완료 주문엔 송장을 안 올림
    assert (result["success"], result["fail"], result["skip"]) == (1, 1, 0)
    failed = next(r for r in result["results"] if r["status"] == "fail")
    assert failed["name"] == "정결제" and "확인 처리 실패" in failed["message"]


class _UploadFails(FakeCoupang):
    def __init__(self, shipments, mode: str):
        super().__init__(shipments)
        self.mode = mode

    async def upload_invoices(self, dtos):
        self.upload_calls.append([(dto["shipmentBoxId"], dto["invoiceNumber"]) for dto in dtos])
        if self.mode == "raise":
            raise RuntimeError("쿠팡 API 재시도 소진")
        return None


@pytest.mark.parametrize("mode", ["none", "raise"])
def test_upload_failure_is_counted_as_fail_not_success(run, mode):
    reply = _haedal_reply([("한준비", "0504-7777-0002", ADDR_B, "꿀고구마 3Kg (중상)", "412300000072")])
    client = _UploadFails({"INSTRUCT": [_shipment(8502, "한준비", "0504-7777-0002", "3Kg (중상)", ADDR_B)]}, mode)
    result = run(client, reply)
    assert (result["success"], result["fail"]) == (0, 1)
    assert result["results"][0]["status"] == "fail"


@pytest.mark.parametrize("status, mode", [("INSTRUCT", "none"), ("ACCEPT", "raise"), ("DEPARTURE", "none")])
def test_order_list_failure_aborts_without_touching_orders(run, status, mode):
    """주문 목록 조회가 응답 없음/예외면 빈 목록으로 보지 않고 중단 — 송장 중복 확인용 조회도 같다."""
    reply = _haedal_reply([("한준비", "0504-7777-0002", ADDR_B, "꿀고구마 3Kg (중상)", "412300000072")])
    client = FakeCoupang({"INSTRUCT": [_shipment(8502, "한준비", "0504-7777-0002", "3Kg (중상)", ADDR_B)]})
    if mode == "none":
        client.list_none_status = status
    else:
        client.list_raise_status = status
    with pytest.raises(RuntimeError, match="조회 실패|재시도 소진"):
        run(client, reply)
    assert client.confirm_calls == [] and client.upload_calls == []


# ── 2) 제주다팜 송장입력(tracking_input) 6~8단계 ──
HWANGGEUM = "[재구매1위] 제주 황금향 정품 하우스 고당도 평균16brix 산지직송 맛보장"


def _delivery(rows: list[tuple[str, str, str, str, str]]) -> bytes:
    """DeliveryList: (AA 이름, AB 전화, AD 주소, K 상품명, L 옵션) — D 택배사·E 운송장은 빈칸."""
    wb = Workbook()
    ws = wb.active
    ws.append(["헤더"] * 31)
    for name, phone, address, product, option in rows:
        row = [""] * 31
        row[26], row[27], row[29], row[10], row[11] = name, phone, address, product, option
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _jeju_reply(rows: list[tuple[str, str, str, str, str, str]]) -> bytes:
    """제주다팜 회신: (E 상품명, K 수령인, M 연락처, O 주소, Q 택배사, R 운송장)."""
    wb = Workbook()
    ws = wb.active
    ws.append(["헤더"] * 18)
    for product, name, phone, address, courier, tracking in rows:
        row = [""] * 18
        row[4], row[10], row[12], row[14], row[16], row[17] = product, name, phone, address, courier, tracking
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _de(output: bytes) -> tuple:
    ws = load_workbook(BytesIO(output)).active
    return ws.cell(2, 4).value, ws.cell(2, 5).value


def test_tracking_input_toss_namesake_other_phone_and_address_not_filled():
    """부산 김철수(쿠팡) 줄에 서울 토스 고객 김철수 송장이 들어가던 재현 — 전화·주소가 다 다르면 넣지 않고 사유."""
    delivery = _delivery([("김철수", "0507-1111-2222", ADDR_B, HWANGGEUM, "1박스 2kg (소)")])
    reply = _jeju_reply([("하우스 정품 황금향 소과(100g~150g) 2kg", "김철수", "0508-9999-8888", ADDR_A, "", "T-TOSS-KIM")])
    out, _fn, stats = tracking_input.process(reply, delivery)
    assert _de(out) == (None, None)
    assert stats["filled"] == 0 and stats["skipped"] == 1, stats
    assert "김철수(전화·주소 불일치" in stats["skipped_names"], stats


def test_tracking_input_no_option_info_other_phone_and_address_not_filled():
    """회신에 상품 정보가 없는 양식(8단계)도 같다 — 전화·주소가 다르면 이름만으로 넣지 않는다."""
    delivery = _delivery([("박영수", "0504-1212-3434", "인천광역시 남동구 1", "콜라비", "3kg 1박스")])
    reply = _jeju_reply([("", "박영수", "010-9898-7676", "울산광역시 남구 2", "롯데택배", "255200000099")])
    out, _fn, stats = tracking_input.process(reply, delivery)
    assert _de(out) == (None, None)
    assert stats["filled"] == 0 and "박영수(전화·주소 불일치" in stats["skipped_names"], stats


def test_tracking_input_other_phone_but_same_address_still_filled():
    """전화가 달라도 주소(공백 무시)가 같으면 같은 사람 — 넣는다."""
    delivery = _delivery([("김철수", "0507-1111-2222", ADDR_B, HWANGGEUM, "1박스 2kg (소)")])
    reply = _jeju_reply([("하우스 정품 황금향 소과(100g~150g) 2kg", "김철수", "0508-9999-8888",
                          ADDR_B.replace(" ", "  ") + " ", "", "T-SAME-ADDR")])
    out, _fn, stats = tracking_input.process(reply, delivery)
    assert _de(out) == ("한진택배", "T-SAME-ADDR")
    assert stats["filled"] == 1


def test_tracking_input_reply_without_phone_still_filled():
    """회신 전화가 비어 있으면 종전처럼 이름+옵션으로 넣는다."""
    delivery = _delivery([("김철수", "0507-1111-2222", ADDR_B, HWANGGEUM, "1박스 2kg (소)")])
    reply = _jeju_reply([("하우스 정품 황금향 소과(100g~150g) 2kg", "김철수", "", ADDR_A, "", "T-NO-PHONE")])
    out, _fn, stats = tracking_input.process(reply, delivery)
    assert _de(out) == ("한진택배", "T-NO-PHONE")
    assert stats["filled"] == 1


def test_tracking_input_same_person_same_phone_still_filled():
    """정상 케이스: 같은 사람·같은 전화(하이픈 유무 차이)면 주소 표기가 달라도 넣는다."""
    delivery = _delivery([("김철수", "050711112222", "부산 해운대구 센텀중앙로 2", HWANGGEUM, "1박스 2kg (소)")])
    reply = _jeju_reply([("하우스 정품 황금향 소과(100g~150g) 2kg", "김철수", "0507-1111-2222", ADDR_B, "한진택배", "T-OK")])
    out, _fn, stats = tracking_input.process(reply, delivery)
    assert _de(out) == ("한진택배", "T-OK")
    assert stats["filled"] == 1
