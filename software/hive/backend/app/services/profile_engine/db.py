import json
import os
import re
import sqlite3
import glob as glob_mod
import time

import requests

from .brickstore_db import parseDatabase


MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "migrations")

# "2x4" is how a human writes a size; the catalog only ever spells it "2 x 4".
# Normalizing both sides is the single biggest reason search used to miss.
DIMENSION_RE = re.compile(r"(?<=\d)\s*[x×]\s*(?=\d)")
# Everything that isn't a letter, digit or fraction slash becomes a separator,
# so "Brick, Modified" and "(Cheese Slope)" tokenize like the words they are.
SEPARATOR_RE = re.compile(r"[^a-z0-9/]+")
NUMERIC_TOKEN_RE = re.compile(r"^\d+(?:/\d+)?$")
# Printed and decorated variants are ~60% of the catalog and are almost never
# what a labeler wants, so they sort below the plain mold they decorate. The
# part number is the reliable tell — most variant names never say "print".
VARIANT_NAME_RE = re.compile(r"\b(print|printed|sticker|pattern|decorated)\b")
VARIANT_PART_NUM_RE = re.compile(r"(pr|pat|ps)\d")
# Non-System lines the sorter doesn't handle. Demoted, not hidden.
OFF_SYSTEM_RE = re.compile(
    r"^(duplo|modulex|znap|fabuland|primo|quatro|belville|scala|clikits|galidor|homemaker)\b"
)


class PartsData:
    parts: dict[str, dict]
    categories: dict[int, dict]
    bricklink_categories: dict[int, dict]
    colors: dict[int, dict]
    rb_to_bl_color: dict[int, int]
    bl_to_rb_part: dict[str, str]
    api_total_parts: int | None

    generation: int

    def __init__(self):
        self.parts = {}
        self.categories = {}
        self.bricklink_categories = {}
        self.colors = {}
        self.rb_to_bl_color = {}
        self.bl_to_rb_part = {}
        self.api_total_parts = None
        self.generation = 0


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

        # python-side data migration for 003: backfill price_guides from JSON blobs
        if version == 3:
            _migratePriceGuidesFromJson(conn)


def _safeDiv(numerator, denominator):
    try:
        n = float(numerator)
        d = float(denominator)
    except (TypeError, ValueError):
        return None
    if d == 0:
        return None
    return n / d


def _migratePriceGuidesFromJson(conn):
    rows = conn.execute("SELECT item_no, price_guide FROM bricklink_items WHERE price_guide IS NOT NULL").fetchall()
    if not rows:
        return
    migrated = 0
    for item_no, pg_json in rows:
        try:
            pg = json.loads(pg_json)
        except (json.JSONDecodeError, TypeError):
            continue
        ad = pg.get("affiliate_data")
        if not ad:
            continue
        vals = {"item_no": item_no, "updated_at": None}
        for section_key, col_prefix in [
            ("inventory_new", "inv_new"),
            ("inventory_used", "inv_used"),
            ("ordered_new", "ord_new"),
            ("ordered_used", "ord_used"),
        ]:
            s = ad.get(section_key)
            if not s:
                continue
            lots = s.get("unit_quantity", 0)
            qty = s.get("total_quantity", 0)
            vals[f"{col_prefix}_lots"] = lots
            vals[f"{col_prefix}_qty"] = qty
            vals[f"{col_prefix}_min"] = _safeDiv(s.get("min_price"), 1)
            vals[f"{col_prefix}_max"] = _safeDiv(s.get("max_price"), 1)
            vals[f"{col_prefix}_avg"] = _safeDiv(s.get("avg_price"), qty)
            vals[f"{col_prefix}_wavg"] = _safeDiv(s.get("qty_avg_price"), lots)
        conn.execute(
            "INSERT OR REPLACE INTO price_guides ("
            "item_no, updated_at, "
            "inv_new_lots, inv_new_qty, inv_new_min, inv_new_max, inv_new_avg, inv_new_wavg, "
            "inv_used_lots, inv_used_qty, inv_used_min, inv_used_max, inv_used_avg, inv_used_wavg, "
            "ord_new_lots, ord_new_qty, ord_new_min, ord_new_max, ord_new_avg, ord_new_wavg, "
            "ord_used_lots, ord_used_qty, ord_used_min, ord_used_max, ord_used_avg, ord_used_wavg"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                vals.get("item_no"), vals.get("updated_at"),
                vals.get("inv_new_lots", 0), vals.get("inv_new_qty", 0),
                vals.get("inv_new_min"), vals.get("inv_new_max"), vals.get("inv_new_avg"), vals.get("inv_new_wavg"),
                vals.get("inv_used_lots", 0), vals.get("inv_used_qty", 0),
                vals.get("inv_used_min"), vals.get("inv_used_max"), vals.get("inv_used_avg"), vals.get("inv_used_wavg"),
                vals.get("ord_new_lots", 0), vals.get("ord_new_qty", 0),
                vals.get("ord_new_min"), vals.get("ord_new_max"), vals.get("ord_new_avg"), vals.get("ord_new_wavg"),
                vals.get("ord_used_lots", 0), vals.get("ord_used_qty", 0),
                vals.get("ord_used_min"), vals.get("ord_used_max"), vals.get("ord_used_avg"), vals.get("ord_used_wavg"),
            ),
        )
        migrated += 1
    conn.commit()
    print(f"[db] migrated {migrated} price guides from JSON to structured table")


