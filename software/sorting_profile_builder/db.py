import json
import os
import sqlite3
import glob as glob_mod
import time

import requests

from brickstore_db import parseDatabase


MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "migrations")


class PartsData:
    parts: dict[str, dict]
    categories: dict[int, dict]
    bricklink_categories: dict[int, dict]
    colors: dict[int, dict]
    api_total_parts: int | None

    def __init__(self):
        self.parts = {}
        self.categories = {}
        self.bricklink_categories = {}
        self.colors = {}
        self.api_total_parts = None


def initDb(db_path):
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    runMigrations(conn)
    return conn


def runMigrations(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    current_version = int(row[0]) if row else 0

    sql_files = sorted(glob_mod.glob(os.path.join(MIGRATIONS_DIR, "*.sql")))
    for sql_path in sql_files:
        fname = os.path.basename(sql_path)
        version = int(fname.split("_")[0])
        if version <= current_version:
            continue
        print(f"[db] running migration {fname}")
        with open(sql_path, "r") as f:
            sql = f.read()
        # skip CREATE TABLE meta since we already created it above
        statements = sql.split(";")
        for stmt in statements:
            stmt = stmt.strip()
            if not stmt:
                continue
            if stmt.startswith("CREATE TABLE meta"):
                continue
            conn.execute(stmt)
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(version),),
        )
        conn.commit()
        print(f"[db] migration {fname} complete")


def reloadPartsData(conn, parts_data):
    parts_data.categories = _loadCategories(conn)
    parts_data.bricklink_categories = _loadBricklinkCategories(conn)
    parts_data.colors = _loadColors(conn)
    parts_data.parts = loadPartsDict(conn)
    row = conn.execute("SELECT value FROM meta WHERE key='api_total_parts'").fetchone()
    parts_data.api_total_parts = int(row[0]) if row else None


def _loadCategories(conn):
    cats = {}
    for row in conn.execute("SELECT id, name, part_count FROM categories"):
        cats[row[0]] = {"id": row[0], "name": row[1], "part_count": row[2]}
    return cats


def _loadBricklinkCategories(conn):
    cats = {}
    for row in conn.execute("SELECT id, name, parent_id FROM bricklink_categories"):
        cats[row[0]] = {"category_id": row[0], "category_name": row[1], "parent_id": row[2]}
    return cats


def _loadColors(conn):
    colors = {}
    for row in conn.execute("SELECT id, name, rgb, is_trans, extra FROM colors"):
        color = json.loads(row[4]) if row[4] else {}
        color["id"] = row[0]
        color["name"] = row[1]
        color["rgb"] = row[2]
        color["is_trans"] = bool(row[3])
        colors[row[0]] = color
    return colors


def loadPartsDict(conn):
    parts = {}

    # load all parts
    for row in conn.execute("SELECT part_num, name, part_cat_id, year_from, year_to, part_img_url, part_url, external_ids FROM parts"):
        part_num, name, part_cat_id, year_from, year_to, part_img_url, part_url, external_ids_json = row
        external_ids = json.loads(external_ids_json) if external_ids_json else {}
        parts[part_num] = {
            "part_num": part_num,
            "name": name,
            "part_cat_id": part_cat_id,
            "year_from": year_from,
            "year_to": year_to,
            "part_img_url": part_img_url,
            "part_url": part_url,
            "external_ids": external_ids,
        }

    # load bricklink id mappings
    bl_ids_by_part = {}
    for row in conn.execute("SELECT part_num, item_no, is_primary FROM part_bricklink_ids ORDER BY is_primary DESC"):
        part_num, item_no, is_primary = row
        bl_ids_by_part.setdefault(part_num, []).append(item_no)

    # load bricklink items
    bl_items = {}
    for row in conn.execute("SELECT item_no, part_num, name, type, category_id, weight, year_released, is_obsolete, synced_at, price_guide FROM bricklink_items"):
        item_no, part_num, name, item_type, category_id, weight, year_released, is_obsolete, synced_at, price_guide_json = row
        bl_items[item_no] = {
            "item_no": item_no,
            "part_num": part_num,
            "name": name,
            "type": item_type,
            "category_id": category_id,
            "weight": weight,
            "year_released": year_released,
            "is_obsolete": is_obsolete,
            "synced_at": synced_at,
            "price_guide": json.loads(price_guide_json) if price_guide_json else None,
        }

    # reconstruct bricklink_data structure for rule_engine compatibility
    for part_num, ids in bl_ids_by_part.items():
        part = parts.get(part_num)
        if not part:
            continue

        # ensure external_ids has BrickLink list
        if "BrickLink" not in part["external_ids"]:
            part["external_ids"]["BrickLink"] = ids

        items_map = {}
        for item_no in ids:
            bl_item = bl_items.get(item_no)
            if bl_item:
                entry = {
                    "catalog": {
                        "meta": {"code": 200, "message": "OK", "description": "OK"},
                        "data": {
                            "no": item_no,
                            "name": bl_item["name"],
                            "type": "PART",
                            "category_id": bl_item["category_id"],
                            "weight": f'{bl_item["weight"]:.2f}' if bl_item["weight"] else "0.00",
                            "year_released": bl_item["year_released"],
                            "is_obsolete": bool(bl_item["is_obsolete"]),
                        },
                    },
                    "catalog_synced_at": bl_item["synced_at"],
                    "part_num": part_num,
                    "bricklink_item_no": item_no,
                }
                if bl_item["price_guide"]:
                    entry["price_guide"] = bl_item["price_guide"]
                items_map[item_no] = entry

        if items_map:
            part["bricklink_data"] = {
                "primary_item_no": ids[0],
                "items": items_map,
            }

    return parts


