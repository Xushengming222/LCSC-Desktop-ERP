"""LCSC catalog remote data source — port of data/remote/LcscCatalogRemoteDataSource.kt.

Fetches product data from ``so.szlcsc.com`` by parsing the Next.js
``__NEXT_DATA__`` JSON embedded in the HTML. When the server responds with
HTTP 203 (anti-bot challenge), the page embeds JavaScript variables that are
combined and RC4-encrypted into a verification cookie, then the request is
retried with that cookie.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

_LOG = logging.getLogger(__name__)

_VERIFICATION_KEY = "tg09It3*9h"
_VERIFICATION_TOKENS = ("_xvasu", "_xvtsc", "_xvpfs", "_xvpts")
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
_DEFAULT_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Referer": "https://so.szlcsc.com/",
}

_VAR_RE_CACHE: dict[str, re.Pattern[str]] = {}


@dataclass
class _FetchHtmlResult:
    status_code: int
    html: str


def opt_string_or_none(obj: dict | None, name: str) -> str | None:
    if not isinstance(obj, dict):
        return None
    value = obj.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    value = value.strip()
    if not value or value == "null":
        return None
    return value


def opt_int_or_none(obj: dict | None, name: str) -> int | None:
    if not isinstance(obj, dict) or name not in obj or obj[name] is None:
        return None
    try:
        return int(obj[name])
    except (ValueError, TypeError):
        return None


def opt_double_or_none(obj: dict | None, name: str) -> float | None:
    if not isinstance(obj, dict) or name not in obj or obj[name] is None:
        return None
    try:
        return float(obj[name])
    except (ValueError, TypeError):
        return None


def _rc4(key: str, value: str) -> bytes:
    """Standard RC4 keystream cipher matching the Kotlin implementation."""
    key_bytes = key.encode("utf-8")
    value_bytes = value.encode("utf-8")
    state = list(range(256))
    index_b = 0
    key_len = len(key_bytes)
    for index_a in range(256):
        index_b = (index_b + state[index_a] + (key_bytes[index_a % key_len] & 0xFF)) % 256
        state[index_a], state[index_b] = state[index_b], state[index_a]

    index_a = 0
    index_b = 0
    output = bytearray(len(value_bytes))
    for index in range(len(value_bytes)):
        index_a = (index_a + 1) % 256
        index_b = (index_b + state[index_a]) % 256
        state[index_a], state[index_b] = state[index_b], state[index_a]
        key_stream = state[(state[index_a] + state[index_b]) % 256]
        output[index] = (value_bytes[index] ^ key_stream) & 0xFF
    return bytes(output)


def _extract_js_variable(html: str, name: str) -> str | None:
    pattern = _VAR_RE_CACHE.get(name)
    if pattern is None:
        pattern = re.compile(r"var\s+" + re.escape(name) + r"\s*=\s*(.+?);")
        _VAR_RE_CACHE[name] = pattern
    match = pattern.search(html)
    if not match:
        return None
    value = match.group(1).strip()
    if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
        value = value[1:-1]
    return value


def _looks_like_verification_page(html: str) -> bool:
    return any(token in html for token in _VERIFICATION_TOKENS)


def _build_verification_cookie(html: str) -> str | None:
    xvasu = _extract_js_variable(html, "_xvasu")
    xvpts = _extract_js_variable(html, "_xvpts")
    xvpfs = _extract_js_variable(html, "_xvpfs")
    if xvasu is None or xvpts is None or xvpfs is None:
        return None
    cookie_name = f"{xvpfs}{xvasu}"
    encrypted = _rc4(_VERIFICATION_KEY, f"{xvpts}:{xvasu}")
    cookie_value = base64.b64encode(encrypted).decode("ascii")
    return f"{cookie_name}={cookie_value}"


class LcscCatalogRemoteDataSource:
    def __init__(self, timeout: float = 15.0) -> None:
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(_DEFAULT_HEADERS)

    def search_products(self, keyword: str) -> list[dict]:
        url = "https://so.szlcsc.com/global.html"
        root = self._fetch_next_data(url, params={"k": keyword})
        if root is None:
            return []
        product_list = (
            root.get("props", {})
            .get("pageProps", {})
            .get("soData", {})
            .get("searchResult", {})
            .get("productRecordList", [])
        )
        if not isinstance(product_list, list):
            return []
        return [p for p in product_list if isinstance(p, dict)]

    def search_matched_product(self, part_number: str) -> dict | None:
        normalized = part_number.strip().upper()
        for record in self.search_products(part_number):
            product_code = opt_string_or_none(
                record.get("productVO"), "productCode"
            )
            if product_code is None:
                continue
            if product_code.strip().upper() == normalized:
                return record
        return None

    # ---- internal ----
    def _fetch_next_data(self, url: str, params: dict | None = None) -> dict | None:
        try:
            result = self._fetch_html(url, params=params)
            if result is None:
                return None
            if result.status_code == 203 and _looks_like_verification_page(result.html):
                cookie = _build_verification_cookie(result.html)
                if cookie is None:
                    _LOG.warning("verification cookie parse failed: url=%s", url)
                    return None
                result = self._fetch_html(url, params=params, cookie=cookie)
                if result is None:
                    return None
            return self._parse_next_data(url, result.status_code, result.html)
        except requests.RequestException as error:
            _LOG.warning("network failed: url=%s err=%s", url, error)
            return None
        except (ValueError, json.JSONDecodeError) as error:
            _LOG.warning("parse failed: url=%s err=%s", url, error)
            return None

    def _fetch_html(
        self, url: str, params: dict | None = None, cookie: str | None = None
    ) -> _FetchHtmlResult | None:
        headers = dict(_DEFAULT_HEADERS)
        if cookie:
            headers["Cookie"] = cookie
        response = self._session.get(
            url, params=params, headers=headers, timeout=self._timeout
        )
        if response.status_code >= 400:
            _LOG.warning("fetchHtml failed: code=%s url=%s", response.status_code, url)
            return None
        html = response.text or ""
        if not html.strip():
            _LOG.warning("fetchHtml empty body: code=%s url=%s", response.status_code, url)
            return None
        return _FetchHtmlResult(status_code=response.status_code, html=html)

    @staticmethod
    def _parse_next_data(url: str, status_code: int, html: str) -> dict | None:
        soup = BeautifulSoup(html, "html.parser")
        script = soup.select_one("script#__NEXT_DATA__")
        if script is None or not script.string:
            _LOG.warning(
                "missing __NEXT_DATA__: code=%s url=%s preview=%s",
                status_code, url, html[:200],
            )
            return None
        try:
            root = json.loads(script.string)
        except json.JSONDecodeError:
            _LOG.warning("invalid __NEXT_DATA__ json: code=%s url=%s", status_code, url)
            return None
        product_count = len(
            root.get("props", {})
            .get("pageProps", {})
            .get("soData", {})
            .get("searchResult", {})
            .get("productRecordList", [])
            or []
        )
        _LOG.debug("fetchNextData success: code=%s url=%s products=%s", status_code, url, product_count)
        return root
