import os, struct, sys, glob
import numpy as np


def stl_vertices(path):
    with open(path, 'rb') as f:
        f.read(80)
        n = struct.unpack('<I', f.read(4))[0]
        is_ascii = False
        if n == 0 or n > 10_000_000:
            with open(path, 'rb') as g:
                start = g.read(256)
            if b'solid' in start[:6] and b'facet' in start:
                is_ascii = True
        verts = []
        if not is_ascii:
            for _ in range(n):
                data = f.read(50)
                if len(data) < 50:
                    break
                for i in range(3):
                    x, y, z = struct.unpack('<fff', data[12 + i*12 : 12 + (i+1)*12])
                    verts.append((x, y, z))
        else:
            with open(path, 'r', errors='ignore') as g:
                for line in g:
                    line = line.strip()
                    if line.startswith('vertex'):
                        parts = line.split()
                        verts.append((float(parts[1]), float(parts[2]), float(parts[3])))
        return np.array(verts, dtype=np.float64)


def aabb_dims(V):
    return (V.max(0) - V.min(0)).tolist()


def obb_dims(V):
    c = V.mean(0)
    X = V - c
    cov = np.cov(X.T)
    _, evecs = np.linalg.eigh(cov)
    evecs = evecs[:, ::-1]
    proj = X @ evecs
    return (proj.max(0) - proj.min(0)).tolist()


def bom_name_from_stl(path):
    # "0000_Main - top_beam.stl" -> "top_beam"
    # "Assembly 1 - spoke.stl"   -> "spoke"
    base = os.path.basename(path).replace('.stl', '')
    return base.split(' - ')[-1].strip()


def measure_dir(stl_dir):
    rows = []
    for p in sorted(glob.glob(os.path.join(stl_dir, '**', '*.stl'), recursive=True)):
        try:
            V = stl_vertices(p)
            if len(V) == 0:
                continue
            rows.append((p, aabb_dims(V), obb_dims(V)))
        except Exception as e:
            print('err', p, e, file=sys.stderr)
    return rows


def main():
    root = os.path.dirname(os.path.abspath(__file__))
    stl_dir = os.path.join(root, 'stl-downloads')
    rows = measure_dir(stl_dir)
    if not rows:
        print(f"no STLs found under {stl_dir}", file=sys.stderr)
        sys.exit(1)
    rows.sort(key=lambda r: -r[2][0])
    print(f"{'name':60s}  {'aabb_max':>9s}  {'obb_L':>8s} {'obb_W':>8s} {'obb_H':>8s}  {'L/W':>5s}")
    for p, aabb, obb in rows:
        name = os.path.basename(p).replace('.stl', '')
        aabb_max = max(aabb)
        ratio = obb[0] / obb[1] if obb[1] > 0 else 0
        print(f"{name[:60]:60s}  {aabb_max:9.2f}  {obb[0]:8.2f} {obb[1]:8.2f} {obb[2]:8.2f}  {ratio:5.2f}")


if __name__ == '__main__':
    main()