def searchParts(conn, query, cat_filter=None, limit=50, offset=0):
    query_lower = query.lower().strip() if query else ""
    conditions = []
    params = []

    if query_lower:
        conditions.append(
            "(LOWER(p.name) LIKE ? OR LOWER(p.part_num) LIKE ? OR EXISTS "
            "(SELECT 1 FROM part_bricklink_ids pb WHERE pb.part_num = p.part_num AND LOWER(pb.item_no) LIKE ?))"
        )
        like_val = f"%{query_lower}%"
        params.extend([like_val, like_val, like_val])

    if cat_filter is not None:
        conditions.append("p.part_cat_id = ?")
        params.append(cat_filter)

    if not conditions:
        return [], 0

    where = " AND ".join(conditions)

    count_sql = f"SELECT COUNT(*) FROM parts p WHERE {where}"
    total = conn.execute(count_sql, params).fetchone()[0]

    sql = (
        f"SELECT p.part_num, p.name, p.part_cat_id, p.year_from, p.year_to, "
        f"p.part_img_url, p.part_url, p.external_ids, c.name "
        f"FROM parts p LEFT JOIN categories c ON c.id = p.part_cat_id "
        f"WHERE {where} ORDER BY p.part_num LIMIT ? OFFSET ?"
    )
    params.extend([limit, offset])

    results = []
    for row in conn.execute(sql, params):
        part_num, name, part_cat_id, year_from, year_to, part_img_url, part_url, ext_ids_json, cat_name = row
        external_ids = json.loads(ext_ids_json) if ext_ids_json else {}
        results.append({
            "part_num": part_num,
            "name": name,
            "part_cat_id": part_cat_id,
            "year_from": year_from,
            "year_to": year_to,
            "part_img_url": part_img_url,
            "part_url": part_url,
            "external_ids": external_ids,
            "_category_name": cat_name or "Unknown",
        })

    return results, total


# --- upsert functions for sync ---

def upsertCategories(conn, categories_list):
    conn.executemany(
        "INSERT OR REPLACE INTO categories (id, name, part_count) VALUES (?, ?, ?)",
        [(c["id"], c["name"], c.get("part_count", 0)) for c in categories_list],
    )
    conn.commit()


def upsertColors(conn, colors_list):
    for c in colors_list:
        color_id = c["id"]
        extra = json.dumps({k: v for k, v in c.items() if k not in ("id", "name", "rgb", "is_trans")})
        conn.execute(
            "INSERT OR REPLACE INTO colors (id, name, rgb, is_trans, extra) VALUES (?, ?, ?, ?, ?)",
            (color_id, c.get("name", ""), c.get("rgb"), 1 if c.get("is_trans") else 0, extra),
        )
    conn.commit()


