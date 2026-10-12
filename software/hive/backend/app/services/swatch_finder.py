"""Finds the colour reference palette's swatches in a camera frame and reads each one's colour.

A palette is a strip of LEGO tiles of known colours (white, the greys, black, the primaries) at the edge of the
classification camera's view. This runs the small network that finds them (an ONNX export with a ``hive.*``
metadata block: ``hive.kind`` = "swatch_finder", the colour names in ``hive.colour_names``, their BrickLink ids in
``hive.classes``, the long side it runs at in ``hive.net_long_side``) and reads each tile's colour from the
full-resolution frame. Needs numpy, scipy, Pillow and onnxruntime.

    finder = SwatchFinder("swatch.onnx", threads=1)
    found = finder.find(jpeg_bytes)           # a path, JPEG bytes, a PIL image or an RGB uint8 array
    for s in found.swatches: print(s.colour, s.rgb, s.pixels, s.flags)

One pass of the network over the whole frame shrunk to NET pixels on its long side (a 3840 x 2160 frame runs at
960 x 544, the scale it was trained at): every pixel's chance of being on a tile's flat top face, well inside its
edges, and that tile's colour. Each connected region called top face and one colour is a swatch (two neighbouring
tiles of different colours are two swatches even where blur has closed the gap between them); its reading is the
colour of its pixels in the full-resolution frame (the region shrunk by one network pixel first, so no edge, gap or
side face gets in). A reading is reported with what might make it untrustworthy (flags), never dropped: the caller
decides.

The frame as a whole gets a call: ``found.palette``, the swatches that make up the palette (a chain of neighbouring
swatches, at least PALETTE_SWATCHES of them in at least PALETTE_COLOURS colours), empty when there is none in view.
``found.flags`` are about those swatches only.

Written to be shared as it is between the places frames are (Hive, a sorter, research); the copy here leaves out
the training-side parts (a torch checkpoint, drawing an overlay) and takes the colour names from the model alone.
Apart from that it matches the research finder at commit c45bd29: keep the two the same, so readings compare.
"""

import io
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

NET = 960  # the long side the network runs at
MIN_AREA = 150  # network pixels a region needs to be a swatch: on C4 a tile's readable top face is 450 to 1,500
# (cut off by the frame's edge too), a patch between a loose piece's studs 20 to 400 (2026-10-12, v1a)
MAX_AREA = 0.04  # share of the frame past which a region is not one tile (a 1x8's top face is under 1%)
CLIP = 230  # a channel this bright piled up at one value is the camera saturating (C4's white tops out at 239, not 255)
UNEVEN = 12.0  # standard deviation of lightness (0..255) inside a swatch past which it is flagged uneven
# The neutrals from light to dark: a palette's readings of these must come out in this order of lightness.
NEUTRALS = ["White", "Light Bluish Gray", "Dark Bluish Gray", "Black"]
# A palette is a chain of neighbouring swatches: each within REACH times the larger one's length of the next, at
# least PALETTE_SWATCHES of them in at least PALETTE_COLOURS colours. A loose piece or two is not one.
REACH = 2.5
PALETTE_SWATCHES = 4
PALETTE_COLOURS = 4


@dataclass
class Swatch:
    colour: str  # one of the model's hive.colour_names
    colour_score: float  # the network's mean probability of that colour over the swatch
    surface_score: float  # its mean probability of top face
    pixels: int  # full-resolution pixels read
    rgb: list  # median sRGB, 0..255
    rgb_mean: list
    rgb_std: list
    clipped: float  # share of the pixels with a channel at its ceiling (see _clipped)
    centre: list  # x, y in the full-resolution frame
    box: list  # x0, y0, x1, y1 in the full-resolution frame
    length: float  # its long and short sides in full-resolution pixels (a 1x2 tile's is about twice a 1x1's)
    width: float
    flags: list = field(default_factory=list)  # "clipped" (over a tenth at the ceiling), "uneven", "small", "unsure_colour"


@dataclass
class Found:
    width: int
    height: int
    swatches: list
    flags: list  # about the palette as a whole: "neutrals_out_of_order", "repeated_colour"
    palette: list  # indices of the swatches that make up the palette, in order; empty when there is none
    seconds: dict
    model: str
    masks: list = None  # with find(..., masks=True): each swatch's read pixels, a bool array over its box

    def to_dict(self):
        d = asdict(self)
        d.pop("masks")
        return d