def reloadPartsData(conn, parts_data):
    parts_data.categories = _loadCategories(conn)
    parts_data.bricklink_categories = _loadBricklinkCategories(conn)
    parts_data.colors = _loadColors(conn)
    parts_data.parts = loadPartsDict(conn)
    parts_data.rb_to_bl_color = _buildRbToBlColorMap(parts_data.colors)
    parts_data.bl_to_rb_part = _buildBlToRbPartMap(parts_data.parts)
    # This is the one "catalog changed" hook every sync already goes through, so
    # rebuilding here is what keeps the search index from ever going stale.
    rebuildPartSearch(conn)
    row = conn.execute("SELECT value FROM meta WHERE key='api_total_parts'").fetchone()
    parts_data.api_total_parts = int(row[0]) if row else None
    parts_data.generation += 1


def _buildBlToRbPartMap(parts):
    # Brickognize answers in BrickLink item numbers (4073), the catalog is keyed
    # on Rebrickable part numbers (6141) — without this, every BrickLink-only id
    # looks like an unknown part. First writer wins: a BrickLink item shared by
    # several Rebrickable molds keeps whichever the parts mirror lists first,
    # which is stable across reloads because loadPartsDict is ordered.
    mapping = {}
    for part_num, part in parts.items():
        for item_no in part.get("external_ids", {}).get("BrickLink", []):
            mapping.setdefault(item_no, part_num)
    return mapping


