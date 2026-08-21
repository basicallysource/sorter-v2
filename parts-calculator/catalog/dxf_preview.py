#!/usr/bin/env python
"""Generate SVG previews for the laser-cut DXFs in ../static/dxf/.

The DXFs are simple OnShape sketch exports (LINE / CIRCLE / ARC only, mm units).
Each one becomes ../static/dxf-previews/<name>.svg — a stroke-only outline the
app shows on the laser-cut parts tab. Prints each part's bounding box so the
sheet dimensions in src/lib/lasercut.ts can be kept honest.

Run:  /opt/homebrew/opt/python@3.11/libexec/bin/python dxf_preview.py
"""
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DXF_DIR = os.path.join(REPO, "static", "dxf")
OUT_DIR = os.path.join(REPO, "static", "dxf-previews")

STROKE = "#1c1c1c"
STROKE_W = 1.2  # in mm, thin but visible at card size


def entities(path):
    """Yield (type, {code: [values]}) for every entity in the ENTITIES section."""
    lines = open(path, errors="ignore").read().replace("\r", "").split("\n")
    i = lines.index("ENTITIES")
    j = i
    while j < len(lines) - 1:
        if lines[j].strip() == "0":
            name = lines[j + 1].strip()
            if name == "ENDSEC":
                return
            if name in ("LINE", "CIRCLE", "ARC"):
                k = j + 2
                vals = {}
                while k < len(lines) - 1 and lines[k].strip() != "0":
                    vals.setdefault(lines[k].strip(), []).append(lines[k + 1].strip())
                    k += 2
                yield name, vals
        j += 1


def convert(path, out_svg):
    parts = []
    xs, ys = [], []

    def f(vals, code):
        return float(vals[code][0])

    for name, vals in entities(path):
        if name == "LINE":
            x1, y1, x2, y2 = f(vals, "10"), f(vals, "20"), f(vals, "11"), f(vals, "21")
            parts.append(("line", (x1, y1, x2, y2)))
            xs += [x1, x2]; ys += [y1, y2]
        elif name == "CIRCLE":
            cx, cy, r = f(vals, "10"), f(vals, "20"), f(vals, "40")
            parts.append(("circle", (cx, cy, r)))
            xs += [cx - r, cx + r]; ys += [cy - r, cy + r]
        elif name == "ARC":
            cx, cy, r = f(vals, "10"), f(vals, "20"), f(vals, "40")
            a1, a2 = f(vals, "50"), f(vals, "51")  # degrees, CCW
            parts.append(("arc", (cx, cy, r, a1, a2)))
            # bound by the arc's endpoints + axis crossings inside the sweep
            angs = [a1, a2]
            a = math.ceil(a1 / 90) * 90
            sweep_end = a2 if a2 > a1 else a2 + 360
            while a <= sweep_end:
                angs.append(a)
                a += 90
            for ang in angs:
                xs.append(cx + r * math.cos(math.radians(ang)))
                ys.append(cy + r * math.sin(math.radians(ang)))

    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    w, h = maxx - minx, maxy - miny
    pad = 0.03 * max(w, h)

    # DXF y is up, SVG y is down — flip via  y -> (maxy - y)
    def X(x):
        return x - minx + pad

    def Y(y):
        return maxy - y + pad

    el = []
    for kind, geo in parts:
        if kind == "line":
            x1, y1, x2, y2 = geo
            el.append(f'<line x1="{X(x1):.2f}" y1="{Y(y1):.2f}" x2="{X(x2):.2f}" y2="{Y(y2):.2f}"/>')
        elif kind == "circle":
            cx, cy, r = geo
            el.append(f'<circle cx="{X(cx):.2f}" cy="{Y(cy):.2f}" r="{r:.2f}"/>')
        else:
            cx, cy, r, a1, a2 = geo
            sweep = (a2 - a1) % 360
            x1 = cx + r * math.cos(math.radians(a1)); y1 = cy + r * math.sin(math.radians(a1))
            x2 = cx + r * math.cos(math.radians(a2)); y2 = cy + r * math.sin(math.radians(a2))
            large = 1 if sweep > 180 else 0
            # CCW in DXF becomes sweep-flag 0 after the y-flip
            el.append(f'<path d="M {X(x1):.2f} {Y(y1):.2f} A {r:.2f} {r:.2f} 0 {large} 0 {X(x2):.2f} {Y(y2):.2f}"/>')

    vb_w, vb_h = w + 2 * pad, h + 2 * pad
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vb_w:.2f} {vb_h:.2f}">'
        f'<g fill="none" stroke="{STROKE}" stroke-width="{STROKE_W}" stroke-linecap="round">'
        + "".join(el)
        + "</g></svg>"
    )
    open(out_svg, "w").write(svg)
    return w, h


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for fn in sorted(os.listdir(DXF_DIR)):
        if not fn.endswith(".dxf"):
            continue
        out = os.path.join(OUT_DIR, fn[:-4] + ".svg")
        w, h = convert(os.path.join(DXF_DIR, fn), out)
        print(f"  {fn:<26} {w:7.1f} x {h:7.1f} mm  -> {os.path.relpath(out, REPO)}")


if __name__ == "__main__":
    main()
