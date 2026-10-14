"""Data Access Objects mirroring the Android Room DAOs (core/database/dao).

All methods are synchronous. The repository layer wraps them with Qt Signals
to reproduce the ``Flow``-based observation of the Kotlin implementation.
"""
from __future__ import annotations

import sqlite3
from typing import Iterable

from .entities import (
    ComponentEntity,
    DashboardSummaryProjection,
    ExistingStockLocationProjection,
    InventoryItemEntity,
    InventoryTransactionEntity,
    LocationCategoryProfileProjection,
    LocationInventoryProjection,
    SearchInventoryProjection,
    StorageLocationEntity,
    StorageLocationSummaryProjection,
)

# Map dataclass field -> SQLite column for tables whose columns mix naming
# styles. component_master / inventory_item / inventory_txn already use
# snake_case so they map 1:1.
_STORAGE_LOCATION_COLUMNS = {
    "id": "id",
    "code": "code",
    "display_name": "displayName",
    "color_hex": "colorHex",
    "sort_mode": "sortMode",
    "inbound_category": "inbound_category",
    "inbound_package_name": "inbound_package_name",
    "inbound_profile_updated_at": "inbound_profile_updated_at",
    "remark": "remark",
    "created_at": "createdAt",
}


def _row_to_component(row: sqlite3.Row) -> ComponentEntity:
    return ComponentEntity(
        id=row["id"],
        part_number=row["part_number"],
        mpn=row["mpn"],
        name=row["name"],
        brand=row["brand"],
        package_name=row["package_name"],
        category=row["category"],
        spec_json=row["spec_json"],
        description=row["description"],
        source_url=row["source_url"],
        image_local_path=row["image_local_path"],
        image_url=row["image_url"],
        updated_at=row["updated_at"],
    )


def _row_to_storage_location(row: sqlite3.Row) -> StorageLocationEntity:
    return StorageLocationEntity(
        id=row["id"],
        code=row["code"],
        display_name=row["displayName"],
        color_hex=row["colorHex"],
        sort_mode=row["sortMode"],
        inbound_category=row["inbound_category"],
        inbound_package_name=row["inbound_package_name"],
        inbound_profile_updated_at=row["inbound_profile_updated_at"],
        remark=row["remark"],
        created_at=row["createdAt"],
    )


def _row_to_inventory_item(row: sqlite3.Row) -> InventoryItemEntity:
    return InventoryItemEntity(
        id=row["id"],
        component_id=row["component_id"],
        location_id=row["location_id"],
        quantity=row["quantity"],
        last_inbound_at=row["last_inbound_at"],
        updated_at=row["updated_at"],
    )


def _row_to_transaction(row: sqlite3.Row) -> InventoryTransactionEntity:
    return InventoryTransactionEntity(
        id=row["id"],
        component_id=row["component_id"],
        location_id=row["location_id"],
        txn_type=row["txn_type"],
        quantity_delta=row["quantity_delta"],
        source_type=row["source_type"],
        source_ref=row["source_ref"],
        raw_payload=row["raw_payload"],
        created_at=row["created_at"],
    )


def _storage_location_placeholders(entity: StorageLocationEntity) -> dict[str, object]:
    return {
        "id": entity.id,
        "code": entity.code,
        "displayName": entity.display_name,
        "colorHex": entity.color_hex,
        "sortMode": entity.sort_mode,
        "inbound_category": entity.inbound_category,
        "inbound_package_name": entity.inbound_package_name,
        "inbound_profile_updated_at": entity.inbound_profile_updated_at,
        "remark": entity.remark,
        "createdAt": entity.created_at,
    }


def _build_insert(
    table: str,
    columns: list[str],
    values: dict[str, object],
    *,
    id_value: int,
) -> tuple[str, dict[str, object]]:
    """Build an INSERT OR IGNORE statement.

    When ``id_value`` is 0 the id column is omitted so SQLite AUTOINCREMENT
    assigns a fresh rowid — mirroring Room's ``autoGenerate`` semantics where
    a 0 id means "let the database generate one".
    """
    if id_value == 0:
        cols = [c for c in columns if c != "id"]
        params = {k: v for k, v in values.items() if k != "id"}
    else:
        cols = list(columns)
        params = dict(values)
    col_sql = ", ".join(cols)
    ph_sql = ", ".join(f":{c}" for c in cols)
    sql = f"INSERT OR IGNORE INTO {table} ({col_sql}) VALUES ({ph_sql})"
    return sql, params