def _buildRbToBlColorMap(colors):
    mapping = {}
    for rb_id, color in colors.items():
        bl = color.get("external_ids", {}).get("BrickLink", {})
        bl_ids = bl.get("ext_ids", [])
        if bl_ids:
            mapping[rb_id] = bl_ids[0]
    return mapping


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
    for row in conn.execute("SELECT item_no, part_num, name, type, category_id, weight, year_released, is_obsolete, synced_at FROM bricklink_items"):
        item_no, part_num, name, item_type, category_id, weight, year_released, is_obsolete, synced_at = row
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
        }

    # load structured price guides. price_guides is now keyed by (item_no, color),
    # but this legacy per-item map (used by the rule engine) needs one row per item;
    # pick each item's most-liquid color as the representative price.
    price_guides = {}
    _pg_best_liquidity = {}
    for row in conn.execute(
        "SELECT item_no, "
        "inv_new_lots, inv_new_qty, inv_new_min, inv_new_max, inv_new_avg, inv_new_wavg, "
        "inv_used_lots, inv_used_qty, inv_used_min, inv_used_max, inv_used_avg, inv_used_wavg, "
        "ord_new_lots, ord_new_qty, ord_new_min, ord_new_max, ord_new_avg, ord_new_wavg, "
        "ord_used_lots, ord_used_qty, ord_used_min, ord_used_max, ord_used_avg, ord_used_wavg "
        "FROM price_guides"
    ):
        item_no = row[0]
        liquidity = (row[2] or 0) + (row[8] or 0)  # inv_new_qty + inv_used_qty
        if item_no in _pg_best_liquidity and liquidity <= _pg_best_liquidity[item_no]:
            continue
        _pg_best_liquidity[item_no] = liquidity
        price_guides[item_no] = {
            "inv_new":  {"lots": row[1], "qty": row[2], "min": row[3], "max": row[4], "avg": row[5], "wavg": row[6]},
            "inv_used": {"lots": row[7], "qty": row[8], "min": row[9], "max": row[10], "avg": row[11], "wavg": row[12]},
            "ord_new":  {"lots": row[13], "qty": row[14], "min": row[15], "max": row[16], "avg": row[17], "wavg": row[18]},
            "ord_used": {"lots": row[19], "qty": row[20], "min": row[21], "max": row[22], "avg": row[23], "wavg": row[24]},
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
                pg = price_guides.get(item_no)
                if pg:
                    entry["price_guide"] = pg
                items_map[item_no] = entry

        if items_map:
            part["bricklink_data"] = {
                "primary_item_no": ids[0],
                "items": items_map,
            }

    return parts


def _normalizeSearchText(text):
    lowered = DIMENSION_RE.sub(" x ", (text or "").lower())
    return " ".join(SEPARATOR_RE.sub(" ", lowered).split())


def _searchTokens(normalized_query):
    # A size is one token, not three. Split "1 x 2" into "1", "x", "2" and every
    # name containing a 1 and a 2 anywhere matches, which is how "slope 1x2" used
    # to bury the actual 1 x 2 slopes under sails and tyres.
    words = normalized_query.split()
    tokens = []
    i = 0
    while i < len(words):
        if (
            NUMERIC_TOKEN_RE.match(words[i])
            and i + 2 < len(words)
            and words[i + 1] == "x"
            and NUMERIC_TOKEN_RE.match(words[i + 2])
        ):
            phrase = [words[i], "x", words[i + 2]]
            i += 3
            while i + 1 < len(words) and words[i] == "x" and NUMERIC_TOKEN_RE.match(words[i + 1]):
                phrase.extend(["x", words[i + 1]])
                i += 2
            tokens.append((" ".join(phrase), "dimension"))
        elif NUMERIC_TOKEN_RE.match(words[i]):
            tokens.append((words[i], "number"))
            i += 1
        else:
            tokens.append((words[i], "word"))
            i += 1
    return tokens


def _isVariantPart(normalized_name, part_num):
    return bool(VARIANT_NAME_RE.search(normalized_name) or VARIANT_PART_NUM_RE.search(part_num.lower()))


def rebuildPartSearch(conn):
    color_counts = {}
    for part_num, count in conn.execute(
        "SELECT pb.part_num, COUNT(DISTINCT bic.bl_color_id) FROM part_bricklink_ids pb "
        "JOIN bricklink_item_colors bic ON bic.item_no = pb.item_no GROUP BY pb.part_num"
    ):
        color_counts[part_num] = count

    bricklink_ids = {}
    for part_num, item_no in conn.execute("SELECT part_num, item_no FROM part_bricklink_ids"):
        bricklink_ids.setdefault(part_num, []).append(item_no)

    rows = []
    for part_num, name in conn.execute("SELECT part_num, name FROM parts").fetchall():
        name_text = _normalizeSearchText(name)
        id_text = _normalizeSearchText(" ".join([part_num] + bricklink_ids.get(part_num, [])))
        rows.append((
            part_num,
            f" {name_text} ",
            f" {id_text} ",
            len(name_text.split()),
            1 if _isVariantPart(name_text, part_num) else 0,
            1 if OFF_SYSTEM_RE.match(name_text) else 0,
            color_counts.get(part_num, 0),
        ))

    # One transaction: WAL readers keep seeing the old index until the commit, so
    # a rebuild never exposes an empty table to a search in flight.
    conn.execute("DELETE FROM part_search")
    conn.executemany(
        "INSERT INTO part_search (part_num, name_text, id_text, word_count, is_variant, is_off_system, popularity) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


def searchParts(conn, query, cat_filter=None, limit=50, offset=0):
    normalized_query = _normalizeSearchText(query)
    conditions = []
    params = []

    # Every token has to hit, in any order, so "2x4 brick" and "brick 2x4" are
    # the same search. Words match on a word prefix (so "bric" still finds
    # bricks); bare numbers must match a whole word in the name, or a part
    # number prefix, so "technic axle 3" doesn't drag in every axle 32.
    for token, kind in _searchTokens(normalized_query):
        if kind == "dimension":
            # The catalog is not consistent about which side comes first — a
            # brick is "Brick 1 x 2" but the slope of the same footprint is
            # "Slope 45° 2 x 1" — so a size matches either way round.
            sizes = token.split(" x ")
            patterns = [f"% {token} %"]
            if len(sizes) == 2 and sizes[0] != sizes[1]:
                patterns.append(f"% {sizes[1]} x {sizes[0]} %")
            conditions.append("(" + " OR ".join(["s.name_text LIKE ?"] * len(patterns)) + ")")
            params.extend(patterns)
        elif kind == "number":
            conditions.append("(s.name_text LIKE ? OR s.id_text LIKE ?)")
            params.extend([f"% {token} %", f"% {token}%"])
        else:
            conditions.append("(s.name_text LIKE ? OR s.id_text LIKE ?)")
            params.extend([f"% {token}%", f"% {token}%"])

    if cat_filter is not None:
        conditions.append("p.part_cat_id = ?")
        params.append(cat_filter)

    if not conditions:
        return [], 0

    where = " AND ".join(conditions)
    from_sql = "parts p JOIN part_search s ON s.part_num = p.part_num"

    count_sql = f"SELECT COUNT(*) FROM {from_sql} WHERE {where}"
    total = conn.execute(count_sql, params).fetchone()[0]

    # Rank in the order a human scans: what you typed, then plain molds over
    # printed variants, then the mold that exists in the most colors (a good
    # proxy for "the common one"), then the shortest name.
    order_terms = []
    tier_params = []
    if normalized_query:
        order_terms.append(
            "CASE "
            "WHEN s.id_text LIKE ? THEN 0 "
            "WHEN s.id_text LIKE ? THEN 1 "
            "WHEN s.name_text = ? THEN 2 "
            "WHEN s.name_text LIKE ? THEN 3 "
            "ELSE 4 END"
        )
        tier_params = [
            f"% {normalized_query} %",
            f"% {normalized_query}%",
            f" {normalized_query} ",
            f" {normalized_query}%",
        ]
    order_terms.extend([
        "s.is_variant",
        "s.is_off_system",
        "CASE WHEN s.popularity >= 40 THEN 0 WHEN s.popularity >= 10 THEN 1 "
        "WHEN s.popularity >= 2 THEN 2 ELSE 3 END",
        "s.word_count",
        "LENGTH(p.name)",
        "p.part_num",
    ])
    order_sql = ", ".join(order_terms)

    sql = (
        f"SELECT p.part_num, p.name, p.part_cat_id, p.year_from, p.year_to, "
        f"p.part_img_url, p.part_url, p.external_ids, c.name, "
        f"bi.name, bc.name "
        f"FROM {from_sql} LEFT JOIN categories c ON c.id = p.part_cat_id "
        f"LEFT JOIN part_bricklink_ids pbi ON pbi.part_num = p.part_num AND pbi.is_primary = 1 "
        f"LEFT JOIN bricklink_items bi ON bi.item_no = pbi.item_no "
        f"LEFT JOIN bricklink_categories bc ON bc.id = bi.category_id "
        f"WHERE {where} ORDER BY {order_sql} LIMIT ? OFFSET ?"
    )
    params.extend(tier_params)
    params.extend([limit, offset])

    results = []
    for row in conn.execute(sql, params):
        part_num, name, part_cat_id, year_from, year_to, part_img_url, part_url, ext_ids_json, cat_name, bl_name, bl_cat_name = row
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
            "_bl_name": bl_name,
            "_bl_category_name": bl_cat_name,
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
    existing = conn.execute("SELECT 1 FROM bricklink_items WHERE item_no = ?", (item["item_no"],)).fetchone()
    if existing:
        # update catalog fields without clobbering price_guide or synced_at
        sets = ["part_num=?", "name=COALESCE(?, name)", "type=COALESCE(?, type)",
                "category_id=COALESCE(?, category_id)", "weight=COALESCE(?, weight)",
                "year_released=COALESCE(?, year_released)", "is_obsolete=COALESCE(?, is_obsolete)",
                "dim_x_studs=COALESCE(?, dim_x_studs)", "dim_y_studs=COALESCE(?, dim_y_studs)"]
        params = [item["part_num"], item.get("name"), item.get("type", "PART"),
                  item.get("category_id"), item.get("weight"), item.get("year_released"),
                  1 if item.get("is_obsolete") else 0,
                  item.get("dim_x_studs"), item.get("dim_y_studs")]
        if item.get("synced_at"):
            sets.append("synced_at=?")
            params.append(item["synced_at"])
        if price_guide_json:
            sets.append("price_guide=?")
            params.append(price_guide_json)
        params.append(item["item_no"])
        conn.execute(f"UPDATE bricklink_items SET {', '.join(sets)} WHERE item_no=?", params)
    else:
        conn.execute(
            "INSERT INTO bricklink_items (item_no, part_num, name, type, category_id, weight, year_released, is_obsolete, synced_at, price_guide, dim_x_studs, dim_y_studs) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                item.get("dim_x_studs"),
                item.get("dim_y_studs"),
            ),
        )


def upsertPartBricklinkId(conn, part_num, item_no, is_primary=0):
    conn.execute(
        "INSERT OR REPLACE INTO part_bricklink_ids (part_num, item_no, is_primary) VALUES (?, ?, ?)",
        (part_num, item_no, is_primary),
    )


def upsertBricklinkItemColors(conn, item_no, bl_color_ids):
    for cid in bl_color_ids or []:
        conn.execute(
            "INSERT OR IGNORE INTO bricklink_item_colors (item_no, bl_color_id) VALUES (?, ?)",
            (item_no, cid),
        )


def setMeta(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()


def getMeta(conn, key):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


# --- catalog sync state (durable, survives restart) ---

CATALOG_SYNC_STATE_COLUMNS = (
    "status", "progress_current", "progress_total", "pages_fetched",
    "last_message", "error", "started_at", "updated_at", "completed_at",
)
_CATALOG_SYNC_STATE_SELECT = (
    "SELECT sync_type, status, progress_current, progress_total, pages_fetched, "
    "last_message, error, started_at, updated_at, completed_at FROM catalog_sync_state"
)


def _rowToCatalogSyncState(row):
    return {
        "sync_type": row[0],
        "status": row[1],
        "progress_current": row[2],
        "progress_total": row[3],
        "pages_fetched": row[4],
        "last_message": row[5],
        "error": row[6],
        "started_at": row[7],
        "updated_at": row[8],
        "completed_at": row[9],
    }


def upsertCatalogSyncState(conn, sync_type, **fields):
    conn.execute("INSERT OR IGNORE INTO catalog_sync_state (sync_type) VALUES (?)", (sync_type,))
    cols = [c for c in CATALOG_SYNC_STATE_COLUMNS if c in fields]
    if cols:
        assignments = ", ".join(f"{c}=?" for c in cols)
        params = [fields[c] for c in cols] + [sync_type]
        conn.execute(f"UPDATE catalog_sync_state SET {assignments} WHERE sync_type=?", params)
    conn.commit()


def getCatalogSyncState(conn, sync_type):
    row = conn.execute(
        f"{_CATALOG_SYNC_STATE_SELECT} WHERE sync_type=?", (sync_type,)
    ).fetchone()
    return _rowToCatalogSyncState(row) if row else None


def getAllCatalogSyncStates(conn):
    rows = conn.execute(_CATALOG_SYNC_STATE_SELECT).fetchall()
    return {row[0]: _rowToCatalogSyncState(row) for row in rows}


def markRunningSyncsInterrupted(conn):
    # A row left in 'running' means the process died mid-sync; surface that so the
    # UI can offer a resume rather than showing a stuck-forever "running".
    conn.execute(
        "UPDATE catalog_sync_state SET status='interrupted', "
        "last_message='Interrupted by server restart — start again to resume' "
        "WHERE status='running'"
    )
    conn.commit()


# --- brickstore db import ---

def importBrickstoreDb(conn, brickstore_db_path, only_minifigs=False):
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

    # upsert items: type P = parts, type M = complete minifigs.
    imported = 0
    skipped = 0
    minifigs = 0
    for item in db_data["items"]:
        item_type = item["type"]
        if item_type == "M":
            # Complete minifigs. Brickognize recognizes assembled figs and returns
            # the BrickLink minifig number (e.g. "sw0001a") as the item id, which is
            # exactly this catalog key. We register each fig as its own "part"
            # (part_num == BL minifig no, primary BrickLink mapping) plus a MINIFIG
            # bricklink item, and seed color 0 (figs are color-agnostic) so the
            # price pass picks it up via type=MINIFIG.
            mf_no = item["no"]
            upsertPart(conn, {
                "part_num": mf_no,
                "name": item["name"],
                "part_cat_id": None,
                "year_from": item.get("year_released"),
                "year_to": item.get("year_last_produced"),
                "external_ids": {"BrickLink": [mf_no]},
            })
            upsertBricklinkItem(conn, {
                "item_no": mf_no,
                "part_num": mf_no,
                "name": item["name"],
                "type": "MINIFIG",
                "category_id": item["category_id"],
                "weight": item["weight"],
                "year_released": item.get("year_released"),
                "is_obsolete": item.get("is_obsolete"),
                "synced_at": "brickstore_db",
                "dim_x_studs": item.get("dim_x_studs"),
                "dim_y_studs": item.get("dim_y_studs"),
            })
            upsertBricklinkItemColors(conn, mf_no, [0])
            minifigs += 1
            continue
        if only_minifigs or item_type != "P":
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
            "dim_x_studs": item.get("dim_x_studs"),
            "dim_y_studs": item.get("dim_y_studs"),
        })
        upsertPartBricklinkId(conn, part_num, item_no)
        upsertBricklinkItemColors(conn, item_no, item.get("known_colors"))
        imported += 1

    conn.commit()
    print(f"[db] imported {imported} bricklink items + {minifigs} minifigs ({skipped} skipped, no matching part)")
    return {"categories": len(db_data["categories"]), "items": imported, "minifigs": minifigs, "skipped": skipped}


