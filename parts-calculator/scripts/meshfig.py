"""A tiny offscreen renderer, so a mesh problem can be shown rather than described.

There is no GL context on a build box and none is wanted: this rasterises
triangles with numpy and a z-buffer, which is enough for a flat-shaded part at
any zoom, and it draws chosen edges on top so a defect measured in hundredths
of a millimetre is visible at all. Used by mesh_report.py and mesh_repair.py.

Backfaces are painted a dark red rather than culled, so looking through a hole
in a surface reads as a hole instead of as background.
"""
import numpy as np
from PIL import Image, ImageDraw, ImageFont

SS = 2                                    # supersample, downscaled at the end
BG = (0.09, 0.10, 0.115)
GREY = np.array([0.74, 0.765, 0.80])      # the part
PALE = np.array([0.90, 0.91, 0.93])       # the part, under a wireframe
INSIDE = np.array([0.30, 0.13, 0.15])     # backfaces: you are seeing through something
HOT = np.array([0.93, 0.17, 0.17])
LIGHT = np.array([-0.35, 0.45, 1.0])

FONTS = ("/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf")
MONO = ("/System/Library/Fonts/SFNSMono.ttf", "/System/Library/Fonts/Menlo.ttc")


def font(size, mono=False):
    for path in (MONO if mono else FONTS):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


def basis(direction, up=(0, 0, 1)):
    """Camera frame looking down `direction` at the subject, roughly z-up."""
    z = np.asarray(direction, float)
    z = z / np.linalg.norm(z)
    up = np.array(up, float)
    if abs(z @ up) > 0.95:
        up = np.array([0.0, 1.0, 0.0])
    x = np.cross(up, z)
    x /= np.linalg.norm(x)
    return np.stack([x, np.cross(z, x), z], axis=1)


def render(mesh, hot, cam, w, h, centre, span, surface=GREY):
    """Flat-shaded orthographic render. `hot` is a per-face bool, painted HOT.

    Returns the float image and a projector from world points to pixels.
    """
    verts = mesh.vertices @ cam
    ctr = np.asarray(centre, float) @ cam
    scale = min(w, h) / span
    px = np.stack([(verts[:, 0] - ctr[0]) * scale + w / 2,
                   h / 2 - (verts[:, 1] - ctr[1]) * scale,
                   verts[:, 2]], axis=1)
    normals = mesh.face_normals @ cam
    light = LIGHT / np.linalg.norm(LIGHT)
    front = normals[:, 2] > 0
    lam = np.clip(np.where(front[:, None], normals, -normals) @ light, 0, 1)
    shade = 0.32 + 0.68 * lam ** 0.85
    base = np.where(hot[:, None], HOT, np.where(front[:, None], surface, INSIDE))
    colour = np.clip(base * shade[:, None], 0, 1)

    img = np.ones((h, w, 3), np.float32) * np.array(BG, np.float32)
    zbuf = np.full((h, w), -1e30, np.float32)
    tris = px[mesh.faces]
    for i in np.argsort(hot.astype(int)):        # hot faces last, so ties go to them
        t = tris[i]
        x0, x1 = max(int(t[:, 0].min()), 0), min(int(t[:, 0].max()) + 2, w)
        y0, y1 = max(int(t[:, 1].min()), 0), min(int(t[:, 1].max()) + 2, h)
        if x1 <= x0 or y1 <= y0:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
        (ax, ay), (bx, by), (cx, cy) = t[0, :2], t[1, :2], t[2, :2]
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1e-12:
            continue
        w0 = ((by - cy) * (gx - cx) + (cx - bx) * (gy - cy)) / den
        w1 = ((cy - ay) * (gx - cx) + (ax - cx) * (gy - cy)) / den
        w2 = 1 - w0 - w1
        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not inside.any():
            continue
        z = w0 * t[0, 2] + w1 * t[1, 2] + w2 * t[2, 2]
        sub = zbuf[y0:y1, x0:x1]
        win = inside & (z > sub)
        if not win.any():
            continue
        sub[win] = z[win]
        img[y0:y1, x0:x1][win] = colour[i]

    def project(points):
        p = np.atleast_2d(np.asarray(points, float)) @ cam
        return (p[:, :2] - ctr[:2]) * np.array([scale, -scale]) + np.array([w / 2, h / 2])

    return img, project