def _exec_insert(conn: sqlite3.Connection, sql: str, params: dict[str, object]) -> int:
    """Execute an INSERT OR IGNORE and return the resulting row id.

    Returns 0 when the row was skipped due to a conflict, matching Room's
    ``OnConflictStrategy.IGNORE`` which yields -1 / 0 for skipped inserts.
    ``cur.lastrowid`` alone is insufficient because SQLite still reports the
    last *successful* rowid when an IGNORE skips a row.
    """
    cur = conn.execute(sql, params)
    if cur.rowcount <= 0:
        return 0
    return cur.lastrowid or 0


class ComponentDao:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get_all(self) -> list[ComponentEntity]:
        rows = self._conn.execute(
            "SELECT * FROM component_master ORDER BY id ASC"
        ).fetchall()
        return [_row_to_component(r) for r in rows]

    def insert(self, component: ComponentEntity) -> int:
        values = {
            "id": component.id,
            "part_number": component.part_number,
            "mpn": component.mpn,
            "name": component.name,
            "brand": component.brand,
            "package_name": component.package_name,
            "category": component.category,
            "spec_json": component.spec_json,
            "description": component.description,
            "source_url": component.source_url,
            "image_local_path": component.image_local_path,
            "image_url": component.image_url,
            "updated_at": component.updated_at,
        }
        sql, params = _build_insert(
            "component_master",
            [
                "id", "part_number", "mpn", "name", "brand", "package_name",
                "category", "spec_json", "description", "source_url",
                "image_local_path", "image_url", "updated_at",
            ],
            values,
            id_value=component.id,
        )
        return _exec_insert(self._conn, sql, params)

    def insert_all(self, components: Iterable[ComponentEntity]) -> None:
        for c in components:
            self.insert(c)

    def find_by_id(self, component_id: int) -> ComponentEntity | None:
        row = self._conn.execute(
            "SELECT * FROM component_master WHERE id = ? LIMIT 1", (component_id,)
        ).fetchone()
        return _row_to_component(row) if row else None

    def find_by_part_number(self, part_number: str) -> ComponentEntity | None:
        row = self._conn.execute(
            "SELECT * FROM component_master WHERE part_number = ? LIMIT 1",
            (part_number,),
        ).fetchone()
        return _row_to_component(row) if row else None

    def update(self, component: ComponentEntity) -> None:
        self._conn.execute(
            """
            UPDATE component_master SET
                part_number = :part_number,
                mpn = :mpn,
                name = :name,
                brand = :brand,
                package_name = :package_name,
                category = :category,
                spec_json = :spec_json,
                description = :description,
                source_url = :source_url,
                image_local_path = :image_local_path,
                image_url = :image_url,
                updated_at = :updated_at
            WHERE id = :id
            """,
            {
                "id": component.id,
                "part_number": component.part_number,
                "mpn": component.mpn,
                "name": component.name,
                "brand": component.brand,
                "package_name": component.package_name,
                "category": component.category,
                "spec_json": component.spec_json,
                "description": component.description,
                "source_url": component.source_url,
                "image_local_path": component.image_local_path,
                "image_url": component.image_url,
                "updated_at": component.updated_at,
            },
        )

    def delete_all(self) -> None:
        self._conn.execute("DELETE FROM component_master")