# --- bricklink price sync ---

BLA_BATCH_URL = "https://api.bricklink.com/api/affiliate/v1/price_guide_batch"
BLA_BATCH_SIZE = 500
BLA_THROTTLE_SECONDS = 0.5


def syncBricklinkPrices(conn, api_key, should_stop_fn=None, progress_fn=None, only_types=None):
    # Price every real (item, color) combo. The colors come from BrickStore's
    # known_colors (bricklink_item_colors), so we only request combos that exist
    # instead of the old color_id=0 request, which returns a near-empty bucket.
    # ``only_types`` (e.g. {"MINIFIG"}) restricts the pass to those item types so
    # a targeted re-price (just the figs) doesn't re-fetch every part.
    bl_to_rb = {bl: rb for rb, bl in _buildRbToBlColorMap(_loadColors(conn)).items()}

    where = ""
    where_params: list = []
    if only_types:
        where = "WHERE bi.type IN (%s) " % ",".join("?" * len(only_types))
        where_params = list(only_types)
    rows = conn.execute(
        "SELECT bic.item_no, bic.bl_color_id, bi.part_num, bi.type "
        "FROM bricklink_item_colors bic "
        "JOIN bricklink_items bi ON bi.item_no = bic.item_no "
        f"{where}"
        "ORDER BY bic.item_no, bic.bl_color_id",
        where_params,
    ).fetchall()
    combos = [(r[0], r[1], r[2], r[3] or "PART") for r in rows]
    total = len(combos)
    if total == 0:
        return {"total": 0, "updated": 0, "batches": 0, "stopped": False}

    if progress_fn:
        progress_fn(0, total, f"Starting per-color price sync for {total} part/color combos...")

    updated = 0
    batches_sent = 0

    for batch_start in range(0, total, BLA_BATCH_SIZE):
        if should_stop_fn and should_stop_fn():
            return {"total": total, "updated": updated, "batches": batches_sent, "stopped": True}

        batch = combos[batch_start:batch_start + BLA_BATCH_SIZE]
        body = [{"color_id": cid,
                 "item": {"no": item_no, "type": "MINIFIG" if itype == "MINIFIG" else "PART"}}
                for item_no, cid, _, itype in batch]

        time.sleep(BLA_THROTTLE_SECONDS)
        # Retry transient network failures (flaky DNS / connection resets) with
        # backoff rather than aborting the whole multi-thousand-combo sync on a
        # single hiccup. Only connection-level errors are retried; an HTTP error
        # status still raises after raise_for_status below.
        resp = None
        for attempt in range(5):
            try:
                resp = requests.post(
                    BLA_BATCH_URL,
                    params={
                        "currency_code": "USD",
                        "precision": "4",
                        "vat_type": "0",
                        "api_key": api_key,
                    },
                    json=body,
                    timeout=30,
                )
                break
            except requests.exceptions.RequestException as exc:
                if attempt == 4:
                    raise
                wait_s = 2 ** attempt
                if progress_fn:
                    progress_fn(batch_start, total, f"network error ({exc.__class__.__name__}), retry {attempt + 1}/4 in {wait_s}s")
                time.sleep(wait_s)
        resp.raise_for_status()
        result = resp.json()
        batches_sent += 1

        # key responses by (item_no, color_id) since one batch spans many colors
        price_by_key = {}
        for entry in result.get("data", []):
            item_no = entry.get("item", {}).get("no")
            if item_no is not None:
                price_by_key[(item_no, entry.get("color_id"))] = entry

        for item_no, cid, part_num, itype in batch:
            price_entry = price_by_key.get((item_no, cid))
            if not price_entry:
                continue
            existing = conn.execute("SELECT 1 FROM bricklink_items WHERE item_no = ?", (item_no,)).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO bricklink_items (item_no, part_num, type, synced_at) "
                    "VALUES (?, ?, ?, 'price_sync')",
                    (item_no, part_num, itype),
                )
            _upsertPriceGuide(conn, item_no, cid, bl_to_rb.get(cid), price_entry)
            updated += 1

        conn.commit()

        processed = min(batch_start + len(batch), total)
        if progress_fn:
            pct = round((processed / total) * 100)
            progress_fn(
                processed, total,
                f"Prices: {processed} / {total} combos ({pct}%), {updated} priced, batch #{batches_sent}",
            )

        print(f"[prices] batch #{batches_sent}: {len(batch)} combos, {len(price_by_key)} responses")

    return {"total": total, "updated": updated, "batches": batches_sent, "stopped": False}


