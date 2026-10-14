"""Inventory backup manager — port of data/repository/InventoryBackupManager.kt.

Exports the database to a ``.xlsx`` workbook (sheets: meta, storage_locations,
components, inventory_items) with embedded component preview images, and
imports such a workbook back, restoring all rows. The Android version uses
Apache POI; here we use ``openpyxl``.
"""
from __future__ import annotations

import io
import logging
import re
import time
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.drawing.image import Image as XlImage
from openpyxl.utils import get_column_letter

from ..db.dao import (
    ComponentDao,
    InventoryItemDao,
    InventoryTransactionDao,
    StorageLocationDao,
)
from ..db.entities import ComponentEntity, InventoryItemEntity, StorageLocationEntity
from ..domain.models import (
    LocationCategoryProfile,
    calculate_dominant_location_category_profile,
)
from ..domain.sort_mode import StorageLocationSortMode

_LOG = logging.getLogger(__name__)
_SCHEMA_VERSION = 1
_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


class InventoryBackupManager:
    def __init__(
        self,
        storage_location_dao: StorageLocationDao,
        component_dao: ComponentDao,
        inventory_item_dao: InventoryItemDao,
        inventory_transaction_dao: InventoryTransactionDao,
        image_store,
        enrichment_manager,
        user_preferences_repository,
        app_version_name: str = "desktop-1.0.0",
        app_version_code: str = "1",
        run_in_transaction=None,  # callable(context_manager_fn) -> runs the fn in a txn
    ) -> None:
        self._storage_location_dao = storage_location_dao
        self._component_dao = component_dao
        self._inventory_item_dao = inventory_item_dao
        self._inventory_transaction_dao = inventory_transaction_dao
        self._image_store = image_store
        self._enrichment_manager = enrichment_manager
        self._prefs = user_preferences_repository
        self._app_version_name = app_version_name
        self._app_version_code = app_version_code
        self._run_in_transaction = run_in_transaction

    # ---- export ----
    def export_to_path(
        self,
        path: str | Path,
        on_components_progress=None,
    ) -> str | None:
        try:
            workbook = Workbook()
            # remove default sheet
            default = workbook.active
            workbook.remove(default)

            storage_locations = self._storage_location_dao.get_all()
            recent_location_colors = self._prefs.preferences.recent_location_colors
            inventory_items = self._inventory_item_dao.get_all()

            # Only export storage locations that have inventory items
            location_ids_with_items = {item.location_id for item in inventory_items}
            storage_locations = [sl for sl in storage_locations if sl.id in location_ids_with_items]

            # Filter inventory items to only those in exported locations
            exported_location_ids = {sl.id for sl in storage_locations}
            filtered_items = [item for item in inventory_items if item.location_id in exported_location_ids]

            referenced_component_ids = {item.component_id for item in filtered_items}
            components = [
                c for c in self._component_dao.get_all() if c.id in referenced_component_ids
            ]

            meta_sheet = workbook.create_sheet("meta")
            self._write_row(meta_sheet, 1, ["schemaVersion", str(_SCHEMA_VERSION)])
            self._write_row(meta_sheet, 2, ["appVersionName", self._app_version_name])
            self._write_row(meta_sheet, 3, ["appVersionCode", self._app_version_code])
            self._write_row(
                meta_sheet, 4, ["recentLocationColors", "\n".join(recent_location_colors)]
            )

            sl_sheet = workbook.create_sheet("storage_locations")
            self._write_row(
                sl_sheet,
                1,
                ["id", "code", "displayName", "colorHex", "sortMode", "remark", "createdAt"],
            )
            for index, item in enumerate(storage_locations):
                self._write_row(
                    sl_sheet,
                    index + 2,
                    [
                        item.id,
                        item.code,
                        item.display_name,
                        item.color_hex,
                        item.sort_mode,
                        item.remark,
                        item.created_at,
                    ],
                )

            comp_sheet = workbook.create_sheet("components")
            image_column_index = 11
            total = len(components)
            if total > 0 and on_components_progress:
                on_components_progress(0, total)
            self._write_row(
                comp_sheet,
                1,
                [
                    "id", "partNumber", "name", "brand", "packageName", "category",
                    "specJson", "description", "sourceUrl", "updatedAt", "imagePreview",
                ],
            )
            for index, item in enumerate(components):
                row_index = index + 2
                export_item = self._enrich_component_for_export_if_needed(item)
                self._write_row(
                    comp_sheet,
                    row_index,
                    [
                        export_item.id,
                        export_item.part_number,
                        export_item.name,
                        export_item.brand,
                        export_item.package_name,
                        export_item.category,
                        export_item.spec_json,
                        export_item.description,
                        export_item.source_url,
                        export_item.updated_at,
                        None,
                    ],
                )
                self._insert_component_preview_image(
                    comp_sheet, row_index, image_column_index, export_item.image_local_path
                )
                if on_components_progress:
                    on_components_progress(index + 1, total)
            comp_sheet.column_dimensions[get_column_letter(image_column_index)].width = 18

            inv_sheet = workbook.create_sheet("inventory_items")
            self._write_row(
                inv_sheet,
                1,
                ["id", "componentId", "locationId", "quantity", "lastInboundAt", "updatedAt"],
            )
            for index, item in enumerate(filtered_items):
                self._write_row(
                    inv_sheet,
                    index + 2,
                    [
                        item.id,
                        item.component_id,
                        item.location_id,
                        item.quantity,
                        item.last_inbound_at,
                        item.updated_at,
                    ],
                )

            workbook.save(str(path))
            return None
        except Exception as error:  # noqa: BLE001
            _LOG.exception("export failed")
            return str(error) or "backup export failed"

    # ---- import ----
    def import_from_path(
        self,
        path: str | Path,
        on_components_progress=None,
    ) -> str | None:
        try:
            workbook = load_workbook(filename=str(path), data_only=True)
        except Exception as error:  # noqa: BLE001
            _LOG.exception("import open failed")
            return str(error) or "backup import open failed"

        try:
            meta_sheet = workbook["meta"] if "meta" in workbook.sheetnames else None
            if meta_sheet is None:
                return "unsupported backup version"
            schema_version = self._cell_as_string(meta_sheet.cell(row=1, column=2))
            try:
                if int(schema_version) != _SCHEMA_VERSION:
                    return "unsupported backup version"
            except (ValueError, TypeError):
                return "unsupported backup version"

            storage_locations = self._read_storage_locations(
                workbook["storage_locations"] if "storage_locations" in workbook.sheetnames else None
            )
            recent_location_colors = self._read_recent_location_colors(meta_sheet)
            comp_sheet = workbook["components"] if "components" in workbook.sheetnames else None
            preview_images = self._extract_preview_images(comp_sheet)
            imported_components = self._read_components(
                comp_sheet, preview_images, on_components_progress
            )
            components = [row.entity for row in imported_components]
            inventory_items = self._read_inventory_items(
                workbook["inventory_items"] if "inventory_items" in workbook.sheetnames else None
            )

            self._run_restore_transaction(storage_locations, components, inventory_items)

            if recent_location_colors:
                self._prefs.set_recent_location_colors(recent_location_colors)

            self._enrichment_manager.schedule_all(
                [row.entity.part_number for row in imported_components if row.requires_enrichment]
            )
            return None
        except Exception as error:  # noqa: BLE001
            _LOG.exception("import failed")
            return str(error) or "backup import failed"

    def _run_restore_transaction(
        self,
        storage_locations: list[StorageLocationEntity],
        components: list[ComponentEntity],
        inventory_items: list[InventoryItemEntity],
    ) -> None:
        if self._run_in_transaction is not None:
            self._run_in_transaction(
                lambda: self._do_restore(storage_locations, components, inventory_items)
            )
        else:
            self._do_restore(storage_locations, components, inventory_items)
        self._refresh_all_location_category_profiles_internal()

    def _do_restore(
        self,
        storage_locations: list[StorageLocationEntity],
        components: list[ComponentEntity],
        inventory_items: list[InventoryItemEntity],
    ) -> None:
        self._inventory_transaction_dao.delete_all()
        self._inventory_item_dao.delete_all()
        self._component_dao.delete_all()
        self._storage_location_dao.delete_all()
        if storage_locations:
            self._storage_location_dao.insert_all(storage_locations)
        if components:
            self._component_dao.insert_all(components)
        if inventory_items:
            self._inventory_item_dao.insert_all(inventory_items)

    def _refresh_all_location_category_profiles_internal(self) -> None:
        profiles_by_location: dict[int, list[LocationCategoryProfile]] = {}
        for projection in self._inventory_item_dao.get_all_location_category_profiles():
            profile = LocationCategoryProfile(
                location_id=projection.location_id,
                category=projection.category,
                package_name=projection.package_name,
                quantity=projection.quantity,
            )
            profiles_by_location.setdefault(profile.location_id, []).append(profile)
        now = int(time.time() * 1000)
        for location in self._storage_location_dao.get_all():
            profile = calculate_dominant_location_category_profile(
                profiles_by_location.get(location.id, [])
            )
            self._storage_location_dao.update_inbound_profile(
                location_id=location.id,
                category=profile.category,
                package_name=profile.package_name,
                updated_at=now,
            )

    # ---- helpers ----
    @staticmethod
    def _write_row(sheet, row_index: int, values: list) -> None:
        for col_index, value in enumerate(values, start=1):
            cell = sheet.cell(row=row_index, column=col_index)
            if value is None:
                cell.value = None
            elif isinstance(value, bool):
                cell.value = value
            elif isinstance(value, (int, float)):
                cell.value = float(value)
            else:
                cell.value = str(value)

    @staticmethod
    def _cell_as_string(cell) -> str:
        if cell is None or cell.value is None:
            return ""
        value = cell.value
        if isinstance(value, bool):
            return str(value)
        if isinstance(value, (int, float)):
            if isinstance(value, float) and value.is_integer():
                return str(int(value))
            return str(value)
        return str(value).strip()

    def _read_storage_locations(self, sheet) -> list[StorageLocationEntity]:
        if sheet is None:
            return []
        result: list[StorageLocationEntity] = []
        for row in self._data_rows(sheet):
            result.append(
                StorageLocationEntity(
                    id=row.long("id"),
                    code=row.string("code") or "",
                    display_name=row.string_or_null("displayName"),
                    color_hex=row.string_or_null("colorHex"),
                    sort_mode=row.string_or_null("sortMode") or StorageLocationSortMode.NONE,
                    remark=row.string_or_null("remark"),
                    created_at=row.long("createdAt"),
                )
            )
        return result

    def _read_recent_location_colors(self, meta_sheet) -> list[str]:
        if meta_sheet is None:
            return []
        for row_idx in range(1, meta_sheet.max_row + 1):
            key = self._cell_as_string(meta_sheet.cell(row=row_idx, column=1))
            if key == "recentLocationColors":
                raw = self._cell_as_string(meta_sheet.cell(row=row_idx, column=2))
                if not raw:
                    return []
                seen: set[str] = set()
                result: list[str] = []
                for part in raw.split("\n"):
                    part = part.strip()
                    if _COLOR_RE.match(part):
                        upper = part.upper()
                        if upper not in seen:
                            seen.add(upper)
                            result.append(upper)
                    if len(result) >= 5:
                        break
                return result
        return []

    def _read_components(self, sheet, preview_images, on_components_progress):
        from dataclasses import dataclass

        @dataclass
        class ImportedComponentRow:
            entity: ComponentEntity
            requires_enrichment: bool

        if sheet is None:
            return []
        rows = self._data_rows(sheet)
        total = len(rows)
        if total > 0 and on_components_progress:
            on_components_progress(0, total)
        result: list[ImportedComponentRow] = []
        for index, row in enumerate(rows):
            part_number = (row.string("partNumber") or "").strip().upper()
            image_local_path = None
            preview = preview_images.get(row.row_index)
            if preview and part_number:
                image_local_path = self._image_store.persist_image_bytes(
                    part_number=part_number,
                    source_name=preview.get("source_name"),
                    bytes_data=preview["bytes"],
                )
            result.append(
                ImportedComponentRow(
                    entity=ComponentEntity(
                        id=row.long("id"),
                        part_number=part_number,
                        mpn=None,
                        name=row.string_or_null("name"),
                        brand=row.string_or_null("brand"),
                        package_name=row.string_or_null("packageName"),
                        category=row.string_or_null("category"),
                        spec_json=row.string_or_null("specJson"),
                        description=row.string_or_null("description"),
                        source_url=row.string_or_null("sourceUrl"),
                        image_local_path=image_local_path,
                        updated_at=row.long("updatedAt"),
                    ),
                    requires_enrichment=False,
                )
            )
            if on_components_progress:
                on_components_progress(index + 1, total)
        return result

    def _read_inventory_items(self, sheet) -> list[InventoryItemEntity]:
        if sheet is None:
            return []
        result: list[InventoryItemEntity] = []
        for row in self._data_rows(sheet):
            result.append(
                InventoryItemEntity(
                    id=row.long("id"),
                    component_id=row.long("componentId"),
                    location_id=row.long("locationId"),
                    quantity=row.int_value("quantity"),
                    last_inbound_at=row.long("lastInboundAt"),
                    updated_at=row.long("updatedAt"),
                )
            )
        return result

    def _data_rows(self, sheet):
        if sheet.max_row <= 1:
            return []
        header_row = sheet[1]
        headers: dict[str, int] = {}
        for cell in header_row:
            name = self._cell_as_string(cell)
            if name:
                headers[name] = cell.column
        result = []
        for row_index in range(2, sheet.max_row + 1):
            row = sheet[row_index]
            if self._is_empty_row(row):
                continue
            result.append(_ExcelRow(headers, row, row_index))
        return result

    @staticmethod
    def _is_empty_row(row) -> bool:
        for cell in row:
            if cell.value is not None and str(cell.value).strip():
                return False
        return True

    def _enrich_component_for_export_if_needed(self, component: ComponentEntity) -> ComponentEntity:
        if not self._requires_export_enrichment(component):
            return component
        self._enrichment_manager.enrich_now([component.part_number])
        refreshed = self._component_dao.find_by_id(component.id)
        return refreshed or component

    @staticmethod
    def _requires_export_enrichment(component: ComponentEntity) -> bool:
        has_image = False
        if component.image_local_path:
            try:
                p = Path(component.image_local_path)
                has_image = p.exists() and p.stat().st_size > 0
            except OSError:
                has_image = False
        part = (component.part_number or "").strip().upper()
        return bool(part) and not part.startswith("C0") and not has_image

    def _insert_component_preview_image(
        self, sheet, row_index: int, image_column_index: int, image_local_path: str | None
    ) -> None:
        if not image_local_path:
            return
        try:
            image_file = Path(image_local_path)
            if not image_file.exists() or image_file.stat().st_size == 0:
                return
            img = XlImage(str(image_file))
            img.anchor = f"{get_column_letter(image_column_index)}{row_index}"
            sheet.add_image(img)
        except Exception as error:  # noqa: BLE001
            _LOG.warning("insert preview image failed: %s", error)

    def _extract_preview_images(self, sheet) -> dict[int, dict]:
        """Map row index -> {bytes, source_name} for embedded images in the sheet."""
        if sheet is None:
            return {}
        result: dict[int, dict] = {}
        try:
            for image in getattr(sheet, "_images", []):
                anchor = getattr(image, "anchor", None)
                row_num = None
                if anchor is not None:
                    from_cell = getattr(anchor, "_from", None)
                    if from_cell is not None:
                        row_num = getattr(from_cell, "row", None)
                if row_num is None or row_num <= 0:
                    continue
                data = self._read_image_bytes(image)
                if data:
                    result[row_num + 1] = {  # openpyxl rows are 0-indexed in anchor
                        "bytes": data,
                        "source_name": "preview.jpg",
                    }
        except Exception as error:  # noqa: BLE001
            _LOG.warning("extract preview images failed: %s", error)
        return result

    @staticmethod
    def _read_image_bytes(image) -> bytes | None:
        try:
            ref = getattr(image, "ref", None)
            if ref and Path(str(ref)).exists():
                return Path(str(ref)).read_bytes()
        except OSError:
            pass
        try:
            data_method = getattr(image, "_data", None)
            if callable(data_method):
                return data_method()
        except Exception:  # noqa: BLE001
            pass
        try:
            img_obj = getattr(image, "image", None)  # PIL Image
            if img_obj is not None:
                buf = io.BytesIO()
                img_obj.save(buf, format="PNG")
                return buf.getvalue()
        except Exception:  # noqa: BLE001
            pass
        return None


class _ExcelRow:
    def __init__(self, headers: dict[str, int], row, row_index: int) -> None:
        self._headers = headers
        self._row = row
        self.row_index = row_index

    def _cell_value(self, header: str) -> str | None:
        col_index = self._headers.get(header)
        if col_index is None:
            return None
        cell = self._row[col_index - 1] if col_index - 1 < len(self._row) else None
        if cell is None:
            return None
        return InventoryBackupManager._cell_as_string(cell)

    def string(self, header: str) -> str | None:
        return self._cell_value(header)

    def string_or_null(self, header: str) -> str | None:
        value = self._cell_value(header)
        if not value or not value.strip():
            return None
        return value

    def long(self, header: str) -> int:
        value = self._cell_value(header)
        if value is None:
            return 0
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return 0

    def int_value(self, header: str) -> int:
        return self.long(header)