class Net:
    """The network from its ONNX export (onnxruntime, CPU). Returns the surface probability and the colour
    probabilities of every pixel. ``names`` are the colours in the model's output order, "none" first; ``classes``
    their BrickLink colour ids (None for "none")."""

    def __init__(self, path, threads=None):
        import onnxruntime as ort

        self.path = str(path)
        opts = ort.SessionOptions()
        if threads:
            opts.intra_op_num_threads = threads
            opts.inter_op_num_threads = 1
        # Without the arena, what a pass allocates goes back when it ends instead of staying reserved for the life
        # of the process: a long-running server keeps a flat footprint.
        opts.enable_cpu_mem_arena = False
        self.sess = ort.InferenceSession(self.path, opts, providers=["CPUExecutionProvider"])
        self.input = self.sess.get_inputs()[0].name
        meta = self.sess.get_modelmeta().custom_metadata_map or {}
        if "hive.colour_names" not in meta:
            raise ValueError(f"{Path(self.path).name} has no hive.colour_names in its metadata")
        self.names = json.loads(meta["hive.colour_names"])
        try:
            classes = json.loads(meta.get("hive.classes", "null"))
        except ValueError:
            classes = None
        self.classes = classes if isinstance(classes, list) and len(classes) == len(self.names) else [None] * len(self.names)

    def __call__(self, rgb):
        x = (rgb.astype(np.float32) / 255).transpose(2, 0, 1)[None]
        logits = self.sess.run(None, {self.input: x})[0][0]
        surface = 1 / (1 + np.exp(-logits[0]))
        c = logits[1:] - logits[1:].max(0, keepdims=True)
        e = np.exp(c)
        return surface, e / e.sum(0, keepdims=True)

    def bricklink_id(self, colour):
        """The BrickLink colour id of one of the names, if the model carries it."""
        try:
            value = self.classes[self.names.index(colour)]
        except ValueError:
            return None
        return int(value) if isinstance(value, (int, float)) else None


def _open(image):
    """A PIL image from a path, bytes, a PIL image or an array."""
    if isinstance(image, Image.Image):
        return image
    if isinstance(image, np.ndarray):
        return Image.fromarray(image)
    if isinstance(image, (bytes, bytearray)):
        return Image.open(io.BytesIO(image))
    return Image.open(image)


def _net_size(w, h):
    s = NET / max(w, h)
    return max(32, round(w * s / 32) * 32), max(32, round(h * s / 32) * 32)


class SwatchFinder:
    def __init__(self, model, threads=None):
        self.net = Net(model, threads)

    def find(self, image, masks=False):
        t0 = time.perf_counter()
        im = _open(image)
        w, h = im.size
        nw, nh = _net_size(w, h)
        small = _open(image) if not isinstance(image, Image.Image) else im.copy()
        if small.format == "JPEG":
            small.draft("RGB", (nw, nh))  # decode at a fraction of the size: a 4K frame's JPEG in a quarter the time
        small = np.asarray(small.convert("RGB").resize((nw, nh), Image.BILINEAR))
        full = np.asarray(im.convert("RGB"))
        t1 = time.perf_counter()
        surface, colours = self.net(small)
        t2 = time.perf_counter()
        sx, sy = w / nw, h / nh
        called = surface > 0.5
        best = colours.argmax(0)
        read = []
        for c in np.unique(best[called]):
            regions, _ = ndimage.label(called & (best == c))
            for k, sl in enumerate(ndimage.find_objects(regions), start=1):
                if sl is None:
                    continue
                region = regions[sl] == k
                if MIN_AREA <= region.sum() <= MAX_AREA * surface.size:
                    read.append(self._read(full, region, sl, surface, colours, sx, sy))
        order = _in_order([s for s, _ in read])
        swatches = [read[i][0] for i in order]
        t3 = time.perf_counter()
        palette = _palette(swatches)
        return Found(width=w, height=h, swatches=swatches, flags=_palette_flags([swatches[i] for i in palette]),
                     palette=palette, model=Path(self.net.path).name,
                     seconds=dict(decode=round(t1 - t0, 4), network=round(t2 - t1, 4), read=round(t3 - t2, 4)),
                     masks=[read[i][1] for i in order] if masks else None)

    def _read(self, full, region, sl, surface, colours, sx, sy):
        flags = []
        mean = colours[:, sl[0], sl[1]][:, region].mean(1)
        c = int(mean.argmax())
        colour = self.net.names[c + 1]
        if mean[c] < 0.6:
            flags.append("unsure_colour")
        core = ndimage.binary_erosion(region, iterations=1)
        if core.sum() < 0.3 * region.sum():
            flags.append("small")
            core = region
        # The core, in full-resolution pixels: each network pixel is sx by sy of them.
        y0, x0 = int(round(sl[0].start * sy)), int(round(sl[1].start * sx))
        y1, x1 = int(round(sl[0].stop * sy)), int(round(sl[1].stop * sx))
        y1, x1 = min(y1, full.shape[0]), min(x1, full.shape[1])
        yy = ((np.arange(y0, y1) + 0.5) / sy - sl[0].start).astype(int).clip(0, core.shape[0] - 1)
        xx = ((np.arange(x0, x1) + 0.5) / sx - sl[1].start).astype(int).clip(0, core.shape[1] - 1)
        mask = core[yy[:, None], xx[None, :]]
        px = full[y0:y1, x0:x1][mask].astype(np.float32)
        ys, xs = np.nonzero(mask)
        rgb = np.median(px, 0)
        luma = px @ np.array([0.299, 0.587, 0.114], np.float32)
        clipped = _clipped(px)
        if clipped > 0.1:
            flags.append("clipped")
        if luma.std() > UNEVEN:
            flags.append("uneven")
        pts = np.stack([xs, ys], 1).astype(np.float64)
        ev = np.linalg.eigvalsh(np.cov(pts.T)) if len(pts) > 2 else np.zeros(2)
        width, length = (np.sqrt(np.maximum(ev, 0)) * np.sqrt(12)).tolist()  # a uniform rectangle's sides
        return Swatch(colour=colour, colour_score=round(float(mean[c]), 3),
                      surface_score=round(float(surface[sl][region].mean()), 3), pixels=int(len(px)),
                      rgb=[round(float(v), 1) for v in rgb], rgb_mean=[round(float(v), 1) for v in px.mean(0)],
                      rgb_std=[round(float(v), 1) for v in px.std(0)], clipped=round(clipped, 4),
                      centre=[round(x0 + xs.mean(), 1), round(y0 + ys.mean(), 1)], box=[x0, y0, x1, y1],
                      length=round(length, 1), width=round(width, 1), flags=flags), mask


