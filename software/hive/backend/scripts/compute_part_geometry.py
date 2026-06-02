import os
import sys
import time
import json
import sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.profile_engine import db as profile_db
from app.services.profile_engine import ldraw_geometry as lg

DEFAULT_LDRAW = os.path.join(os.path.dirname(__file__), "..", "ldraw_lib", "ldraw")
DEFAULT_DB = os.path.join(os.path.dirname(__file__), "..", "data", "profile_builder", "parts.db")


def main():
    ldraw_root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_LDRAW)
    db_path = os.path.abspath(sys.argv[2] if len(sys.argv) > 2 else DEFAULT_DB)
    print(f"ldraw: {ldraw_root}")
    print(f"db:    {db_path}")

    conn = sqlite3.connect(db_path)
    profile_db.runMigrations(conn)

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    result = lg.computeAllGeometry(
        conn, ldraw_root, profile_db.upsertPartGeometry, now,
        progress_fn=lambda c, t, m: print(f"  {m}"),
    )

    have = result["computed"]
    total = result["total"]
    print(f"\nDONE: {have}/{total} parts with geometry ({100*have/total:.1f}%)")
    print(f"  direct={result['direct']}  parent={result['parent']}")

    print("\nspot-check:")
    for pid in ["3001", "3005", "3023", "3068b", "973pb2833", "3001pr0042"]:
        g = profile_db.getPartGeometry(conn, pid)
        if g:
            print(f"  {pid:14s} {g['bbox_x_mm']}x{g['bbox_y_mm']}x{g['bbox_z_mm']}mm "
                  f"ext={g['max_extent_mm']} vol={g['volume_mm3']} "
                  f"src={g['geometry_source']} parent={g['physical_parent_part_num']}")
        else:
            print(f"  {pid:14s} (none)")


if __name__ == "__main__":
    main()
