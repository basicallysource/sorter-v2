import csv
import os
import re
import sys
import argparse
from collections import defaultdict

import measure_stl

DEFAULT_MAIN_BOM = 'bom-downloads/BOM of 0000_Main.csv'
DEFAULT_INTERFACE_BOM = 'bom-downloads/BOM of 000_interface_layer_assembly.csv'
DEFAULT_STL_DIR = 'stl-downloads'

ALUMINUM_EXTRUSION_NAMES = {
    'top_beam', 'vertical_beam',
    'crossbeam', 'simple_crossbeams',
    'spoke', 'vertical_frame', 'upper_vertical_frame', 'lower_vertical_frame',
    'vertical_column',
}

# Fallback lengths for extrusions that aren't present as named STLs in the
# stl-downloads/ exports. Anything measurable from STLs overrides these.
EXTRUSION_LENGTHS_MM_FALLBACK = {
    # vertical_column: hardcoded (user-provided). No STL is emitted with
    # this name — if the Onshape model gets a proper rename + re-export,
    # drop this entry.
    'vertical_column': 280,
}

# BOM names that should be treated as aliases of the canonical name used elsewhere.
# Only used for display/grouping; quantities stay attached to the BOM source name.
CANONICAL_ALIAS = {
    'simple_crossbeams': 'crossbeam',
    'vertical_frame': 'spoke',
    'upper_vertical_frame': 'spoke',
    'lower_vertical_frame': 'spoke',
}


def measure_extrusion_lengths(stl_dir):
    """Walk stl_dir for STLs whose BOM-name (basename after ' - ') is a
    known extrusion. Length = longest OBB axis, rounded to mm. If the same
    name shows up in multiple files with conflicting lengths, keep the
    first and warn on the rest."""
    results = {}
    conflicts = defaultdict(list)
    rows = measure_stl.measure_dir(stl_dir)
    for path, _aabb, obb in rows:
        name = measure_stl.bom_name_from_stl(path)
        if name not in ALUMINUM_EXTRUSION_NAMES:
            continue
        length = round(max(obb))
        if name in results:
            if abs(results[name] - length) > 2:
                conflicts[name].append((path, length))
        else:
            results[name] = length
    for name, dups in conflicts.items():
        others = ', '.join(f"{os.path.basename(p)}={l}" for p, l in dups)
        print(f"warning: conflicting STL lengths for {name}: kept {results[name]}, also saw {others}",
              file=sys.stderr)
    return results


def categorize(name, description):
    name_l = (name or '').lower()
    desc_l = (description or '').lower()
    text = f"{name_l} {desc_l}"
    if 'ruthex' in text:
        return 'heat_insert'
    if 'screw' in text or 'bolt' in text:
        return 'screw'
    if 'nut' in text:
        return 'nut'
    # "Aluminum boss" = gear boss (e.g. 20t_Aluminum_ Boss), not an
    # extrusion. Drop from the output.
    if 'boss' in name_l:
        return None
    if name in ALUMINUM_EXTRUSION_NAMES or 'aluminum' in name_l or 'aluminium' in name_l:
        return 'aluminum'
    return None


def branch_of(item_id):
    if item_id == '1.1' or item_id.startswith('1.1.'):
        return 'layer'
    if item_id == '1' or item_id.startswith('1.'):
        return 'interface'
    if item_id == '2' or item_id.startswith('2.'):
        return 'feeder'
    if item_id == '3' or item_id.startswith('3.'):
        return 'layer'
    return None


def effective_qty(item_id, by_id):
    qty = 1
    current = item_id
    while current:
        row = by_id.get(current)
        if row is None:
            break
        qty *= int(row['Quantity'])
        parts = current.split('.')
        if len(parts) <= 1:
            break
        current = '.'.join(parts[:-1])
    return qty


def is_leaf(item_id, all_ids):
    prefix = item_id + '.'
    return not any(other.startswith(prefix) for other in all_ids)