class StorageLocationDao:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get_all(self) -> list[StorageLocationEntity]:
        rows = self._conn.execute(
            "SELECT * FROM storage_location ORDER BY code ASC"
        ).fetchall()
        return [_row_to_storage_location(r) for r in rows]

    def count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM storage_location").fetchone()[0])

    def find_by_code(self, code: str) -> StorageLocationEntity | None:
        row = self._conn.execute(
            "SELECT * FROM storage_location WHERE code = ? LIMIT 1", (code,)
        ).fetchone()
        return _row_to_storage_location(row) if row else None

    def find_by_id(self, location_id: int) -> StorageLocationEntity | None:
        row = self._conn.execute(
            "SELECT * FROM storage_location WHERE id = ? LIMIT 1", (location_id,)
        ).fetchone()
        return _row_to_storage_location(row) if row else None

    def observe_location_summaries(self) -> list[StorageLocationSummaryProjection]:
        rows = self._conn.execute(
            """
            SELECT
                sl.id AS id,
                sl.code AS code,
                sl.displayName AS displayName,
                sl.colorHex AS colorHex,
                sl.sortMode AS sortMode,
                sl.remark AS remark,
                CAST(COUNT(ii.id) AS INTEGER) AS inventoryItemCount,
                CAST(COALESCE(SUM(ii.quantity), 0) AS INTEGER) AS totalQuantity
            FROM storage_location sl
            LEFT JOIN inventory_item ii ON ii.location_id = sl.id
            GROUP BY sl.id
            ORDER BY sl.code ASC
            """
        ).fetchall()
        return [
            StorageLocationSummaryProjection(
                id=r["id"],
                code=r["code"],
                display_name=r["displayName"],
                color_hex=r["colorHex"],
                sort_mode=r["sortMode"],
                remark=r["remark"],
                inventory_item_count=r["inventoryItemCount"],
                total_quantity=r["totalQuantity"],
            )
            for r in rows
        ]

    def insert(self, location: StorageLocationEntity) -> int:
        values = _storage_location_placeholders(location)
        sql, params = _build_insert(
            "storage_location",
            [
                "id", "code", "displayName", "colorHex", "sortMode",
                "inbound_category", "inbound_package_name",
                "inbound_profile_updated_at", "remark", "createdAt",
            ],
            values,
            id_value=location.id,
        )
        return _exec_insert(self._conn, sql, params)

    def insert_all(self, locations: Iterable[StorageLocationEntity]) -> None:
        for loc in locations:
            self.insert(loc)

    def update(self, location: StorageLocationEntity) -> None:
        self._conn.execute(
            """
            UPDATE storage_location SET
                code = :code,
                displayName = :displayName,
                colorHex = :colorHex,
                sortMode = :sortMode,
                inbound_category = :inbound_category,
                inbound_package_name = :inbound_package_name,
                inbound_profile_updated_at = :inbound_profile_updated_at,
                remark = :remark,
                createdAt = :createdAt
            WHERE id = :id
            """,
            _storage_location_placeholders(location),
        )

    def update_inbound_profile(
        self,
        location_id: int,
        category: str | None,
        package_name: str | None,
        updated_at: int,
    ) -> None:
        self._conn.execute(
            """
            UPDATE storage_location
            SET inbound_category = ?,
                inbound_package_name = ?,
                inbound_profile_updated_at = ?
            WHERE id = ?
            """,
            (category, package_name, updated_at, location_id),
        )

    def find_locations_missing_inbound_profile(self) -> list[StorageLocationEntity]:
        rows = self._conn.execute(
            """
            SELECT * FROM storage_location
            WHERE inbound_profile_updated_at = 0
            ORDER BY code ASC
            """
        ).fetchall()
        return [_row_to_storage_location(r) for r in rows]

    def delete_by_id(self, location_id: int) -> None:
        self._conn.execute("DELETE FROM storage_location WHERE id = ?", (location_id,))

    def delete_all(self) -> None:
        self._conn.execute("DELETE FROM storage_location")