def _clipped(px):
    """The share of pixels with a channel at the camera's ceiling. A camera need not saturate at 255 (C4's white
    reads a flat 239 over a whole tile), so a ceiling is a bright value (CLIP or more) that many pixels share
    exactly, where a real colour spreads over several levels."""
    at = np.zeros(len(px), bool)
    for c in range(3):
        top = px[:, c].max()
        if top >= CLIP:
            ceiling = px[:, c] >= top - 1
            if ceiling.mean() > 0.1 or top >= 254:
                at |= ceiling
    return round(float(at.mean()), 4)


def _in_order(swatches):
    """The order the swatches sit in along the palette (its longest direction), so readings line up frame to frame:
    indices into `swatches`."""
    if len(swatches) < 2:
        return list(range(len(swatches)))
    c = np.array([s.centre for s in swatches])
    axis = np.linalg.eigh(np.cov((c - c.mean(0)).T))[1][:, -1]
    if abs(axis[1]) >= abs(axis[0]):
        axis = axis * np.sign(axis[1])  # top to bottom
    else:
        axis = axis * np.sign(axis[0])  # left to right
    return [int(i) for i in np.argsort((c - c.mean(0)) @ axis)]


def _palette(swatches):
    """The largest chain of neighbouring swatches, if it is a palette (REACH, PALETTE_SWATCHES, PALETTE_COLOURS):
    its swatches' indices in order, else []. Swatches the network is unsure of the colour of don't count."""
    sure = [i for i, s in enumerate(swatches) if "unsure_colour" not in s.flags]
    group = {i: i for i in sure}

    def root(i):
        while group[i] != i:
            group[i] = group[group[i]]
            i = group[i]
        return i

    for a in sure:
        for b in sure:
            if a < b:
                sa, sb = swatches[a], swatches[b]
                if np.hypot(sa.centre[0] - sb.centre[0], sa.centre[1] - sb.centre[1]) <= REACH * max(sa.length, sb.length):
                    group[root(a)] = root(b)
    chains = {}
    for i in sure:
        chains.setdefault(root(i), []).append(i)
    best = max(chains.values(), key=len, default=[])
    if len(best) < PALETTE_SWATCHES or len({swatches[i].colour for i in best}) < PALETTE_COLOURS:
        return []
    return sorted(best)


def _palette_flags(swatches):
    flags = []
    names = [s.colour for s in swatches]
    if len(set(names)) < len(names):
        flags.append("repeated_colour")
    luma = {s.colour: float(np.dot(s.rgb, [0.299, 0.587, 0.114])) for s in swatches if s.colour in NEUTRALS}
    seen = [luma[n] for n in NEUTRALS if n in luma]
    if any(a <= b for a, b in zip(seen, seen[1:])):
        flags.append("neutrals_out_of_order")
    return flags