def upsertPart(conn, part_data):
    part_num = part_data["part_num"]
    external_ids = json.dumps(part_data.get("external_ids", {}))
    conn.execute(
        "INSERT OR REPLACE INTO parts (part_num, name, part_cat_id, year_from, year_to, part_img_url, part_url, external_ids) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            part_num,
            part_data.get("name", ""),
            part_data.get("part_cat_id"),
            part_data.get("year_from"),
            part_data.get("year_to"),
            part_data.get("part_img_url"),
            part_data.get("part_url"),
            external_ids,
        ),
    )
    # upsert bricklink id mappings from external_ids
    bl_ids = part_data.get("external_ids", {}).get("BrickLink", [])
    for i, item_no in enumerate(bl_ids):
        if item_no is None:
            continue
        item_no = str(item_no).strip()
        if not item_no:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO part_bricklink_ids (part_num, item_no, is_primary) VALUES (?, ?, ?)",
            (part_num, item_no, 1 if i == 0 else 0),
        )


def upsertParts(conn, parts_list):
    for p in parts_list:
        upsertPart(conn, p)
    conn.commit()


def upsertBricklinkCategory(conn, cat_id, name, parent_id=0):
    conn.execute(
        "INSERT OR REPLACE INTO bricklink_categories (id, name, parent_id) VALUES (?, ?, ?)",
        (cat_id, name, parent_id),
    )


def upsertBricklinkItem(conn, item):
    price_guide = item.get("price_guide")
    price_guide_json = json.dumps(price_guide) if price_guide else None
    conn.execute(
        "INSERT OR REPLACE INTO bricklink_items (item_no, part_num, name, type, category_id, weight, year_released, is_obsolete, synced_at, price_guide) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            item["item_no"],
            item["part_num"],
            item.get("name"),
            item.get("type", "PART"),
            item.get("category_id"),
            item.get("weight"),
            item.get("year_released"),
            1 if item.get("is_obsolete") else 0,
            item.get("synced_at"),
            price_guide_json,
        ),
    )


def upsertPartBricklinkId(conn, part_num, item_no, is_primary=0):
    conn.execute(
        "INSERT OR REPLACE INTO part_bricklink_ids (part_num, item_no, is_primary) VALUES (?, ?, ?)",
        (part_num, item_no, is_primary),
    )


