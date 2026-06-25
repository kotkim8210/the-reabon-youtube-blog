"""Toss Shopping (토스쇼핑) OpenAPI async client."""

import asyncio
import logging
import re
import time

import httpx

from app import config

logger = logging.getLogger(__name__)

OAUTH_URL = config.TOSS_OAUTH_TOKEN_URL
BASE_URL = config.TOSS_API_BASE_URL
MAX_RETRIES = 3
RATE_LIMIT = asyncio.Semaphore(10)
PARTNER_NAME = "알제이시스템즈"
INVALID_IP_RE = re.compile(r"INVALID_IP|허가되지 않은 IP", re.IGNORECASE)


class TossApiError(RuntimeError):
    """Toss Shopping API error that should be shown clearly to the operator."""

    def __init__(self, message: str, *, error_code: str = "", reason: str = "", raw: object | None = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.reason = reason
        self.raw = raw

    @property
    def is_invalid_ip(self) -> bool:
        haystack = f"{self.error_code} {self.reason} {self.message}"
        return bool(INVALID_IP_RE.search(haystack))


class TossClient:
    """Async client for Toss Shopping OpenAPI with OAuth2 auth."""

    def __init__(self):
        self.access_key = config.TOSS_ACCESS_KEY
        self.secret_key = config.TOSS_SECRET_KEY
        self._client: httpx.AsyncClient | None = None
        self._token: str | None = None
        self._token_expires_at: float = 0

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _ensure_token(self):
        """Get or refresh OAuth2 access token."""
        if not self.access_key or not self.secret_key:
            raise ValueError(
                "TOSS_ACCESS_KEY 또는 TOSS_SECRET_KEY가 설정되지 않았습니다. "
                ".env 파일 또는 환경변수를 확인하세요."
            )

        if self._token and time.time() < self._token_expires_at - 60:
            return

        client = await self._get_client()
        resp = await client.post(
            OAUTH_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self.access_key,
                "client_secret": self.secret_key,
                "scope": config.TOSS_OAUTH_SCOPE,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 3600)
        logger.info("Toss OAuth2 token refreshed")

    async def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json_body: dict | None = None,
    ) -> dict | None:
        """Make an authenticated request with rate limiting and retry."""
        async with RATE_LIMIT:
            client = await self._get_client()

            for attempt in range(MAX_RETRIES):
                await self._ensure_token()

                headers = {
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                }

                try:
                    response = await client.request(
                        method=method,
                        url=BASE_URL + path,
                        headers=headers,
                        params=params,
                        json=json_body,
                    )

                    if response.status_code == 401:
                        self._token = None
                        if attempt < MAX_RETRIES - 1:
                            continue
                        response.raise_for_status()

                    if response.status_code == 429:
                        wait = 2 ** attempt
                        logger.warning(f"Toss rate limited, waiting {wait}s")
                        await asyncio.sleep(wait)
                        continue

                    if response.status_code >= 500:
                        wait = 2 ** attempt
                        logger.warning(f"Toss server error {response.status_code}, retrying in {wait}s")
                        await asyncio.sleep(wait)
                        continue

                    if response.status_code == 400:
                        body = response.text
                        logger.error(
                            f"Toss API 400 Bad Request: {method} {path} | "
                            f"body={json_body} | response={body}"
                        )
                        raise httpx.HTTPStatusError(
                            f"400 Bad Request: {body}",
                            request=response.request,
                            response=response,
                        )

                    response.raise_for_status()
                    return response.json()

                except httpx.RequestError as e:
                    logger.error(f"Toss API request error: {e}")
                    if attempt == MAX_RETRIES - 1:
                        raise

            return None

    @staticmethod
    def _raise_if_failed(result: dict | None, fallback_message: str) -> None:
        if not result or result.get("resultType") != "FAIL":
            return
        error_info = result.get("error") or {}
        error_code = str(error_info.get("errorCode") or "INVALID_REQUEST")
        reason = str(error_info.get("reason") or fallback_message)
        raise TossApiError(
            f"{error_code}: {reason}",
            error_code=error_code,
            reason=reason,
            raw=error_info,
        )

    async def get_orders(
        self,
        start_date: str,
        end_date: str,
        status: str | None = "PAID",
        limit: int = 50,
    ) -> list[dict]:
        """Fetch all orders for a date range with pagination.

        Args:
            start_date: yyyy-MM-dd format
            end_date: yyyy-MM-dd format
            status: Order status filter (PAID, PREPARING_PRODUCT, etc.)
            limit: Page size (max 50)

        Returns:
            List of order items.
        """
        all_orders = []
        next_cursor = None

        while True:
            params = {
                "startDate": start_date,
                "endDate": end_date,
                "limit": limit,
            }
            if status:
                params["status"] = status
            if next_cursor:
                params["nextCursor"] = next_cursor

            result = await self._request(
                "GET",
                "/api/v3/shopping-fep/orders/v2",
                params=params,
            )

            if not result:
                break

            # Toss API wraps data in success.results and may return HTTP 200 with resultType=FAIL.
            if result.get("resultType") == "FAIL":
                error_info = result.get("error", {}) or {}
                error_code = str(error_info.get("errorCode") or "TOSS_API_FAIL")
                reason = str(error_info.get("reason") or error_info or "토스 주문 조회 실패")
                logger.error("토스 주문 API 실패: %s", error_info)
                raise TossApiError(
                    f"토스 주문 조회 API 실패: {error_code} - {reason}",
                    error_code=error_code,
                    reason=reason,
                    raw=error_info,
                )

            data = result.get("success") or result
            items = data.get("results", [])
            all_orders.extend(items)

            next_cursor = data.get("nextCursor")
            if not next_cursor:
                break

        return all_orders

    async def confirm_order(self, order_product_id: int) -> dict | None:
        """Move a paid order into PREPARING_PRODUCT before delivery input."""
        result = await self._request(
            "PUT",
            "/api/v3/shopping-fep/orders/products/status",
            json_body={
                "orderProductIds": [order_product_id],
                "status": "PREPARING_PRODUCT",
                "partnerName": PARTNER_NAME,
            },
        )
        self._raise_if_failed(result, "토스 주문 상태 변경 실패")
        return result

    async def register_tracking(
        self,
        order_product_id: int,
        delivery_company: str,
        tracking_number: str,
    ) -> dict | None:
        """Register a tracking number for an order product.

        If the initial attempt fails with 400, try confirming the order first
        and then retry tracking registration.
        """
        tracking_number = re.sub(r"\D", "", str(tracking_number))
        payload = {
            "orderProductId": order_product_id,
            "deliveryCompany": delivery_company,
            "trackingNumber": tracking_number,
            "partnerName": PARTNER_NAME,
        }

        def _needs_confirm(exc: Exception) -> bool:
            """결제완료(PAID) 상태라 운송장 등록이 거부된 경우인지 판별.

            - 실제 HTTP 400
            - HTTP 200 envelope FAIL → TossApiError (예: "주문상품의 상태가
              '상품준비중' 혹은 '배송중'이 아닙니다") ← 이 케이스가 실제로 발생함
            """
            if isinstance(exc, httpx.HTTPStatusError):
                return exc.response.status_code == 400
            if isinstance(exc, TossApiError):
                text = f"{getattr(exc, 'reason', '') or ''} {exc}"
                return ("상품준비중" in text) or ("배송중" in text) or ("상태" in text)
            return False

        try:
            result = await self._request(
                "PUT",
                "/api/v3/shopping-fep/orders/products/delivery",
                json_body=payload,
            )
            self._raise_if_failed(result, "토스 운송장 등록 실패")
            return result
        except (httpx.HTTPStatusError, TossApiError) as e:
            if not _needs_confirm(e):
                raise
            logger.info(
                f"운송장 등록 실패(상품준비중 아님) → 주문 확인(PREPARING_PRODUCT) 후 재시도 "
                f"(orderProductId={order_product_id}) | 원본 에러: {e}"
            )
            try:
                confirm_resp = await self.confirm_order(order_product_id)
                logger.info(f"주문 확인 완료 (orderProductId={order_product_id}): {confirm_resp}")
            except Exception as confirm_err:
                logger.warning(
                    f"주문 확인 실패 (무시하고 재시도): {confirm_err}"
                )
            # 확인 처리 후 API 반영 대기
            await asyncio.sleep(1.5)
            result = await self._request(
                "PUT",
                "/api/v3/shopping-fep/orders/products/delivery",
                json_body=payload,
            )
            self._raise_if_failed(result, "토스 운송장 등록 실패")
            return result

    async def get_claims(
        self,
        start_date: str,
        end_date: str,
        claim_type: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Fetch claims (cancel/exchange/return) for a date range.

        Args:
            start_date: yyyy-MM-dd
            end_date: yyyy-MM-dd
            claim_type: CANCEL, EXCHANGE, RETURN or None for all
            limit: Page size (max 50)
        """
        all_claims = []
        next_cursor = None

        while True:
            params = {
                "startDate": start_date,
                "endDate": end_date,
                "limit": limit,
            }
            if claim_type:
                params["claimType"] = claim_type
            if next_cursor:
                params["nextCursor"] = next_cursor

            result = await self._request(
                "GET",
                "/api/v3/shopping-fep/orders/claims",
                params=params,
            )

            if not result:
                break

            if result.get("resultType") == "FAIL":
                error_info = result.get("error", {})
                logger.error(f"토스 클레임 API 실패: {error_info}")
                raise RuntimeError(f"토스 클레임 조회 API 실패: {error_info}")

            data = result.get("success") or result
            items = data.get("results", [])
            all_claims.extend(items)

            next_cursor = data.get("nextCursor")
            if not next_cursor:
                break

        return all_claims

    async def approve_cancel(self, order_product_id: int) -> dict | None:
        """Approve a cancellation request."""
        return await self._request(
            "PUT",
            f"/api/v3/shopping-fep/orders/products/{order_product_id}/cancel/approve",
        )

    async def reject_cancel(
        self, order_product_id: int, reason: str
    ) -> dict | None:
        """Reject a cancellation request."""
        return await self._request(
            "PUT",
            f"/api/v3/shopping-fep/orders/products/{order_product_id}/cancel/reject",
            json_body={"rejectReason": reason},
        )

    async def approve_exchange(self, order_product_id: int) -> dict | None:
        """Approve an exchange request."""
        return await self._request(
            "PUT",
            f"/api/v3/shopping-fep/orders/products/{order_product_id}/exchange/approve",
        )

    async def reject_exchange(
        self, order_product_id: int, reason: str
    ) -> dict | None:
        """Reject an exchange request."""
        return await self._request(
            "PUT",
            f"/api/v3/shopping-fep/orders/products/{order_product_id}/exchange/reject",
            json_body={"rejectReason": reason},
        )

    async def approve_return(self, order_product_id: int) -> dict | None:
        """Approve a return request."""
        return await self._request(
            "PUT",
            f"/api/v3/shopping-fep/orders/products/{order_product_id}/return/approve",
        )

    async def reject_return(
        self, order_product_id: int, reason: str
    ) -> dict | None:
        """Reject a return request."""
        return await self._request(
            "PUT",
            f"/api/v3/shopping-fep/orders/products/{order_product_id}/return/reject",
            json_body={"rejectReason": reason},
        )

    async def test_connection(self) -> dict:
        """Test API connection by attempting token acquisition."""
        try:
            await self._ensure_token()
            return {"status": "ok", "message": "토스 API 연결 성공"}
        except ValueError as e:
            return {"status": "error", "message": str(e)}
        except Exception as e:
            return {"status": "error", "message": f"토스 API 연결 실패: {e}"}


toss_client = TossClient()
