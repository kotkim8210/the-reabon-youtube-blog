"""Coupang Open API async HTTP client."""

import asyncio
import json
import logging
import re

import httpx

from app.coupang.auth import generate_hmac_signature
from app import config

logger = logging.getLogger(__name__)

BASE_URL = "https://api-gateway.coupang.com"
MAX_RETRIES = 3
RATE_LIMIT = asyncio.Semaphore(10)
BLOCKED_IP_RE = re.compile(r"ip address\s+([0-9.]+)\s+is not allowed", re.IGNORECASE)


class CoupangApiError(RuntimeError):
    """Coupang returned an authenticated API error that should be shown clearly."""

    def __init__(
        self,
        status_code: int,
        message: str,
        response_text: str = "",
        blocked_ip: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.response_text = response_text
        self.blocked_ip = blocked_ip


def _parse_coupang_error(response: httpx.Response) -> tuple[str, str | None]:
    """Extract Coupang's useful error text and blocked egress IP when present."""
    text = response.text or ""
    message = text[:500] or f"HTTP {response.status_code}"
    try:
        data = response.json()
        if isinstance(data, dict):
            message = str(data.get("message") or data.get("error") or message)
    except (json.JSONDecodeError, ValueError):
        pass

    blocked_ip = None
    match = BLOCKED_IP_RE.search(message) or BLOCKED_IP_RE.search(text)
    if match:
        blocked_ip = match.group(1)
    return message, blocked_ip


def _build_query_string(params: dict | None) -> str:
    """Build sorted query string without URL encoding."""
    if not params:
        return ""
    sorted_params = sorted(params.items())
    return "&".join(f"{k}={v}" for k, v in sorted_params)


class CoupangClient:
    """Async client for Coupang Open API with rate limiting and retry."""

    def __init__(
        self,
        vendor_id: str = "",
        access_key: str = "",
        secret_key: str = "",
        account_label: str = "default",
    ):
        self.vendor_id = vendor_id
        self.access_key = access_key
        self.secret_key = secret_key
        self.account_label = account_label
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        query_params: dict | None = None,
        json_body: dict | None = None,
    ) -> dict | list | None:
        """Make an authenticated request with rate limiting and retry."""
        async with RATE_LIMIT:
            client = await self._get_client()

            # Build query string for signature
            query_string = _build_query_string(query_params)

            # Signature message: dt + method + path + query (no ? separator)
            sign_path = path + query_string

            # Actual URL uses ? separator
            full_url = BASE_URL + path
            if query_string:
                full_url += "?" + query_string

            for attempt in range(MAX_RETRIES):
                auth_header = generate_hmac_signature(
                    method=method,
                    path=sign_path,
                    secret_key=self.secret_key,
                    access_key=self.access_key,
                )

                headers = {
                    "Authorization": auth_header,
                    "Content-Type": "application/json;charset=UTF-8",
                }

                try:
                    response = await client.request(
                        method=method,
                        url=full_url,
                        headers=headers,
                        json=json_body,
                    )

                    if response.status_code == 429:
                        wait = 2 ** attempt
                        logger.warning(f"Rate limited, waiting {wait}s (attempt {attempt + 1})")
                        await asyncio.sleep(wait)
                        continue

                    if response.status_code >= 500:
                        wait = 2 ** attempt
                        logger.warning(f"Server error {response.status_code}, retrying in {wait}s")
                        await asyncio.sleep(wait)
                        continue

                    if response.status_code in (401, 403):
                        message, blocked_ip = _parse_coupang_error(response)
                        logger.error(
                            "Coupang API %s: %s",
                            response.status_code,
                            response.text,
                        )
                        raise CoupangApiError(
                            response.status_code,
                            message,
                            response.text,
                            blocked_ip,
                        )

                    response.raise_for_status()

                    if response.status_code == 204:
                        return None
                    return response.json()

                except httpx.HTTPStatusError:
                    if attempt == MAX_RETRIES - 1:
                        raise
                except httpx.RequestError as e:
                    logger.error(f"Coupang API request error: {e}")
                    if attempt == MAX_RETRIES - 1:
                        raise

            return None

    # --- Product APIs ---

    async def get_seller_products(self, next_token: str | None = None, max_per_page: int = 50) -> dict:
        path = "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"
        params = {"vendorId": self.vendor_id, "maxPerPage": str(max_per_page)}
        if next_token:
            params["nextToken"] = next_token
        return await self._request("GET", path, query_params=params)

    async def get_product_detail(self, seller_product_id: int) -> dict:
        path = f"/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{seller_product_id}"
        return await self._request("GET", path)

    # --- Order APIs ---

    async def get_order_sheets(
        self,
        created_at_from: str | None = None,
        created_at_to: str | None = None,
        order_status: str | None = None,
        max_per_page: int = 50,
        next_token: str | None = None,
    ) -> dict:
        path = f"/v2/providers/openapi/apis/api/v4/vendors/{self.vendor_id}/ordersheets"
        params = {"maxPerPage": str(max_per_page)}
        if created_at_from:
            params["createdAtFrom"] = created_at_from
        if created_at_to:
            params["createdAtTo"] = created_at_to
        if order_status:
            params["status"] = order_status
        if next_token:
            params["nextToken"] = next_token
        return await self._request("GET", path, query_params=params)

    # --- Return APIs ---

    async def get_return_requests(
        self,
        created_at_from: str | None = None,
        created_at_to: str | None = None,
    ) -> dict:
        path = f"/v2/providers/openapi/apis/api/v4/vendors/{self.vendor_id}/returnRequests"
        params = {}
        if created_at_from:
            params["createdAtFrom"] = created_at_from
        if created_at_to:
            params["createdAtTo"] = created_at_to
        return await self._request("GET", path, query_params=params)

    # --- Online Inquiry (고객 문의) APIs ---

    async def get_call_center_inquiries(
        self,
        inquiry_start_at: str,
        inquiry_end_at: str,
        partner_counseling_status: str = "NO_ANSWER",
        page_num: int = 1,
        page_size: int = 30,
    ) -> dict:
        """고객센터 문의 조회 (v5). 상태: NO_ANSWER(답변필요)/TRANSFER(확인필요)."""
        path = (
            f"/v2/providers/openapi/apis/api/v5/vendors/{self.vendor_id}"
            "/callCenterInquiries"
        )
        params = {
            "vendorId": self.vendor_id,
            "partnerCounselingStatus": partner_counseling_status,
            "inquiryStartAt": inquiry_start_at,
            "inquiryEndAt": inquiry_end_at,
            "pageNum": str(max(1, page_num)),
            "pageSize": str(max(1, min(page_size, 30))),
        }
        return await self._request("GET", path, query_params=params)

    async def get_online_inquiries(
        self,
        inquiry_start_at: str,
        inquiry_end_at: str,
        answered_type: str = "NOANSWER",
        page_num: int = 1,
        page_size: int = 50,
    ) -> dict:
        """온라인 문의 조회. 날짜는 yyyy-MM-dd, 조회 구간은 최대 7일."""
        path = f"/v2/providers/openapi/apis/api/v4/vendors/{self.vendor_id}/onlineInquiries"
        params = {
            "vendorId": self.vendor_id,
            "answeredType": answered_type,
            "inquiryStartAt": inquiry_start_at,
            "inquiryEndAt": inquiry_end_at,
            "pageNum": str(page_num),
            "pageSize": str(page_size),
        }
        return await self._request("GET", path, query_params=params)

    async def reply_online_inquiry(
        self,
        inquiry_id: int,
        content: str,
        reply_by: str,
    ) -> dict | None:
        """온라인 문의에 답변 등록. reply_by는 쿠팡 WING 로그인 ID."""
        path = (
            f"/v2/providers/openapi/apis/api/v4/vendors/{self.vendor_id}"
            f"/onlineInquiries/{inquiry_id}/replies"
        )
        body = {
            "content": content,
            "vendorId": self.vendor_id,
            "replyBy": reply_by,
        }
        return await self._request("POST", path, json_body=body)

    # --- Order Confirmation ---

    async def confirm_orders(
        self,
        shipment_box_ids: list[int],
    ) -> dict:
        """Confirm orders (결제완료 → 상품준비중).

        Args:
            shipment_box_ids: List of shipmentBoxId to confirm.
        """
        path = (
            f"/v2/providers/openapi/apis/api/v4/vendors/{self.vendor_id}"
            f"/ordersheets/acknowledgement"
        )
        body = {
            "vendorId": self.vendor_id,
            "shipmentBoxIds": shipment_box_ids,
        }
        return await self._request("PUT", path, json_body=body)

    # --- Shipping APIs ---

    async def upload_invoices(
        self,
        invoice_dtos: list[dict],
    ) -> dict:
        """Register tracking numbers for shipments (송장업로드).

        Args:
            invoice_dtos: List of dicts with keys:
                shipmentBoxId, orderId, vendorItemId,
                deliveryCompanyCode, invoiceNumber
        """
        path = (
            f"/v2/providers/openapi/apis/api/v4/vendors/{self.vendor_id}"
            f"/orders/invoices"
        )
        body = {
            "vendorId": self.vendor_id,
            "orderSheetInvoiceApplyDtos": [
                {
                    "shipmentBoxId": dto["shipmentBoxId"],
                    "orderId": dto["orderId"],
                    "vendorItemId": dto["vendorItemId"],
                    "deliveryCompanyCode": dto["deliveryCompanyCode"],
                    "invoiceNumber": dto["invoiceNumber"],
                    "splitShipping": False,
                    "preSplitShipped": False,
                    "estimatedShippingDate": "",
                }
                for dto in invoice_dtos
            ],
        }
        return await self._request("POST", path, json_body=body)

    # --- Price Update ---

    async def update_product_price(
        self,
        seller_product_id: int,
        vendor_item_id: int,
        new_price: int,
    ) -> dict:
        path = "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"
        body = {
            "sellerProductId": seller_product_id,
            "items": [{"vendorItemId": vendor_item_id, "salePrice": new_price}],
        }
        return await self._request("PUT", path, json_body=body)


# Singleton instances
coupang_client = CoupangClient(
    config.COUPANG_VENDOR_ID,
    config.COUPANG_ACCESS_KEY,
    config.COUPANG_SECRET_KEY,
    account_label="default",
)
coupang_goguma_client = CoupangClient(
    config.COUPANG_GOGUMA_VENDOR_ID,
    config.COUPANG_GOGUMA_ACCESS_KEY,
    config.COUPANG_GOGUMA_SECRET_KEY,
    account_label="goguma",
)
coupang_produce_client = CoupangClient(
    config.COUPANG_PRODUCE_VENDOR_ID,
    config.COUPANG_PRODUCE_ACCESS_KEY,
    config.COUPANG_PRODUCE_SECRET_KEY,
    account_label="produce",
)