def process_main(path):
    by_id = {}
    with open(path, newline='') as f:
        for row in csv.DictReader(f):
            by_id[row['Item']] = row
    all_ids = set(by_id)
    result = defaultdict(list)
    for item_id, row in by_id.items():
        if not is_leaf(item_id, all_ids):
            continue
        name = (row.get('Name') or '').strip()
        desc = (row.get('Description') or '').strip()
        cat = categorize(name, desc)
        if cat is None:
            continue
        br = branch_of(item_id)
        if br is None:
            continue
        qty = effective_qty(item_id, by_id)
        result[br].append((cat, name, desc, qty))
    return result


def process_interface(path):
    out = []
    with open(path, newline='') as f:
        for row in csv.DictReader(f):
            name = (row.get('Name') or '').strip()
            desc = (row.get('Description') or '').strip()
            cat = categorize(name, desc)
            if cat is None:
                continue
            qty = int(row['Quantity'])
            out.append((cat, name, desc, qty))
    return out


def aggregate(entries):
    totals = defaultdict(int)
    descs = {}
    for cat, name, desc, qty in entries:
        key = (cat, name)
        totals[key] += qty
        if desc and key not in descs:
            descs[key] = desc
    return totals, descs


def scale(totals, factor):
    return {k: v * factor for k, v in totals.items()}


def halve(totals):
    out = {}
    for k, v in totals.items():
        if v % 2 != 0:
            raise ValueError(f"layer total for {k} is odd ({v}); cannot halve cleanly")
        out[k] = v // 2
    return out


def merge(*totals_list):
    merged = defaultdict(int)
    for totals in totals_list:
        for k, v in totals.items():
            merged[k] += v
    return merged


SCREW_RE = re.compile(r'M(\d+)x([\d.]+)\s*x\s*(\d+)')
NUT_RE = re.compile(r'M(\d+)(?:x([\d.]+))?')
RUTHEX_RX_RE = re.compile(r'RX-M(\d+)-([\d.,]+)')
RUTHEX_M_RE = re.compile(r'M(\d+)(?:x([\d.]+))?')


class BOMNameParseError(ValueError):
    """Raised when a BOM item name doesn't match the expected pattern for
    its category. Fail loud so drifted names get caught instead of silently
    producing blank fields."""


def parse_screw(name):
    m = SCREW_RE.search(name)
    if not m:
        raise BOMNameParseError(
            f"screw name does not match expected 'M<n>x<pitch> x <length>' pattern: {name!r}. "
            f"Fix the BOM entry or update SCREW_RE in build_bom.py."
        )
    size = f'M{m.group(1)}'
    pitch = m.group(2)
    length = m.group(3)
    n = name.lower()
    if 'button' in n:
        head = 'button'
    elif 'countersunk' in n:
        head = 'countersunk'
    elif 'socket head' in n or 'cap' in n:
        head = 'socket cap'
    else:
        raise BOMNameParseError(
            f"screw head type not recognized in name: {name!r}. "
            f"Expected one of: button, countersunk, socket head/cap."
        )
    grade = ''
    gm = re.search(r'grade\s+[A-Za-z&\s]+?(?=\s+M\d|$)', name, re.IGNORECASE)
    if gm:
        grade = gm.group(0).replace('grade', '').replace('Grade', '').strip()
    return {'size': size, 'pitch': pitch, 'length_mm': length, 'head_type': head, 'grade': grade}


def parse_nut(name):
    n = name.lower()
    if 'flange' in n:
        nut_type = 'flange'
    elif 'pronged' in n:
        nut_type = 'pronged'
    elif 'hex' in n:
        nut_type = 'hex'
    else:
        raise BOMNameParseError(
            f"nut type not recognized in name: {name!r}. "
            f"Expected one of: flange, pronged, hex."
        )
    m = NUT_RE.search(name)
    if not m:
        raise BOMNameParseError(
            f"nut size (M<n>) not found in name: {name!r}. "
            f"Fix the BOM entry or update NUT_RE in build_bom.py."
        )
    return {'size': f'M{m.group(1)}', 'pitch': m.group(2) or '', 'type': nut_type}