def _upsertPriceGuide(conn, item_no, bl_color_id, rb_color_id, entry):
    # entry is the BLA response for one (item, color)
    # compute avg = total_price / total_quantity, wavg = total_qty_price / unit_quantity
    vals = {"item_no": item_no, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    for api_key, col_prefix in [
        ("inventory_new", "inv_new"),
        ("inventory_used", "inv_used"),
        ("ordered_new", "ord_new"),
        ("ordered_used", "ord_used"),
    ]:
        s = entry.get(api_key)
        if not s:
            continue
        lots = s.get("unit_quantity", 0)
        qty = s.get("total_quantity", 0)
        vals[f"{col_prefix}_lots"] = lots
        vals[f"{col_prefix}_qty"] = qty
        vals[f"{col_prefix}_min"] = _safeDiv(s.get("min_price"), 1)
        vals[f"{col_prefix}_max"] = _safeDiv(s.get("max_price"), 1)
        vals[f"{col_prefix}_avg"] = _safeDiv(s.get("total_price"), qty)
        vals[f"{col_prefix}_wavg"] = _safeDiv(s.get("total_qty_price"), lots)
    conn.execute(
        "INSERT OR REPLACE INTO price_guides ("
        "item_no, bl_color_id, rb_color_id, updated_at, "
        "inv_new_lots, inv_new_qty, inv_new_min, inv_new_max, inv_new_avg, inv_new_wavg, "
        "inv_used_lots, inv_used_qty, inv_used_min, inv_used_max, inv_used_avg, inv_used_wavg, "
        "ord_new_lots, ord_new_qty, ord_new_min, ord_new_max, ord_new_avg, ord_new_wavg, "
        "ord_used_lots, ord_used_qty, ord_used_min, ord_used_max, ord_used_avg, ord_used_wavg"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            vals.get("item_no"), bl_color_id, rb_color_id, vals.get("updated_at"),
            vals.get("inv_new_lots", 0), vals.get("inv_new_qty", 0),
            vals.get("inv_new_min"), vals.get("inv_new_max"), vals.get("inv_new_avg"), vals.get("inv_new_wavg"),
            vals.get("inv_used_lots", 0), vals.get("inv_used_qty", 0),
            vals.get("inv_used_min"), vals.get("inv_used_max"), vals.get("inv_used_avg"), vals.get("inv_used_wavg"),
            vals.get("ord_new_lots", 0), vals.get("ord_new_qty", 0),
            vals.get("ord_new_min"), vals.get("ord_new_max"), vals.get("ord_new_avg"), vals.get("ord_new_wavg"),
            vals.get("ord_used_lots", 0), vals.get("ord_used_qty", 0),
            vals.get("ord_used_min"), vals.get("ord_used_max"), vals.get("ord_used_avg"), vals.get("ord_used_wavg"),
        ),
    )


