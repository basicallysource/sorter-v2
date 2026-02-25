import base64
import hashlib
import hmac
import secrets
import time
from urllib.parse import quote

import requests

BRICKLINK_BASE_URL = "https://api.bricklink.com/api/store/v1"
REQUEST_TIMEOUT_SECONDS = 20


class BricklinkRateLimitError(Exception):
    retry_after_seconds: float | None

    def __init__(self, message: str, retry_after_seconds: float | None = None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class BricklinkApiError(Exception):
    pass


def _percentEncode(value: str) -> str:
    return quote(str(value), safe="~-._")


def _normalizeParams(params: dict[str, str]) -> str:
    pairs: list[tuple[str, str]] = []
    for key, value in params.items():
        if value is None:
            continue
        pairs.append((_percentEncode(key), _percentEncode(value)))
    pairs.sort(key=lambda item: (item[0], item[1]))
    return "&".join(f"{key}={value}" for key, value in pairs)


class BricklinkClient:
    consumer_key: str
    consumer_secret: str
    token_value: str
    token_secret: str

    def __init__(
        self,
        consumer_key: str,
        consumer_secret: str,
        token_value: str,
        token_secret: str,
    ):
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.token_value = token_value
        self.token_secret = token_secret

    def getItem(self, item_type: str, item_no: str) -> dict:
        item_no_path = quote(str(item_no), safe="")
        return self._requestJson("GET", f"/items/{item_type}/{item_no_path}")

    def getPriceGuide(self, item_type: str, item_no: str, query_params: dict[str, str]) -> dict:
        item_no_path = quote(str(item_no), safe="")
        return self._requestJson("GET", f"/items/{item_type}/{item_no_path}/price", params=query_params)

    def getCategories(self) -> dict:
        return self._requestJson("GET", "/categories")

    def _requestJson(self, method: str, path: str, params: dict[str, str] | None = None) -> dict:
        query_params = {}
        if params:
            for key, value in params.items():
                if value is None:
                    continue
                query_params[key] = str(value)

        url = f"{BRICKLINK_BASE_URL}{path}"
        oauth_params = self._mkOauthParams()
        auth_header = self._mkAuthHeader(method, url, query_params, oauth_params)

        try:
            response = requests.request(
                method,
                url,
                params=query_params or None,
                headers={
                    "Authorization": auth_header,
                    "Accept": "application/json",
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as e:
            raise BricklinkApiError(f"BrickLink request failed: {e}") from e

        retry_after = _parseRetryAfter(response.headers.get("Retry-After"))
        try:
            body = response.json()
        except ValueError:
            body = None

        if response.status_code == 429:
            raise BricklinkRateLimitError("BrickLink rate limited the request", retry_after)

        if response.status_code >= 400:
            detail = _extractErrorMessage(body) or response.text.strip() or response.reason
            raise BricklinkApiError(f"BrickLink HTTP {response.status_code}: {detail}")

        if isinstance(body, dict):
            meta = body.get("meta") or {}
            meta_code = meta.get("code")
            if meta_code == 429:
                raise BricklinkRateLimitError("BrickLink API returned rate-limit response", retry_after)
            if meta_code not in (None, 200):
                detail = meta.get("description") or meta.get("message") or str(meta)
                raise BricklinkApiError(f"BrickLink API error {meta_code}: {detail}")
            return body

        raise BricklinkApiError("BrickLink returned a non-JSON response")

    def _mkOauthParams(self) -> dict[str, str]:
        return {
            "oauth_consumer_key": self.consumer_key,
            "oauth_token": self.token_value,
            "oauth_nonce": secrets.token_hex(16),
            "oauth_timestamp": str(int(time.time())),
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_version": "1.0",
        }

    def _mkAuthHeader(
        self,
        method: str,
        url: str,
        query_params: dict[str, str],
        oauth_params: dict[str, str],
    ) -> str:
        signing_params = {}
        signing_params.update(query_params)
        signing_params.update(oauth_params)
        normalized_params = _normalizeParams(signing_params)
        base_string = "&".join([
            method.upper(),
            _percentEncode(url),
            _percentEncode(normalized_params),
        ])
        signing_key = "&".join([
            _percentEncode(self.consumer_secret),
            _percentEncode(self.token_secret),
        ])
        digest = hmac.new(
            signing_key.encode("utf-8"),
            base_string.encode("utf-8"),
            hashlib.sha1,
        ).digest()
        signature = base64.b64encode(digest).decode("utf-8")

        header_params = dict(oauth_params)
        header_params["oauth_signature"] = signature
        header_bits = ['realm=""']
        for key in sorted(header_params.keys()):
            header_bits.append(f'{_percentEncode(key)}="{_percentEncode(header_params[key])}"')
        return "OAuth " + ", ".join(header_bits)


def _extractErrorMessage(body: dict | None) -> str | None:
    if not isinstance(body, dict):
        return None
    meta = body.get("meta")
    if isinstance(meta, dict):
        msg = meta.get("description") or meta.get("message")
        if msg:
            return str(msg)
    message = body.get("message")
    if message:
        return str(message)
    return None


def _parseRetryAfter(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None