# Hardcoded depth fallback for heat inserts whose names don't carry the
# depth suffix. Right now this only covers M5 because the three "Ruthex
# M5" rows in the interface BOM all lack the depth token.
#
# Why this happens: the assemblies pull the M5 insert part from more than
# one source part studio. The interface "modified top bracket" sources
# its insert from the original Sorter V2 document, where the part wasn't
# renamed with its depth. Meanwhile the interface idler gear assembly
# uses the shared-document version where the part is named properly
# (e.g. "Ruthex M4x8.1mm"). Fix by re-linking the modified top bracket
# to the shared-document part in Onshape; then this fallback can go.
HEAT_INSERT_DEPTH_FALLBACK_MM = {
    'M5': '9.5',
}


def parse_heat_insert(name):
    rx = RUTHEX_RX_RE.search(name)
    if rx:
        return {'size': f'M{rx.group(1)}', 'depth_mm': rx.group(2).replace(',', '.')}
    m = RUTHEX_M_RE.search(name)
    if m:
        size = f'M{m.group(1)}'
        depth = m.group(2) or HEAT_INSERT_DEPTH_FALLBACK_MM.get(size, '')
        return {'size': size, 'depth_mm': depth}
    raise BOMNameParseError(
        f"heat insert size (M<n>) not found in name: {name!r}. "
        f"Expected 'Ruthex M<n>...' or 'RX-M<n>-<depth>'."
    )


