"""토스 클레임 조회(get_claims) — 실측 응답(2026-07) 기반 정규화 테스트."""

import asyncio

from app.toss.client import TossClient

# 2026-07-17 실제 API 응답에서 채취한 아이템 구조 (개인정보 마스킹됨)
REAL_ITEM = {
    "id": 7734693,
    "requestedDt": "2026-07-11T20:51:39",
    "type": "CANCEL",
    "status": "COMPLETED",
    "requestReason": "구매 의사 취소",
    "requestDetailReason": "",
    "requestImages": [],
    "requestDeliveryPenaltyCharger": "USER",
    "refundOneWayDeliveryFee": 3000,
    "roundTripDeliveryFee": 6000,
    "returnAddress": "인천광역시 연수구 인천타워대로**********",
    "order": {
        "id": 245839985,
        "orderProductId": 271684435,
        "ordererName": "김*진",
        "ordererPhoneNumber": "*******4396",
        "receiverName": "김*진",
        "receiverPhoneNumber": "*******4396",
        "deliveryCompany": None,
        "shippingTrackingNumber": None,
        "address": "충청북도 청주시 흥덕구************",
        "price": 14800,
        "createdDt": "2026-07-10T10:12:40",
    },
    "product": {
        "id": 758060605,
        "name": "고당도 햇 백도 딱딱이복숭아 국내산 산지직송",
        "optionName": "2kg,1박스,중과",
        "quantity": 1,
    },
    "claimDeliveryPaymentAmount": None,
}

RETURN_ITEM = dict(
    REAL_ITEM,
    id=7734694,
    type="RETURN",
    status="REQUESTED",
    requestReason="상품 불량",
    requestDetailReason="박스 파손",
)


def _client_with_pages(pages):
    client = TossClient()
    calls = []

    async def fake_request(method, path, params=None, json_body=None):
        calls.append((method, path, dict(params or {})))
        return pages[min(len(calls) - 1, len(pages) - 1)]

    client._request = fake_request
    client._calls = calls
    return client


def test_get_claims_normalizes_real_shape():
    client = _client_with_pages([
        {"resultType": "SUCCESS",
         "success": {"items": [REAL_ITEM, RETURN_ITEM], "hasNext": False, "nextToken": None}},
    ])
    claims = asyncio.run(client.get_claims("2026-06-18", "2026-07-18"))

    assert len(claims) == 2
    c = claims[0]
    assert c["claimType"] == "CANCEL"
    assert c["claimStatus"] == "COMPLETED"
    assert c["claimReason"] == "구매 의사 취소"
    assert c["orderId"] == 245839985
    assert c["orderProductId"] == 271684435
    assert c["receiverName"] == "김*진"
    assert c["productName"].startswith("고당도 햇 백도")

    # 상세사유가 있으면 합쳐서 표시
    assert claims[1]["claimReason"] == "상품 불량 — 박스 파손"

    # 올바른 경로/파라미터로 호출했는지
    method, path, params = client._calls[0]
    assert path == "/api/v3/shopping-fep/claims"
    assert params == {"startDate": "2026-06-18", "endDate": "2026-07-18"}


def test_get_claims_filters_type_client_side():
    client = _client_with_pages([
        {"resultType": "SUCCESS",
         "success": {"items": [REAL_ITEM, RETURN_ITEM], "hasNext": False, "nextToken": None}},
    ])
    claims = asyncio.run(client.get_claims("2026-06-18", "2026-07-18", claim_type="RETURN"))
    assert len(claims) == 1
    assert claims[0]["claimType"] == "RETURN"
    # type/status 서버 필터는 함께만 가능하므로 요청에는 type을 싣지 않는다
    assert "type" not in client._calls[0][2]
    assert "claimType" not in client._calls[0][2]


def test_get_claims_paginates_with_next_token():
    client = _client_with_pages([
        {"resultType": "SUCCESS",
         "success": {"items": [REAL_ITEM], "hasNext": True, "nextToken": "tok-2"}},
        {"resultType": "SUCCESS",
         "success": {"items": [RETURN_ITEM], "hasNext": False, "nextToken": None}},
    ])
    claims = asyncio.run(client.get_claims("2026-06-18", "2026-07-18"))
    assert len(claims) == 2
    assert client._calls[1][2].get("nextToken") == "tok-2"


def test_get_claims_raises_clean_error_on_fail_envelope():
    import pytest
    from app.toss.client import TossApiError

    client = _client_with_pages([
        {"resultType": "FAIL", "success": None,
         "error": {"errorType": 0, "errorCode": "500", "reason": "Internal Server Error"}},
    ])
    with pytest.raises(TossApiError):
        asyncio.run(client.get_claims("2026-06-18", "2026-07-18"))