class InventoryItemDao:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def count_by_location(self, location_id: int) -> int:
        return int(
            self._conn.execute(
                "SELECT COUNT(*) FROM inventory_item WHERE location_id = ?",
                (location_id,),
            ).fetchone()[0]
        )

    def get_all(self) -> list[InventoryItemEntity]:
        rows = self._conn.execute(
            "SELECT * FROM inventory_item ORDER BY id ASC"
        ).fetchall()
        return [_row_to_inventory_item(r) for r in rows]

    def find_by_id(self, inventory_item_id: int) -> InventoryItemEntity | None:
        row = self._conn.execute(
            "SELECT * FROM inventory_item WHERE id = ? LIMIT 1", (inventory_item_id,)
        ).fetchone()
        return _row_to_inventory_item(row) if row else None

    def find_by_component_and_location(
        self, component_id: int, location_id: int
    ) -> InventoryItemEntity | None:
        row = self._conn.execute(
            """
            SELECT * FROM inventory_item
            WHERE component_id = ? AND location_id = ?
            LIMIT 1
            """,
            (component_id, location_id),
        ).fetchone()
        return _row_to_inventory_item(row) if row else None

    def count_by_component(self, component_id: int) -> int:
        return int(
            self._conn.execute(
                "SELECT COUNT(*) FROM inventory_item WHERE component_id = ?",
                (component_id,),
            ).fetchone()[0]
        )

    def get_location_ids_by_component(self, component_id: int) -> list[int]:
        rows = self._conn.execute(
            "SELECT DISTINCT location_id FROM inventory_item WHERE component_id = ?",
            (component_id,),
        ).fetchall()
        return [int(r[0]) for r in rows]

    def insert(self, item: InventoryItemEntity) -> int:
        values = {
            "id": item.id,
            "component_id": item.component_id,
            "location_id": item.location_id,
            "quantity": item.quantity,
            "last_inbound_at": item.last_inbound_at,
            "updated_at": item.updated_at,
        }
        sql, params = _build_insert(
            "inventory_item",
            ["id", "component_id", "location_id", "quantity", "last_inbound_at", "updated_at"],
            values,
            id_value=item.id,
        )
        return _exec_insert(self._conn, sql, params)

    def insert_all(self, items: Iterable[InventoryItemEntity]) -> None:
        for it in items:
            self.insert(it)

    def update(self, item: InventoryItemEntity) -> None:
        self._conn.execute(
            """
            UPDATE inventory_item SET
                component_id = :component_id,
                location_id = :location_id,
                quantity = :quantity,
                last_inbound_at = :last_inbound_at,
                updated_at = :updated_at
            WHERE id = :id
            """,
            {
                "id": item.id,
                "component_id": item.component_id,
                "location_id": item.location_id,
                "quantity": item.quantity,
                "last_inbound_at": item.last_inbound_at,
                "updated_at": item.updated_at,
            },
        )

    def delete_by_id(self, inventory_item_id: int) -> None:
        self._conn.execute("DELETE FROM inventory_item WHERE id = ?", (inventory_item_id,))

    def delete_by_location_id(self, location_id: int) -> None:
        self._conn.execute("DELETE FROM inventory_item WHERE location_id = ?", (location_id,))

    def find_existing_stock_locations(
        self, part_number: str
    ) -> list[ExistingStockLocationProjection]:
        rows = self._conn.execute(
            """
            SELECT
                sl.code AS locationCode,
                sl.displayName AS locationDisplayName,
                ii.quantity AS quantity
            FROM inventory_item ii
            INNER JOIN component_master cm ON cm.id = ii.component_id
            INNER JOIN storage_location sl ON sl.id = ii.location_id
            WHERE cm.part_number = ?
            ORDER BY sl.code ASC
            """,
            (part_number,),
        ).fetchall()
        return [
            ExistingStockLocationProjection(
                location_code=r["locationCode"],
                location_display_name=r["locationDisplayName"],
                quantity=r["quantity"],
            )
            for r in rows
        ]

    def get_in_stock_c0_prefixed_part_numbers(self) -> list[str]:
        rows = self._conn.execute(
            """
            SELECT DISTINCT cm.part_number
            FROM inventory_item ii
            INNER JOIN component_master cm ON cm.id = ii.component_id
            WHERE cm.part_number LIKE 'C0%'
            ORDER BY cm.part_number ASC
            """
        ).fetchall()
        return [r[0] for r in rows]

    def observe_items_by_location(self, location_id: int) -> list[LocationInventoryProjection]:
        rows = self._conn.execute(
            """
            SELECT
                ii.id AS inventoryItemId,
                cm.id AS componentId,
                cm.part_number AS partNumber,
                cm.mpn AS mpn,
                cm.name AS name,
                cm.brand AS brand,
                cm.package_name AS packageName,
                cm.category AS category,
                cm.description AS description,
                cm.source_url AS sourceUrl,
                cm.spec_json AS specJson,
                cm.image_local_path AS imageLocalPath,
                cm.image_url AS imageUrl,
                ii.quantity AS quantity,
                ii.last_inbound_at AS lastInboundAt
            FROM inventory_item ii
            INNER JOIN component_master cm ON cm.id = ii.component_id
            WHERE ii.location_id = ?
            ORDER BY cm.part_number ASC
            """,
            (location_id,),
        ).fetchall()
        return [
            LocationInventoryProjection(
                inventory_item_id=r["inventoryItemId"],
                component_id=r["componentId"],
                part_number=r["partNumber"],
                mpn=r["mpn"],
                name=r["name"],
                brand=r["brand"],
                package_name=r["packageName"],
                category=r["category"],
                description=r["description"],
                source_url=r["sourceUrl"],
                spec_json=r["specJson"],
                image_local_path=r["imageLocalPath"],
                image_url=r["imageUrl"],
                quantity=r["quantity"],
                last_inbound_at=r["lastInboundAt"],
            )
            for r in rows
        ]

    def observe_search_inventory_records(self) -> list[SearchInventoryProjection]:
        rows = self._conn.execute(
            """
            SELECT
                ii.id AS inventoryItemId,
                cm.id AS componentId,
                cm.part_number AS partNumber,
                cm.mpn AS mpn,
                cm.name AS name,
                cm.brand AS brand,
                cm.package_name AS packageName,
                cm.category AS category,
                cm.description AS description,
                cm.source_url AS sourceUrl,
                cm.spec_json AS specJson,
                cm.image_local_path AS imageLocalPath,
                cm.image_url AS imageUrl,
                ii.quantity AS quantity,
                sl.id AS locationId,
                sl.code AS locationCode,
                sl.displayName AS locationDisplayName,
                sl.colorHex AS locationColorHex
            FROM inventory_item ii
            INNER JOIN component_master cm ON cm.id = ii.component_id
            INNER JOIN storage_location sl ON sl.id = ii.location_id
            ORDER BY cm.part_number ASC, sl.code ASC
            """
        ).fetchall()
        return [
            SearchInventoryProjection(
                inventory_item_id=r["inventoryItemId"],
                component_id=r["componentId"],
                part_number=r["partNumber"],
                mpn=r["mpn"],
                name=r["name"],
                brand=r["brand"],
                package_name=r["packageName"],
                category=r["category"],
                description=r["description"],
                source_url=r["sourceUrl"],
                spec_json=r["specJson"],
                image_local_path=r["imageLocalPath"],
                image_url=r["imageUrl"],
                quantity=r["quantity"],
                location_id=r["locationId"],
                location_code=r["locationCode"],
                location_display_name=r["locationDisplayName"],
                location_color_hex=r["locationColorHex"],
            )
            for r in rows
        ]

    def observe_location_category_profiles(self) -> list[LocationCategoryProfileProjection]:
        rows = self._conn.execute(
            """
            SELECT
                ii.location_id AS locationId,
                cm.category AS category,
                cm.package_name AS packageName,
                ii.quantity AS quantity
            FROM inventory_item ii
            INNER JOIN component_master cm ON cm.id = ii.component_id
            """
        ).fetchall()
        return [
            LocationCategoryProfileProjection(
                location_id=r["locationId"],
                category=r["category"],
                package_name=r["packageName"],
                quantity=r["quantity"],
            )
            for r in rows
        ]

    def get_location_category_profiles(
        self, location_id: int
    ) -> list[LocationCategoryProfileProjection]:
        rows = self._conn.execute(
            """
            SELECT
                ii.location_id AS locationId,
                cm.category AS category,
                cm.package_name AS packageName,
                ii.quantity AS quantity
            FROM inventory_item ii
            INNER JOIN component_master cm ON cm.id = ii.component_id
            WHERE ii.location_id = ?
            """,
            (location_id,),
        ).fetchall()
        return [
            LocationCategoryProfileProjection(
                location_id=r["locationId"],
                category=r["category"],
                package_name=r["packageName"],
                quantity=r["quantity"],
            )
            for r in rows
        ]

    def get_all_location_category_profiles(self) -> list[LocationCategoryProfileProjection]:
        return self.observe_location_category_profiles()

    def delete_all(self) -> None:
        self._conn.execute("DELETE FROM inventory_item")