def write_csv(path, totals, descs, label, lengths):
    qty_col = f'quantity_{label}'
    buckets = defaultdict(list)
    for (cat, name), qty in totals.items():
        buckets[cat].append((name, qty))

    sections = []

    aluminum_rows = []
    for name, qty in buckets.get('aluminum', []):
        canonical = CANONICAL_ALIAS.get(name, name)
        length = lengths.get(name, lengths.get(canonical, ''))
        notes = '' if name in ALUMINUM_EXTRUSION_NAMES else 'not an extrusion'
        aluminum_rows.append((name, canonical if canonical != name else '', qty, length, notes))
    sections.append((
        '# aluminum',
        ['name', 'canonical', qty_col, 'length_mm', 'notes'],
        sorted(aluminum_rows),
    ))

    screw_rows = []
    for name, qty in buckets.get('screw', []):
        p = parse_screw(name)
        screw_rows.append((p['size'], p['pitch'], p['length_mm'], p['head_type'],
                           p['grade'], qty, name))
    sections.append((
        '# screws',
        ['size', 'pitch', 'length_mm', 'head_type', 'grade', qty_col, 'name'],
        sorted(screw_rows, key=lambda r: (r[0], r[3], int(r[2] or 0))),
    ))

    nut_rows = []
    for name, qty in buckets.get('nut', []):
        p = parse_nut(name)
        nut_rows.append((p['size'], p['pitch'], p['type'], qty, name))
    sections.append((
        '# nuts',
        ['size', 'pitch', 'type', qty_col, 'name'],
        sorted(nut_rows, key=lambda r: (r[0], r[2])),
    ))

    heat_rows = []
    for name, qty in buckets.get('heat_insert', []):
        p = parse_heat_insert(name)
        heat_rows.append((p['size'], p['depth_mm'], qty, name))
    sections.append((
        '# heat_inserts',
        ['size', 'depth_mm', qty_col, 'name'],
        sorted(heat_rows, key=lambda r: (r[0], r[1])),
    ))

    with open(path, 'w', newline='') as f:
        w = csv.writer(f)
        for i, (title, header, rows) in enumerate(sections):
            if i > 0:
                w.writerow([])
            w.writerow([title])
            w.writerow(header)
            for r in rows:
                w.writerow(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--main-bom', default=DEFAULT_MAIN_BOM,
                    help=f'path to main assembly BOM (default: {DEFAULT_MAIN_BOM})')
    ap.add_argument('--interface-bom', default=DEFAULT_INTERFACE_BOM,
                    help=f'path to interface layer BOM (default: {DEFAULT_INTERFACE_BOM})')
    ap.add_argument('--stl-dir', default=DEFAULT_STL_DIR,
                    help=f'path to STL export root (default: {DEFAULT_STL_DIR})')
    args = ap.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(script_dir, 'bom-outputs')
    os.makedirs(out_dir, exist_ok=True)

    main_path = args.main_bom if os.path.isabs(args.main_bom) else os.path.join(script_dir, args.main_bom)
    iface_path = args.interface_bom if os.path.isabs(args.interface_bom) else os.path.join(script_dir, args.interface_bom)
    stl_path = args.stl_dir if os.path.isabs(args.stl_dir) else os.path.join(script_dir, args.stl_dir)

    print(f"using main BOM: {args.main_bom}  (pass --main-bom path/to/file.csv to override)")
    print(f"using interface BOM: {args.interface_bom}  (pass --interface-bom path/to/file.csv to override)")
    print(f"using STL dir: {args.stl_dir}  (pass --stl-dir path/to/dir to override)")

    measured = measure_extrusion_lengths(stl_path)
    lengths = {**EXTRUSION_LENGTHS_MM_FALLBACK, **measured}
    hardcoded_used = sorted(k for k in EXTRUSION_LENGTHS_MM_FALLBACK if k not in measured)
    print(f"  measured {len(measured)} extrusion length(s) from STLs: "
          f"{', '.join(sorted(measured)) or '(none)'}")
    if hardcoded_used:
        print(f"  fallback (hardcoded) lengths used for: {', '.join(hardcoded_used)}")

    main_data = process_main(main_path)
    iface_data = process_interface(iface_path)

    main_iface_totals, main_iface_descs = aggregate(main_data['interface'])
    feeder_totals, feeder_descs = aggregate(main_data['feeder'])
    layer_raw_totals, layer_descs = aggregate(main_data['layer'])
    iface_detail_totals, iface_detail_descs = aggregate(iface_data)

    # interface = aluminum from main BOM + fasteners/inserts from interface BOM
    main_iface_al = {k: v for k, v in main_iface_totals.items() if k[0] == 'aluminum'}
    iface_non_al = {k: v for k, v in iface_detail_totals.items() if k[0] != 'aluminum'}
    # include any aluminum from the interface BOM that's not already in main
    iface_al_extra = {k: v for k, v in iface_detail_totals.items()
                      if k[0] == 'aluminum' and k not in main_iface_al}
    interface_totals = merge(main_iface_al, iface_non_al, iface_al_extra)
    interface_descs = {**main_iface_descs, **iface_detail_descs}

    layer_totals = halve(layer_raw_totals)

    per_machine_totals = merge(
        interface_totals,
        feeder_totals,
        layer_totals,
    )
    per_machine_descs = {**interface_descs, **feeder_descs, **layer_descs}

    layer_csv = 'cad_export_bom_just_hardware_per_layer.csv'
    machine_csv = 'cad_export_bom_just_hardware_per_machine.csv'
    write_csv(os.path.join(out_dir, layer_csv),
              layer_totals, layer_descs, 'per_layer', lengths)
    write_csv(os.path.join(out_dir, machine_csv),
              per_machine_totals, per_machine_descs,
              'per_machine', lengths)

    print(f"wrote {layer_csv} and {machine_csv} to {out_dir}")
    print(f"  interface rows: {len(interface_totals)}")
    print(f"  feeder rows: {len(feeder_totals)}")
    print(f"  layer rows: {len(layer_totals)}")


if __name__ == '__main__':
    main()