def setMeta(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()


def getMeta(conn, key):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


# --- brickstore db import ---

def importBrickstoreDb(conn, brickstore_db_path):
    db_data = parseDatabase(brickstore_db_path)

    # upsert categories
    for cat in db_data["categories"]:
        upsertBricklinkCategory(conn, cat["category_id"], cat["category_name"])
    conn.commit()
    print(f"[db] imported {len(db_data['categories'])} bricklink categories")

    # build a reverse map: bricklink item_no -> part_num (from part_bricklink_ids)
    bl_to_part = {}
    for row in conn.execute("SELECT part_num, item_no FROM part_bricklink_ids"):
        bl_to_part[row[1]] = row[0]

    # upsert items (only type P = parts)
    imported = 0
    skipped = 0
    for item in db_data["items"]:
        if item["type"] != "P":
            continue
        item_no = item["no"]
        part_num = bl_to_part.get(item_no)
        if not part_num:
            # no matching rebrickable part, create a bricklink-only mapping
            # use the item_no as part_num since we don't have an RB mapping
            part_num = item_no
            # check if this part exists in our parts table
            exists = conn.execute("SELECT 1 FROM parts WHERE part_num=?", (part_num,)).fetchone()
            if not exists:
                skipped += 1
                continue

        upsertBricklinkItem(conn, {
            "item_no": item_no,
            "part_num": part_num,
            "name": item["name"],
            "type": "PART",
            "category_id": item["category_id"],
            "weight": item["weight"],
            "year_released": item["year_released"],
            "is_obsolete": item["is_obsolete"],
            "synced_at": "brickstore_db",
        })
        upsertPartBricklinkId(conn, part_num, item_no)
        imported += 1

    conn.commit()
    print(f"[db] imported {imported} bricklink items ({skipped} skipped, no matching part)")
    return {"categories": len(db_data["categories"]), "items": imported, "skipped": skipped}


# --- bricklink affiliate price sync ---

BL_AFFILIATE_BATCH_URL = "https://api.bricklink.com/api/affiliate/v1/price_guide_batch"
BL_AFFILIATE_BATCH_SIZE = 500
BL_AFFILIATE_THROTTLE_SECONDS = 0.5


def syncBricklinkPrices(conn, api_key, should_stop_fn=None, progress_fn=None):
    # get ALL parts that have a bricklink ID, not just ones with existing bricklink_items rows
    rows = conn.execute(
        "SELECT pb.item_no, pb.part_num FROM part_bricklink_ids pb WHERE pb.is_primary = 1"
    ).fetchall()
    all_items = [(r[0], r[1]) for r in rows]
    total = len(all_items)
    if total == 0:
        return {"total": 0, "updated": 0, "batches": 0, "stopped": False}

    if progress_fn:
        progress_fn(0, total, f"Starting price sync for {total} items...")

    updated = 0
    batches_sent = 0

    for batch_start in range(0, total, BL_AFFILIATE_BATCH_SIZE):
        if should_stop_fn and should_stop_fn():
            return {"total": total, "updated": updated, "batches": batches_sent, "stopped": True}

        batch = all_items[batch_start:batch_start + BL_AFFILIATE_BATCH_SIZE]
        body = [{"color_id": 0, "item": {"no": item_no, "type": "PART"}} for item_no, _ in batch]

        time.sleep(BL_AFFILIATE_THROTTLE_SECONDS)
        resp = requests.post(
            BL_AFFILIATE_BATCH_URL,
            params={
                "currency_code": "USD",
                "precision": "4",
                "vat_type": "0",
                "api_key": api_key,
            },
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        batches_sent += 1

        response_data = result.get("data", [])
        price_by_item = {}
        for entry in response_data:
            item_info = entry.get("item", {})
            item_no = item_info.get("no")
            if item_no:
                price_by_item[item_no] = entry

        for item_no, part_num in batch:
            price_entry = price_by_item.get(item_no)
            if not price_entry:
                continue
            price_guide = _affiliateResponseToPriceGuide(price_entry)
            price_guide_json = json.dumps(price_guide)
            # upsert into bricklink_items — create row if it doesn't exist
            existing = conn.execute("SELECT 1 FROM bricklink_items WHERE item_no = ?", (item_no,)).fetchone()
            if existing:
                conn.execute(
                    "UPDATE bricklink_items SET price_guide = ? WHERE item_no = ?",
                    (price_guide_json, item_no),
                )
            else:
                conn.execute(
                    "INSERT INTO bricklink_items (item_no, part_num, type, synced_at, price_guide) "
                    "VALUES (?, ?, 'PART', 'price_sync', ?)",
                    (item_no, part_num, price_guide_json),
                )
            updated += 1

        conn.commit()

        processed = min(batch_start + len(batch), total)
        if progress_fn:
            pct = round((processed / total) * 100)
            progress_fn(
                processed, total,
                f"Prices: {processed} / {total} ({pct}%), {updated} updated, batch #{batches_sent}",
            )

        print(f"[prices] batch #{batches_sent}: {len(batch)} items, {len(price_by_item)} responses")

    return {"total": total, "updated": updated, "batches": batches_sent, "stopped": False}


def _affiliateResponseToPriceGuide(entry):
    # the affiliate API returns inventory_new, inventory_used, ordered_new, ordered_used
    # rule_engine expects the old Store API format: price_guide.data with min/max/avg/qty_avg etc.
    # map ordered_used (past sales, used) as the default since that's most common for sorting
    # but store all four sections so rules can access any
    def _parseSection(section):
        if not section:
            return None
        return {
            "unit_quantity": section.get("unit_quantity", 0),
            "total_quantity": section.get("total_quantity", 0),
            "min_price": section.get("min_price", "0"),
            "max_price": section.get("max_price", "0"),
            "avg_price": section.get("total_price", "0"),
            "qty_avg_price": section.get("total_qty_price", "0"),
        }

    # use inventory_used as the primary "data" since that matches typical BL price guide usage
    # (current for-sale listings, used condition)
    primary = entry.get("inventory_used") or entry.get("inventory_new") or {}

    return {
        "meta": {"code": 200, "message": "OK", "description": "OK"},
        "data": {
            "item": entry.get("item", {}),
            "new_or_used": "U" if entry.get("inventory_used") else "N",
            "currency_code": "USD",
            "min_price": primary.get("min_price", "0"),
            "max_price": primary.get("max_price", "0"),
            "avg_price": primary.get("total_price", "0"),
            "qty_avg_price": primary.get("total_qty_price", "0"),
            "unit_quantity": primary.get("unit_quantity", 0),
            "total_quantity": primary.get("total_quantity", 0),
        },
        "affiliate_data": {
            "inventory_new": _parseSection(entry.get("inventory_new")),
            "inventory_used": _parseSection(entry.get("inventory_used")),
            "ordered_new": _parseSection(entry.get("ordered_new")),
            "ordered_used": _parseSection(entry.get("ordered_used")),
        },
    }
