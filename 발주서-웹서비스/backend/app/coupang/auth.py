"""Coupang Open API HMAC-SHA256 authentication.

Signature format (official):
  message = datetime + method + path + querystring (no ? between path and query)
  signature = HMAC-SHA256(secret_key, message)
"""

import hashlib
import hmac
import datetime


def generate_hmac_signature(
    method: str,
    path: str,
    secret_key: str,
    access_key: str,
) -> str:
    """Generate HMAC-SHA256 Authorization header value.

    Args:
        method: HTTP method (GET, POST, PUT, DELETE)
        path: API path WITHOUT query string (e.g., /v2/providers/.../products)
        secret_key: Coupang API secret key
        access_key: Coupang API access key

    Returns:
        Authorization header string
    """
    dt = datetime.datetime.now(datetime.UTC).strftime("%y%m%dT%H%M%SZ")

    # String to sign: datetime + method + path
    # (query string is appended separately by the caller)
    message = dt + method + path

    signature = hmac.new(
        secret_key.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return f"CEA algorithm=HmacSHA256, access-key={access_key}, signed-date={dt}, signature={signature}"