class InventoryTransactionDao:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get_all(self) -> list[InventoryTransactionEntity]:
        rows = self._conn.execute(
            "SELECT * FROM inventory_txn ORDER BY id ASC"
        ).fetchall()
        return [_row_to_transaction(r) for r in rows]

    def insert(self, transaction: InventoryTransactionEntity) -> int:
        values = {
            "id": transaction.id,
            "component_id": transaction.component_id,
            "location_id": transaction.location_id,
            "txn_type": transaction.txn_type,
            "quantity_delta": transaction.quantity_delta,
            "source_type": transaction.source_type,
            "source_ref": transaction.source_ref,
            "raw_payload": transaction.raw_payload,
            "created_at": transaction.created_at,
        }
        sql, params = _build_insert(
            "inventory_txn",
            [
                "id", "component_id", "location_id", "txn_type", "quantity_delta",
                "source_type", "source_ref", "raw_payload", "created_at",
            ],
            values,
            id_value=transaction.id,
        )
        return _exec_insert(self._conn, sql, params)

    def insert_all(self, transactions: Iterable[InventoryTransactionEntity]) -> None:
        for t in transactions:
            self.insert(t)

    def delete_by_location_id(self, location_id: int) -> None:
        self._conn.execute("DELETE FROM inventory_txn WHERE location_id = ?", (location_id,))

    def delete_all(self) -> None:
        self._conn.execute("DELETE FROM inventory_txn")


class DashboardDao:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def observe_summary(self) -> DashboardSummaryProjection:
        row = self._conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM component_master) AS componentCount,
                (SELECT COUNT(*) FROM storage_location) AS locationCount,
                (SELECT COUNT(*) FROM inventory_item) AS inventoryCount,
                (SELECT COALESCE(SUM(quantity), 0) FROM inventory_item) AS totalQuantity,
                (SELECT COUNT(*) FROM inventory_txn) AS transactionCount
            """
        ).fetchone()
        return DashboardSummaryProjection(
            component_count=row["componentCount"],
            location_count=row["locationCount"],
            inventory_count=row["inventoryCount"],
            total_quantity=row["totalQuantity"],
            transaction_count=row["transactionCount"],
        )