# --- admin parts-db browser (read-only inspection / connection verification) ---

def _tableCount(conn, table):
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except sqlite3.Error:
        return None


def adminCatalogOverview(conn):
    parts_total = _tableCount(conn, "parts")
    parts_with_bl_id = conn.execute(
        "SELECT COUNT(DISTINCT part_num) FROM part_bricklink_ids"
    ).fetchone()[0]
    parts_with_bl_item = conn.execute(
        "SELECT COUNT(DISTINCT p.part_num) FROM parts p "
        "JOIN part_bricklink_ids pbi ON pbi.part_num = p.part_num "
        "JOIN bricklink_items bi ON bi.item_no = pbi.item_no"
    ).fetchone()[0]
    parts_with_price = conn.execute(
        "SELECT COUNT(DISTINCT p.part_num) FROM parts p "
        "JOIN part_bricklink_ids pbi ON pbi.part_num = p.part_num "
        "JOIN price_guides pg ON pg.item_no = pbi.item_no"
    ).fetchone()[0]
    # BrickLink ids pointing at a part that doesn't exist, or at no item record
    orphan_bl_ids = conn.execute(
        "SELECT COUNT(*) FROM part_bricklink_ids pbi "
        "WHERE NOT EXISTS (SELECT 1 FROM bricklink_items bi WHERE bi.item_no = pbi.item_no)"
    ).fetchone()[0]
    parts_with_dims = conn.execute(
        "SELECT COUNT(*) FROM bricklink_items WHERE dim_x_studs IS NOT NULL"
    ).fetchone()[0]
    price_rows_with_rb_color = conn.execute(
        "SELECT COUNT(*) FROM price_guides WHERE rb_color_id IS NOT NULL"
    ).fetchone()[0]
    parts_with_geometry = _tableCount(conn, "part_geometry")
    return {
        "tables": {
            "parts": parts_total,
            "categories": _tableCount(conn, "categories"),
            "colors": _tableCount(conn, "colors"),
            "bricklink_items": _tableCount(conn, "bricklink_items"),
            "bricklink_categories": _tableCount(conn, "bricklink_categories"),
            "bricklink_item_colors": _tableCount(conn, "bricklink_item_colors"),
            "part_bricklink_ids": _tableCount(conn, "part_bricklink_ids"),
            "price_guides": _tableCount(conn, "price_guides"),
            "rebrickable_sets": _tableCount(conn, "rebrickable_sets"),
            "rebrickable_set_inventory": _tableCount(conn, "rebrickable_set_inventory"),
        },
        "coverage": {
            "parts_total": parts_total,
            "parts_with_bricklink_id": parts_with_bl_id,
            "parts_with_bricklink_item": parts_with_bl_item,
            "parts_with_price_guide": parts_with_price,
            "bricklink_ids_without_item": orphan_bl_ids,
            "bricklink_items_with_dims": parts_with_dims,
            "price_color_rows_mapped_to_rb": price_rows_with_rb_color,
            "parts_with_ldraw_geometry": parts_with_geometry,
        },
    }


