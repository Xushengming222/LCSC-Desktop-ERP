"""LCSC catalog repository — port of data/repository/LcscCatalogRepositoryImpl.kt.

Converts raw product-record JSON from the remote data source into the
``ComponentDetail`` domain model. The two name strategies (exact part-number
lookup vs. search-result listing) are preserved.
"""
from __future__ import annotations

import logging
import re
from enum import Enum

from bs4 import BeautifulSoup

from ..domain.models import ComponentDetail
from .remote_data_source import (
    LcscCatalogRemoteDataSource,
    opt_double_or_none,
    opt_int_or_none,
    opt_string_or_none,
)

_LOG = logging.getLogger(__name__)
_WS_RE = re.compile(r"\s+")


_PACKAGE_PARAMETER_KEYS = {
    "封装",
    "封装规格",
    "商品封装",
    "安装类型",
    "Package",
    "Package / Case",
    "Case",
    "Footprint",
}


class _NameStrategy(Enum):
    ExactPartNumber = "ExactPartNumber"
    SearchResult = "SearchResult"


class LcscCatalogRepositoryImpl:
    def __init__(self, remote_data_source: LcscCatalogRemoteDataSource) -> None:
        self._remote = remote_data_source

    def lookup_by_part_number(self, part_number: str) -> ComponentDetail | None:
        search_record = self._remote.search_matched_product(part_number)
        if search_record is None:
            return None
        product = search_record.get("productVO")
        if not isinstance(product, dict):
            return None
        detail = self._build_component_detail(
            search_record, product, _NameStrategy.ExactPartNumber
        )
        return detail

    def search_by_keyword(self, keyword: str) -> list[ComponentDetail]:
        results: list[ComponentDetail] = []
        for search_record in self._remote.search_products(keyword):
            product = search_record.get("productVO")
            if not isinstance(product, dict):
                continue
            results.append(
                self._build_component_detail(
                    search_record, product, _NameStrategy.SearchResult
                )
            )
        return results

    # ---- parsing ----
    def _build_component_detail(
        self,
        search_record: dict,
        product: dict,
        name_strategy: _NameStrategy,
    ) -> ComponentDetail:
        search_params = self._extract_search_params(search_record)
        datasheet_url = self._extract_datasheet_url(product)

        product_id = opt_string_or_none(product, "productId")
        product_url = f"https://item.szlcsc.com/{product_id}.html" if product_id else None

        price_list = product.get("productPriceList")
        first_price = None
        if isinstance(price_list, list) and price_list:
            first_price = opt_double_or_none(price_list[0], "productPrice")

        category = (
            _sanitize_search_text(opt_string_or_none(search_record, "lightCatalogName"))
            or _sanitize_search_text(opt_string_or_none(product, "productType"))
        )

        light_product_model = _sanitize_search_text(opt_string_or_none(search_record, "lightProductModel"))
        product_model = _sanitize_search_text(opt_string_or_none(product, "productModel"))
        light_product_name = _sanitize_search_text(opt_string_or_none(search_record, "lightProductName"))
        product_name = _sanitize_search_text(opt_string_or_none(product, "productName"))

        # Both branches use identical logic in the Kotlin source — preserved here.
        normalized_name = light_product_model or product_model
        if normalized_name is None:
            normalized_name = _normalize_display_name(
                raw_name=light_product_name or product_name,
                fallback_name=category,
                extracted_specs=list(search_params.values()),
            )

        return ComponentDetail(
            part_number=str(product.get("productCode", "")),
            mpn=product_model,
            name=normalized_name,
            brand=(
                _sanitize_search_text(opt_string_or_none(search_record, "lightBrandName"))
                or _sanitize_search_text(opt_string_or_none(product, "productGradePlateName"))
            ),
            package_name=(
                _sanitize_search_text(opt_string_or_none(search_record, "lightStandard"))
                or _sanitize_search_text(opt_string_or_none(product, "encapsulationModel"))
                or _extract_package_name_from_search_params(search_params)
            ),
            category=category,
            description=(
                _sanitize_search_text(opt_string_or_none(product, "remark"))
                or _sanitize_search_text(opt_string_or_none(search_record, "lightProductIntro"))
            ),
            stock_quantity=(
                opt_int_or_none(product, "stockNumber")
                if opt_int_or_none(product, "stockNumber") is not None
                else opt_int_or_none(product, "validStockNumber")
            ),
            price=first_price,
            product_url=product_url,
            datasheet_url=datasheet_url,
            image_local_path=None,
            image_url=opt_string_or_none(product, "breviaryImageUrl"),
            specifications=search_params,
        )

    @staticmethod
    def _extract_search_params(search_record: dict) -> dict[str, str]:
        param_json = search_record.get("paramLinkedMap")
        if not isinstance(param_json, dict):
            return {}
        result: dict[str, str] = {}
        for key, raw_value in param_json.items():
            normalized_key = _sanitize_search_text(str(key) if key is not None else None)
            normalized_value = _sanitize_search_text(
                raw_value if isinstance(raw_value, str) else (str(raw_value) if raw_value is not None else None)
            )
            if normalized_key and normalized_value:
                result[normalized_key] = normalized_value
        return result

    @staticmethod
    def _extract_datasheet_url(product: dict) -> str | None:
        file_groups = product.get("fileTypeVOList")
        if not isinstance(file_groups, list):
            return None
        for file_group in file_groups:
            if not isinstance(file_group, dict):
                continue
            details = file_group.get("detailVOList")
            if not isinstance(details, list) or not details:
                continue
            file_path = opt_string_or_none(details[0], "fileUrl")
            if file_path:
                return f"https://atta.szlcsc.com{file_path}"
        return None


def _normalize_display_name(
    raw_name: str | None,
    fallback_name: str | None,
    extracted_specs: list[str],
) -> str | None:
    base_name = raw_name if raw_name and raw_name.strip() else None
    if base_name is None:
        return fallback_name
    candidate = base_name
    for spec_value in sorted(
        (s for s in extracted_specs if s and s.strip()), key=len, reverse=True
    ):
        candidate = candidate.replace(spec_value, " ")
    candidate = _WS_RE.sub(" ", candidate).strip()
    return candidate or fallback_name or base_name


def _extract_package_name_from_search_params(search_params: dict[str, str]) -> str | None:
    for key, value in search_params.items():
        if key.strip() in _PACKAGE_PARAMETER_KEYS:
            if value and value.strip():
                return value
    normalized_keys = [(k.strip().lower(), v) for k, v in search_params.items()]
    for norm_key, value in normalized_keys:
        for candidate in _PACKAGE_PARAMETER_KEYS:
            if candidate.lower() in norm_key:
                if value and value.strip():
                    return value
    return None


def _sanitize_search_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = BeautifulSoup(value, "html.parser").get_text()
    text = text.replace("\u00a0", " ")
    text = _WS_RE.sub(" ", text).strip()
    return text or None