class Panel:
    """One rendered view, sized in final (not supersampled) pixels."""

    def __init__(self, mesh, cam, centre, span, size, hot=None, wireframe=False):
        self.mesh, self.size = mesh, size
        w, h = size[0] * SS, size[1] * SS
        hot = np.zeros(len(mesh.faces), bool) if hot is None else hot
        img, self.project = render(mesh, hot, cam, w, h, centre, span,
                                   surface=PALE if wireframe else GREY)
        self.im = Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8)).convert("RGBA")
        self.overlay = Image.new("RGBA", self.im.size, (0, 0, 0, 0))
        self.draw = ImageDraw.Draw(self.overlay)
        if wireframe:
            self.wireframe()

    def wireframe(self, colour=(88, 98, 114, 150), width=3):
        """Every triangle, drawn over the surface, so nothing hides behind geometry."""
        p = self.project(self.mesh.vertices)
        w, h = self.im.size
        on = (p[:, 0] > -w) & (p[:, 0] < 2 * w) & (p[:, 1] > -h) & (p[:, 1] < 2 * h)
        for a, b in self.mesh.edges_unique:
            if on[a] or on[b]:
                self.draw.line([*p[a], *p[b]], fill=colour, width=width)

    def edges(self, edges, colour, width=8):
        if edges is None or not len(edges):
            return self
        p = self.project(self.mesh.vertices)
        for a, b in edges:
            self.draw.line([*p[a], *p[b]], fill=colour, width=width)
        return self

    def ring(self, point, radius_frac=0.055, colour=(255, 78, 78), label=None):
        x, y = self.project(point)[0]
        r = radius_frac * self.im.size[0]
        self.draw.ellipse([x - r, y - r, x + r, y + r], outline=colour, width=6)
        if label:
            self.draw.text((x + r + 12, y - r - 10), label,
                           font=font(int(1.4 * r)), fill=colour)
        return self

    def finish(self, caption):
        im = Image.alpha_composite(self.im, self.overlay).convert("RGB")
        im = im.resize(self.size, Image.LANCZOS)
        d = ImageDraw.Draw(im)
        f = font(max(14, self.size[0] // 37), mono=True)
        w = d.textlength(caption, font=f)
        pad, bottom = self.size[0] // 66, self.size[1]
        d.rectangle([pad, bottom - 3 * pad, pad + w + 1.6 * pad, bottom - pad * 0.5], fill=(14, 16, 20))
        d.text((pad * 1.8, bottom - 2.8 * pad), caption, font=f, fill=(200, 208, 220))
        return im


def sheet(path, title, subtitle, panels, cols=2):
    """Lay finished panels out in a grid with a heading, and write a PNG."""
    w, h = panels[0][1].size
    pad, top, cap = 18, 116, 44
    rows = (len(panels) + cols - 1) // cols
    im = Image.new("RGB", (w * cols + pad * (cols + 1), top + rows * (h + cap) + pad - 10), (16, 18, 22))
    d = ImageDraw.Draw(im)
    d.text((pad + 2, 24), title, font=font(46), fill=(238, 241, 246))
    d.text((pad + 2, 76), subtitle, font=font(30, True), fill=(150, 160, 175))
    for i, (caption, panel) in enumerate(panels):
        row, col = divmod(i, cols)
        x, y = pad * (col + 1) + w * col, top + row * (h + cap)
        d.text((x, y + 2), caption, font=font(30, True), fill=(150, 160, 175))
        im.paste(panel, (x, y + cap - 6))
    im.save(path)
    return path