def adminListParts(conn, query=None, cat_filter=None, missing=None, limit=100, offset=0):
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

    if missing == "bricklink_id":
        conditions.append(
            "NOT EXISTS (SELECT 1 FROM part_bricklink_ids pb WHERE pb.part_num = p.part_num)"
        )
    elif missing == "bricklink_item":
        conditions.append(
            "NOT EXISTS (SELECT 1 FROM part_bricklink_ids pb "
            "JOIN bricklink_items bi ON bi.item_no = pb.item_no WHERE pb.part_num = p.part_num)"
        )

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    total = conn.execute(f"SELECT COUNT(*) FROM parts p{where}", params).fetchone()[0]

    sql = (
        "SELECT p.part_num, p.name, p.part_cat_id, p.year_from, p.year_to, "
        "p.part_img_url, p.part_url, p.external_ids, c.name, bi.name, bc.name, "
        "(SELECT COUNT(*) FROM part_bricklink_ids pb WHERE pb.part_num = p.part_num), "
        "(SELECT COUNT(*) FROM part_bricklink_ids pb JOIN bricklink_items b2 ON b2.item_no = pb.item_no WHERE pb.part_num = p.part_num), "
        "(SELECT COUNT(*) FROM part_bricklink_ids pb JOIN price_guides pg ON pg.item_no = pb.item_no WHERE pb.part_num = p.part_num) "
        "FROM parts p LEFT JOIN categories c ON c.id = p.part_cat_id "
        "LEFT JOIN part_bricklink_ids pbi ON pbi.part_num = p.part_num AND pbi.is_primary = 1 "
        "LEFT JOIN bricklink_items bi ON bi.item_no = pbi.item_no "
        "LEFT JOIN bricklink_categories bc ON bc.id = bi.category_id "
        f"{where} ORDER BY p.part_num LIMIT ? OFFSET ?"
    )

    results = []
    for row in conn.execute(sql, params + [limit, offset]):
        (part_num, name, part_cat_id, year_from, year_to, part_img_url, part_url,
         ext_ids_json, cat_name, bl_name, bl_cat_name, bl_id_count, bl_item_count, price_count) = row
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
            "_bl_name": bl_name,
            "_bl_category_name": bl_cat_name,
            "_bl_id_count": bl_id_count,
            "_bl_item_count": bl_item_count,
            "_price_count": price_count,
        })

    return results, total


def adminGetPart(conn, part_num):
    prow = conn.execute(
        "SELECT p.part_num, p.name, p.part_cat_id, p.year_from, p.year_to, "
        "p.part_img_url, p.part_url, p.external_ids, c.name "
        "FROM parts p LEFT JOIN categories c ON c.id = p.part_cat_id WHERE p.part_num = ?",
        (part_num,),
    ).fetchone()
    if not prow:
        return None

    external_ids = json.loads(prow[7]) if prow[7] else {}
    part = {
        "part_num": prow[0],
        "name": prow[1],
        "part_cat_id": prow[2],
        "year_from": prow[3],
        "year_to": prow[4],
        "part_img_url": prow[5],
        "part_url": prow[6],
        "external_ids": external_ids,
        "_category_name": prow[8] or "Unknown",
    }

    bricklink = []
    dim_x = dim_y = None
    for row in conn.execute(
        "SELECT pbi.item_no, pbi.is_primary, bi.name, bi.type, bi.weight, "
        "bi.year_released, bi.is_obsolete, bc.name, "
        "(SELECT COUNT(*) FROM price_guides pg WHERE pg.item_no = pbi.item_no), "
        "bi.dim_x_studs, bi.dim_y_studs "
        "FROM part_bricklink_ids pbi "
        "LEFT JOIN bricklink_items bi ON bi.item_no = pbi.item_no "
        "LEFT JOIN bricklink_categories bc ON bc.id = bi.category_id "
        "WHERE pbi.part_num = ? ORDER BY pbi.is_primary DESC, pbi.item_no",
        (part_num,),
    ):
        bricklink.append({
            "item_no": row[0],
            "is_primary": bool(row[1]),
            "bl_name": row[2],
            "type": row[3],
            "weight": row[4],
            "year_released": row[5],
            "is_obsolete": bool(row[6]) if row[6] is not None else None,
            "bl_category_name": row[7],
            "has_item_record": row[2] is not None,
            "has_price_guide": bool(row[8]),
        })
        if dim_x is None and row[9] is not None:
            dim_x, dim_y = row[9], row[10]

    part["dim_x_studs"] = dim_x
    part["dim_y_studs"] = dim_y

    # per-color prices across this part's bricklink item(s)
    prices = []
    for row in conn.execute(
        "SELECT pg.item_no, pg.bl_color_id, pg.rb_color_id, col.name, "
        "pg.inv_new_qty, pg.inv_new_avg, pg.inv_new_min, pg.inv_new_max, "
        "pg.inv_used_qty, pg.inv_used_avg, pg.inv_used_min, pg.inv_used_max "
        "FROM price_guides pg "
        "JOIN part_bricklink_ids pbi ON pbi.item_no = pg.item_no AND pbi.part_num = ? "
        "LEFT JOIN colors col ON col.id = pg.rb_color_id "
        "ORDER BY pg.inv_used_avg DESC",
        (part_num,),
    ):
        prices.append({
            "item_no": row[0],
            "bl_color_id": row[1],
            "rb_color_id": row[2],
            "color_name": row[3],
            "new_qty": row[4], "new_avg": row[5], "new_min": row[6], "new_max": row[7],
            "used_qty": row[8], "used_avg": row[9], "used_min": row[10], "used_max": row[11],
        })

    geometry = getPartGeometry(conn, part_num)
    dimensions = resolvePartDimensions(conn, part_num)

    return {"part": part, "bricklink": bricklink, "prices": prices,
            "geometry": geometry, "dimensions": dimensions}


