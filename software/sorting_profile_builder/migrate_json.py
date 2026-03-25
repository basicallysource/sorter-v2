import argparse
import json
import os

from db import initDb, upsertCategories, upsertColors, upsertPart, upsertBricklinkCategory, upsertBricklinkItem, upsertPartBricklinkId, setMeta, loadPartsDict


def migrate(parts_json_path, db_path):
    print(f"loading {parts_json_path} ...")
    with open(parts_json_path, "r") as f:
        data = json.load(f)

    if os.path.exists(db_path):
        print(f"removing existing {db_path}")
        os.remove(db_path)

    conn = initDb(db_path)

    # categories
    cats = data.get("categories", {})
    cat_list = []
    for cat_id_str, cat_data in cats.items():
        cat_list.append({
            "id": int(cat_id_str),
            "name": cat_data.get("name", ""),
            "part_count": cat_data.get("part_count", 0),
        })
    upsertCategories(conn, cat_list)
    print(f"  {len(cat_list)} categories")

    # bricklink categories
    bl_cats = data.get("bricklink_categories", {})
    for cat_id_str, cat_data in bl_cats.items():
        cat_id = int(cat_id_str)
        name = cat_data.get("category_name", cat_data.get("name", ""))
        parent_id = cat_data.get("parent_id", 0)
        upsertBricklinkCategory(conn, cat_id, name, parent_id)
    conn.commit()
    print(f"  {len(bl_cats)} bricklink categories")

    # colors
    colors = data.get("colors", {})
    color_list = []
    for color_id_str, color_data in colors.items():
        c = dict(color_data)
        c["id"] = int(color_id_str)
        if "name" not in c:
            c["name"] = ""
        color_list.append(c)
    upsertColors(conn, color_list)
    print(f"  {len(color_list)} colors")

    # parts (batch insert)
    parts = data.get("parts", {})
    print(f"  migrating {len(parts)} parts...")
    count = 0
    for part_num, part_data in parts.items():
        part_data["part_num"] = part_num
        upsertPart(conn, part_data)

        # migrate bricklink_data if present
        bricklink_data = part_data.get("bricklink_data")
        if isinstance(bricklink_data, dict):
            items_map = bricklink_data.get("items")
            if isinstance(items_map, dict):
                for item_no, item_entry in items_map.items():
                    catalog = item_entry.get("catalog")
                    if isinstance(catalog, dict):
                        cat_data = catalog.get("data", {})
                        bl_item = {
                            "item_no": item_no,
                            "part_num": part_num,
                            "name": cat_data.get("name"),
                            "type": cat_data.get("type", "PART"),
                            "category_id": cat_data.get("category_id"),
                            "weight": float(cat_data["weight"]) if cat_data.get("weight") else None,
                            "year_released": cat_data.get("year_released"),
                            "is_obsolete": cat_data.get("is_obsolete", False),
                            "synced_at": item_entry.get("catalog_synced_at"),
                        }
                        price_guide = item_entry.get("price_guide")
                        if isinstance(price_guide, dict):
                            bl_item["price_guide"] = price_guide
                        upsertBricklinkItem(conn, bl_item)
                        upsertPartBricklinkId(conn, part_num, item_no)

        count += 1
        if count % 10000 == 0:
            conn.commit()
            print(f"    {count} / {len(parts)} parts...")

    conn.commit()
    print(f"  {count} parts migrated")

    # store api_total_parts if we can infer it
    setMeta(conn, "api_total_parts", str(len(parts)))

    # verify
    print("\nverifying...")
    row_counts = {}
    for table in ["categories", "bricklink_categories", "colors", "parts", "part_bricklink_ids", "bricklink_items"]:
        row_counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {row_counts[table]} rows")

    # spot check: reconstruct parts dict and verify a few fields
    print("\nspot-checking loadPartsDict...")
    reconstructed = loadPartsDict(conn)
    print(f"  reconstructed {len(reconstructed)} parts")

    mismatches = 0
    checked = 0
    for part_num in list(parts.keys())[:100]:
        original = parts[part_num]
        rebuilt = reconstructed.get(part_num)
        if not rebuilt:
            mismatches += 1
            continue
        if original.get("name") != rebuilt.get("name"):
            print(f"  MISMATCH name for {part_num}: {original.get('name')!r} vs {rebuilt.get('name')!r}")
            mismatches += 1
        if original.get("part_cat_id") != rebuilt.get("part_cat_id"):
            print(f"  MISMATCH part_cat_id for {part_num}")
            mismatches += 1
        checked += 1

    if mismatches == 0:
        print(f"  all {checked} spot checks passed")
    else:
        print(f"  {mismatches} mismatches in {checked} checks")

    conn.close()
    db_size = os.path.getsize(db_path)
    print(f"\ndone. {db_path} = {db_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="migrate parts.json to SQLite")
    parser.add_argument("--parts-json", required=True, help="path to parts.json")
    parser.add_argument("--db-path", default="./parts.db", help="output SQLite path")
    args = parser.parse_args()
    migrate(args.parts_json, args.db_path)