def getPartGeometry(conn, part_num):
    row = conn.execute(
        "SELECT ldraw_id, physical_parent_part_num, geometry_source, "
        "bbox_x_mm, bbox_y_mm, bbox_z_mm, max_extent_mm, volume_mm3 "
        "FROM part_geometry WHERE part_num = ?",
        (part_num,),
    ).fetchone()
    if not row:
        return None
    return {
        "ldraw_id": row[0],
        "physical_parent_part_num": row[1],
        "geometry_source": row[2],
        "bbox_x_mm": row[3],
        "bbox_y_mm": row[4],
        "bbox_z_mm": row[5],
        "max_extent_mm": row[6],
        "volume_mm3": row[7],
    }


def upsertPartGeometry(conn, part_num, geom, computed_at):
    conn.execute(
        "INSERT OR REPLACE INTO part_geometry "
        "(part_num, ldraw_id, physical_parent_part_num, geometry_source, "
        "bbox_x_mm, bbox_y_mm, bbox_z_mm, max_extent_mm, volume_mm3, computed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            part_num, geom.get("ldraw_id"), geom.get("physical_parent_part_num"),
            geom.get("geometry_source"), geom.get("bbox_x_mm"), geom.get("bbox_y_mm"),
            geom.get("bbox_z_mm"), geom.get("max_extent_mm"), geom.get("volume_mm3"),
            computed_at,
        ),
    )


# Category -> representative part whose LDraw geometry stands in for the whole
# family (minifig torsos/heads/etc. share one physical shape regardless of print).
# Used only as a runtime fallback; never stored.
_CANONICAL_BY_CATEGORY = {
    "Minifig Upper Body": "973c00",
    "Minifig Torso Assembly": "973c00",
    "Minifig Heads": "3626a",
    "Minifig Head": "3626a",
}


def _geomFields(g):
    return {
        "bbox_x_mm": g["bbox_x_mm"], "bbox_y_mm": g["bbox_y_mm"], "bbox_z_mm": g["bbox_z_mm"],
        "max_extent_mm": g["max_extent_mm"], "volume_mm3": g["volume_mm3"],
    }


def resolvePartDimensions(conn, part_num):
    # Best-available dimensions for a part, in mm, with a source/confidence flag.
    # Tier 1: the part's own LDraw geometry (exact).
    g = getPartGeometry(conn, part_num)
    if g:
        src = "ldraw_" + (g.get("geometry_source") or "direct")
        return {**_geomFields(g), "source": src, "confidence": "exact",
                "ldraw_id": g.get("ldraw_id"), "physical_parent_part_num": g.get("physical_parent_part_num")}

    # Tier 2: category-canonical family shape (e.g. any minifig torso -> 973).
    catrow = conn.execute(
        "SELECT c.name FROM parts p LEFT JOIN categories c ON c.id = p.part_cat_id WHERE p.part_num = ?",
        (part_num,),
    ).fetchone()
    rep = _CANONICAL_BY_CATEGORY.get(catrow[0]) if catrow else None
    if rep:
        gg = getPartGeometry(conn, rep)
        if gg:
            return {**_geomFields(gg), "source": f"canonical:{rep}", "confidence": "family",
                    "ldraw_id": gg.get("ldraw_id"), "physical_parent_part_num": rep}

    # Tier 3: BrickStore stud footprint -> mm (x/y only, height unknown).
    row = conn.execute(
        "SELECT bi.dim_x_studs, bi.dim_y_studs FROM part_bricklink_ids pbi "
        "JOIN bricklink_items bi ON bi.item_no = pbi.item_no "
        "WHERE pbi.part_num = ? AND bi.dim_x_studs IS NOT NULL "
        "ORDER BY pbi.is_primary DESC LIMIT 1",
        (part_num,),
    ).fetchone()
    if row and row[0] is not None:
        import math
        x, y = row[0] * 8.0, row[1] * 8.0
        return {"bbox_x_mm": round(max(x, y), 2), "bbox_y_mm": round(min(x, y), 2), "bbox_z_mm": None,
                "max_extent_mm": round(math.hypot(x, y), 2), "volume_mm3": None,
                "source": "studs_footprint", "confidence": "coarse",
                "ldraw_id": None, "physical_parent_part_num": None}

    return {"bbox_x_mm": None, "bbox_y_mm": None, "bbox_z_mm": None, "max_extent_mm": None,
            "volume_mm3": None, "source": "none", "confidence": "none",
            "ldraw_id": None, "physical_parent_part_num": None}


def getPartColorPrice(conn, part_num, rb_color_id, condition="used"):
    # Lookup used by sorting profiles: price for a detected (part, color).
    # Returns the avg price for the requested condition ('new'|'used'), or None.
    # Prefers the part's primary BrickLink item when several map.
    col = "inv_used_avg" if condition == "used" else "inv_new_avg"
    row = conn.execute(
        f"SELECT pg.{col} FROM price_guides pg "
        "JOIN part_bricklink_ids pbi ON pbi.item_no = pg.item_no AND pbi.part_num = ? "
        "WHERE pg.rb_color_id = ? "
        "ORDER BY pbi.is_primary DESC LIMIT 1",
        (part_num, rb_color_id),
    ).fetchone()
    return row[0] if row and row[0] is not None else None


def adminListCategories(conn):
    rows = conn.execute(
        "SELECT c.id, c.name, c.part_count, "
        "(SELECT COUNT(*) FROM parts p WHERE p.part_cat_id = c.id) "
        "FROM categories c ORDER BY c.name"
    ).fetchall()
    return [
        {"id": r[0], "name": r[1], "part_count": r[2], "actual_part_count": r[3]}
        for r in rows
    ]
