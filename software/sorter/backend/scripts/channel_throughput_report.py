#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import math
import time
from pathlib import Path
from typing import Any, Sequence

import requests

BASE = "http://127.0.0.1:8000"
OUT_ROOT = (
    Path(__file__).resolve().parent.parent / "blob" / "channel_throughput_report"
)

CHANNEL_LABELS = {
    "c_channel_2": "C-Channel 2",
    "c_channel_3": "C-Channel 3",
    "classification_channel": "Classification Channel",
}

CHANNEL_SHORT = {
    "c_channel_2": "C2",
    "c_channel_3": "C3",
    "classification_channel": "C4",
}

OUTCOME_LABELS = {
    "classified_success": "Classified",
    "distributed_success": "Distributed",
    "unknown": "Unknown",
    "multi_drop_fail": "Multi-Drop",
    "not_found": "Not Found",
}

# Fixed CSS var names for colours — referenced by SVG fill/stroke.
CHANNEL_COLOR_VAR = {
    "c_channel_2": "--c2",
    "c_channel_3": "--c3",
    "classification_channel": "--c4",
}

OUTCOME_COLOR_VAR = {
    "distributed_success": "--oc-distributed",
    "classified_success": "--oc-classified",
    "unknown": "--oc-unknown",
    "multi_drop_fail": "--oc-multi",
    "not_found": "--oc-notfound",
}


# ---------------------------------------------------------------------------
# Network / IO (unchanged surface)
# ---------------------------------------------------------------------------


def _channel_metrics_source(run_payload: dict[str, Any]) -> dict[str, Any]:
    summary = run_payload.get("summary")
    if isinstance(summary, dict):
        channel_metrics = summary.get("channel_throughput")
        if isinstance(channel_metrics, dict):
            return channel_metrics
    snapshot = run_payload.get("snapshot")
    if isinstance(snapshot, dict):
        channel_metrics = snapshot.get("channel_throughput")
        if isinstance(channel_metrics, dict):
            return channel_metrics
    end_snapshot = run_payload.get("end_snapshot")
    if isinstance(end_snapshot, dict):
        channel_metrics = end_snapshot.get("channel_throughput")
        if isinstance(channel_metrics, dict):
            return channel_metrics
    return {}


def _fmt_num(value: Any, digits: int = 1) -> str:
    if isinstance(value, (int, float)) and not (isinstance(value, float) and math.isnan(value)):
        return f"{float(value):.{digits}f}"
    return "-"


def _fmt_count(value: Any) -> str:
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return "-"


def _load_runtime_stats(base_url: str) -> dict[str, Any]:
    response = requests.get(f"{base_url.rstrip('/')}/runtime-stats", timeout=15)
    response.raise_for_status()
    payload = response.json().get("payload")
    if not isinstance(payload, dict):
        raise RuntimeError("runtime-stats response did not contain a payload object")
    return payload


def _run_payload(args: argparse.Namespace, snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "captured_at": time.time(),
        "label": args.label,
        "strategy": args.strategy,
        "changes": args.changes,
        "note": args.note,
        "snapshot": snapshot,
    }


def _write_run(out_root: Path, run_payload: dict[str, Any]) -> Path:
    captured_at = float(run_payload["captured_at"])
    run_id = time.strftime("run_%Y%m%d_%H%M%S", time.localtime(captured_at))
    run_dir = out_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(json.dumps(run_payload, indent=2), encoding="utf-8")
    return run_dir


def _load_runs(out_root: Path) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    if not out_root.exists():
        return runs
    for run_json in sorted(out_root.glob("run_*/run.json")):
        try:
            payload = json.loads(run_json.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        payload["_path"] = str(run_json)
        runs.append(payload)
    runs.sort(key=lambda item: float(item.get("captured_at") or 0.0), reverse=True)
    return runs


# ---------------------------------------------------------------------------
# Time-series derivation
# ---------------------------------------------------------------------------


def _samples(run: dict[str, Any]) -> list[dict[str, Any]]:
    samples = run.get("samples")
    return samples if isinstance(samples, list) else []


def _extract_timeseries(run: dict[str, Any]) -> dict[str, Any]:
    samples = _samples(run)
    if not samples:
        return {"elapsed_s": []}
    start_ts = float(samples[0].get("captured_at") or 0.0)
    elapsed: list[float] = []
    exits: dict[str, list[int]] = {k: [] for k in CHANNEL_LABELS}
    active: dict[str, list[float]] = {k: [] for k in CHANNEL_LABELS}
    outcomes_cum: dict[str, list[int]] = {k: [] for k in OUTCOME_LABELS}

    for sample in samples:
        ts = float(sample.get("captured_at") or start_ts)
        elapsed.append(max(0.0, ts - start_ts))
        ct = sample.get("channel_throughput") or {}
        for ch_key in CHANNEL_LABELS:
            d = ct.get(ch_key) or {}
            exits[ch_key].append(int(d.get("exit_count") or 0))
            active[ch_key].append(float(d.get("active_time_s") or 0.0))
        c4 = ct.get("classification_channel") or {}
        oc = c4.get("outcomes") or {}
        for outcome_key in OUTCOME_LABELS:
            d = oc.get(outcome_key) or {}
            outcomes_cum[outcome_key].append(int(d.get("count") or 0))

    return {
        "elapsed_s": elapsed,
        "exits": exits,
        "active_s": active,
        "outcomes_cum": outcomes_cum,
    }


def _rolling_active_ppm(cum_exits: Sequence[int], active_s: Sequence[float], elapsed_s: Sequence[float], window_s: float = 30.0) -> list[float | None]:
    out: list[float | None] = []
    n = len(elapsed_s)
    for i in range(n):
        t_now = elapsed_s[i]
        # find earliest sample j with elapsed >= t_now - window
        target = t_now - window_s
        j = i
        while j > 0 and elapsed_s[j - 1] >= target:
            j -= 1
        d_exits = cum_exits[i] - cum_exits[j]
        d_active = active_s[i] - active_s[j]
        if d_active > 0.05 and d_exits > 0:
            out.append((d_exits * 60.0) / d_active)
        else:
            out.append(None)
    return out


# ---------------------------------------------------------------------------
# SVG primitives
# ---------------------------------------------------------------------------


def _nice_ticks(lo: float, hi: float, count: int = 5) -> list[float]:
    if hi <= lo:
        hi = lo + 1.0
    span = hi - lo
    raw = span / max(1, count)
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1.0
    for m in (1, 2, 2.5, 5, 10):
        step = m * mag
        if step >= raw:
            break
    ticks: list[float] = []
    t = math.floor(lo / step) * step
    while t <= hi + 1e-9:
        if t >= lo - 1e-9:
            ticks.append(round(t, 6))
        t += step
    if not ticks:
        ticks = [lo, hi]
    return ticks


def _scale_linear(value: float, d0: float, d1: float, r0: float, r1: float) -> float:
    if d1 == d0:
        return r0
    return r0 + (value - d0) * (r1 - r0) / (d1 - d0)


def _fmt_axis(value: float) -> str:
    if value == 0:
        return "0"
    absv = abs(value)
    if absv >= 100:
        return f"{value:.0f}"
    if absv >= 10:
        return f"{value:.0f}"
    if absv >= 1:
        return f"{value:.1f}"
    return f"{value:.2f}"


def _fmt_time(seconds: float) -> str:
    if seconds >= 60:
        return f"{int(seconds//60)}:{int(seconds%60):02d}"
    return f"{seconds:.0f}s"


def _svg_line_chart(
    series: list[dict[str, Any]],
    x_max: float,
    y_max: float,
    *,
    width: int = 760,
    height: int = 240,
    x_label: str = "elapsed (s)",
    y_label: str = "",
    title: str = "",
) -> str:
    if not series or x_max <= 0 or y_max <= 0:
        return '<div class="chart-empty">No time series available.</div>'
    pad_l, pad_r, pad_t, pad_b = 48, 16, 24, 32
    inner_w = width - pad_l - pad_r
    inner_h = height - pad_t - pad_b
    x_ticks = _nice_ticks(0, x_max, 5)
    y_ticks = _nice_ticks(0, y_max, 4)
    x_hi = max(x_ticks[-1], x_max)
    y_hi = max(y_ticks[-1], y_max)

    parts: list[str] = []
    parts.append(f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title or y_label)}">')
    if title:
        parts.append(f'<text class="chart-title" x="{pad_l}" y="14">{html.escape(title)}</text>')

    # gridlines + y labels
    for t in y_ticks:
        y = pad_t + inner_h - _scale_linear(t, 0, y_hi, 0, inner_h)
        parts.append(f'<line class="grid" x1="{pad_l}" x2="{pad_l + inner_w}" y1="{y:.1f}" y2="{y:.1f}"/>')
        parts.append(f'<text class="axis" x="{pad_l - 6}" y="{y + 3.5:.1f}" text-anchor="end">{_fmt_axis(t)}</text>')
    # x labels
    for t in x_ticks:
        x = pad_l + _scale_linear(t, 0, x_hi, 0, inner_w)
        parts.append(f'<line class="grid grid-v" x1="{x:.1f}" x2="{x:.1f}" y1="{pad_t}" y2="{pad_t + inner_h}"/>')
        parts.append(f'<text class="axis" x="{x:.1f}" y="{pad_t + inner_h + 14}" text-anchor="middle">{_fmt_time(t)}</text>')

    if y_label:
        parts.append(f'<text class="axis-label" transform="translate(12,{pad_t + inner_h / 2}) rotate(-90)" text-anchor="middle">{html.escape(y_label)}</text>')

    # series
    for s in series:
        xs: Sequence[float] = s["xs"]
        ys: Sequence[float | None] = s["ys"]
        colour_var = s.get("color_var", "--ink")
        dashed = s.get("dashed", False)
        pts: list[str] = []
        for x, y in zip(xs, ys):
            if y is None:
                if pts:
                    parts.append(_polyline(pts, colour_var, dashed))
                    pts = []
                continue
            px = pad_l + _scale_linear(x, 0, x_hi, 0, inner_w)
            py = pad_t + inner_h - _scale_linear(y, 0, y_hi, 0, inner_h)
            pts.append(f"{px:.1f},{py:.1f}")
        if pts:
            parts.append(_polyline(pts, colour_var, dashed))

    # axes
    parts.append(f'<line class="axis-line" x1="{pad_l}" x2="{pad_l}" y1="{pad_t}" y2="{pad_t + inner_h}"/>')
    parts.append(f'<line class="axis-line" x1="{pad_l}" x2="{pad_l + inner_w}" y1="{pad_t + inner_h}" y2="{pad_t + inner_h}"/>')
    parts.append("</svg>")
    return "".join(parts)


def _polyline(points: list[str], colour_var: str, dashed: bool) -> str:
    dash = ' stroke-dasharray="3 3"' if dashed else ""
    return f'<polyline fill="none" stroke="var({colour_var})" stroke-width="1.8"{dash} points="{" ".join(points)}"/>'


def _svg_stacked_area(
    xs: Sequence[float],
    series: list[dict[str, Any]],
    *,
    width: int = 760,
    height: int = 240,
    title: str = "",
    y_label: str = "",
) -> str:
    if not xs or not series:
        return '<div class="chart-empty">No time series available.</div>'
    pad_l, pad_r, pad_t, pad_b = 48, 16, 24, 32
    inner_w = width - pad_l - pad_r
    inner_h = height - pad_t - pad_b

    n = len(xs)
    stacked: list[list[float]] = []
    running = [0.0] * n
    for s in series:
        ys = s["ys"]
        band = []
        for i in range(n):
            running[i] += float(ys[i] or 0)
            band.append(running[i])
        stacked.append(band)
    y_max = max((row[-1] if row else 0) for row in stacked) if stacked else 0
    y_max = max(y_max, max((max(row) if row else 0) for row in stacked))
    y_max = max(y_max, 1)
    x_max = max(xs) if xs else 1
    x_ticks = _nice_ticks(0, x_max, 5)
    y_ticks = _nice_ticks(0, y_max, 4)
    x_hi = max(x_ticks[-1], x_max)
    y_hi = max(y_ticks[-1], y_max)

    parts: list[str] = []
    parts.append(f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">')
    if title:
        parts.append(f'<text class="chart-title" x="{pad_l}" y="14">{html.escape(title)}</text>')
    for t in y_ticks:
        y = pad_t + inner_h - _scale_linear(t, 0, y_hi, 0, inner_h)
        parts.append(f'<line class="grid" x1="{pad_l}" x2="{pad_l + inner_w}" y1="{y:.1f}" y2="{y:.1f}"/>')
        parts.append(f'<text class="axis" x="{pad_l - 6}" y="{y + 3.5:.1f}" text-anchor="end">{_fmt_axis(t)}</text>')
    for t in x_ticks:
        x = pad_l + _scale_linear(t, 0, x_hi, 0, inner_w)
        parts.append(f'<line class="grid grid-v" x1="{x:.1f}" x2="{x:.1f}" y1="{pad_t}" y2="{pad_t + inner_h}"/>')
        parts.append(f'<text class="axis" x="{x:.1f}" y="{pad_t + inner_h + 14}" text-anchor="middle">{_fmt_time(t)}</text>')
    if y_label:
        parts.append(f'<text class="axis-label" transform="translate(12,{pad_t + inner_h / 2}) rotate(-90)" text-anchor="middle">{html.escape(y_label)}</text>')

    # Build polygons from top of stack downward so later (higher) bands overwrite lower ones isn't desirable;
    # instead we iterate bottom-up and draw each as polygon from prev_top to current_top.
    prev = [0.0] * n
    for s, top in zip(series, stacked):
        colour_var = s.get("color_var", "--ink")
        path_forward = []
        for i in range(n):
            px = pad_l + _scale_linear(xs[i], 0, x_hi, 0, inner_w)
            py = pad_t + inner_h - _scale_linear(top[i], 0, y_hi, 0, inner_h)
            path_forward.append(f"{px:.1f},{py:.1f}")
        path_back = []
        for i in range(n - 1, -1, -1):
            px = pad_l + _scale_linear(xs[i], 0, x_hi, 0, inner_w)
            py = pad_t + inner_h - _scale_linear(prev[i], 0, y_hi, 0, inner_h)
            path_back.append(f"{px:.1f},{py:.1f}")
        poly_pts = " ".join(path_forward + path_back)
        parts.append(f'<polygon fill="var({colour_var})" fill-opacity="0.78" stroke="var({colour_var})" stroke-width="0.6" points="{poly_pts}"><title>{html.escape(s.get("label",""))}</title></polygon>')
        prev = list(top)

    parts.append(f'<line class="axis-line" x1="{pad_l}" x2="{pad_l}" y1="{pad_t}" y2="{pad_t + inner_h}"/>')
    parts.append(f'<line class="axis-line" x1="{pad_l}" x2="{pad_l + inner_w}" y1="{pad_t + inner_h}" y2="{pad_t + inner_h}"/>')
    parts.append("</svg>")
    return "".join(parts)


def _svg_grouped_bar(
    run_labels: list[str],
    groups: list[dict[str, Any]],
    *,
    width: int = 860,
    height: int = 260,
    title: str = "",
) -> str:
    if not run_labels or not groups:
        return '<div class="chart-empty">No runs recorded.</div>'
    pad_l, pad_r, pad_t, pad_b = 54, 14, 28, 46
    inner_w = width - pad_l - pad_r
    inner_h = height - pad_t - pad_b

    n_runs = len(run_labels)
    n_g = len(groups)
    slot_w = inner_w / max(1, n_runs)
    bar_w = (slot_w * 0.7) / n_g

    # Each group has its own y-scale (normalise 0..max per group).
    maxes = []
    for g in groups:
        vals = [v for v in g["values"] if isinstance(v, (int, float))]
        maxes.append(max(vals) if vals else 0)
    y_max = max(maxes) if maxes else 1
    # use per-group max normalisation: each bar height is (value / group_max)
    # then display value as title.

    parts: list[str] = []
    parts.append(f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">')
    if title:
        parts.append(f'<text class="chart-title" x="{pad_l}" y="14">{html.escape(title)}</text>')

    # draw 4 horizontal gridlines at 25/50/75/100 %
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = pad_t + inner_h - frac * inner_h
        parts.append(f'<line class="grid" x1="{pad_l}" x2="{pad_l + inner_w}" y1="{y:.1f}" y2="{y:.1f}"/>')
        if frac in (0.0, 1.0):
            parts.append(f'<text class="axis" x="{pad_l - 6}" y="{y + 3.5:.1f}" text-anchor="end">{"0" if frac == 0 else "100%"}</text>')

    for ri, label in enumerate(run_labels):
        slot_x = pad_l + ri * slot_w
        group_start = slot_x + (slot_w - bar_w * n_g) / 2
        for gi, g in enumerate(groups):
            val = g["values"][ri]
            colour_var = g["color_var"]
            g_max = maxes[gi] or 1
            frac = (val / g_max) if isinstance(val, (int, float)) and g_max > 0 else 0
            bar_h = max(0, frac * inner_h)
            bx = group_start + gi * bar_w
            by = pad_t + inner_h - bar_h
            title_txt = f"{g['label']} — {label}: {val}"
            parts.append(
                f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w - 1:.1f}" height="{bar_h:.1f}" '
                f'fill="var({colour_var})" fill-opacity="0.9"><title>{html.escape(title_txt)}</title></rect>'
            )
            if bar_h > 14:
                parts.append(
                    f'<text class="bar-val" x="{bx + bar_w / 2:.1f}" y="{by - 3:.1f}" text-anchor="middle">{_fmt_axis(float(val))}</text>'
                )
        # run label below slot
        parts.append(
            f'<text class="axis" x="{slot_x + slot_w / 2:.1f}" y="{pad_t + inner_h + 14:.1f}" text-anchor="middle">{html.escape(label)}</text>'
        )

    parts.append(f'<line class="axis-line" x1="{pad_l}" x2="{pad_l}" y1="{pad_t}" y2="{pad_t + inner_h}"/>')
    parts.append(f'<line class="axis-line" x1="{pad_l}" x2="{pad_l + inner_w}" y1="{pad_t + inner_h}" y2="{pad_t + inner_h}"/>')
    parts.append("</svg>")
    return "".join(parts)


def _svg_hbar(
    rows: list[dict[str, Any]],
    *,
    width: int = 760,
    row_height: int = 30,
    title: str = "",
) -> str:
    if not rows:
        return '<div class="chart-empty">No channel activity recorded.</div>'
    pad_l, pad_r, pad_t, pad_b = 96, 14, 28, 22
    height = pad_t + pad_b + row_height * len(rows)
    inner_w = width - pad_l - pad_r

    total_max = 0.0
    for r in rows:
        total = sum(seg["value"] for seg in r.get("segments", []))
        total_max = max(total_max, total)
    if total_max <= 0:
        return '<div class="chart-empty">No channel activity recorded.</div>'

    parts: list[str] = []
    parts.append(f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">')
    if title:
        parts.append(f'<text class="chart-title" x="{pad_l}" y="14">{html.escape(title)}</text>')

    for ri, row in enumerate(rows):
        y = pad_t + ri * row_height + 4
        parts.append(
            f'<text class="axis" x="{pad_l - 8}" y="{y + row_height / 2 + 3:.1f}" text-anchor="end">{html.escape(row.get("label", ""))}</text>'
        )
        x = pad_l
        for seg in row["segments"]:
            value = max(0.0, float(seg["value"]))
            w = (value / total_max) * inner_w
            colour_var = seg.get("color_var", "--ink")
            label = seg.get("label", "")
            parts.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{row_height - 10}" '
                f'fill="var({colour_var})" fill-opacity="{seg.get("opacity", 0.85)}">'
                f'<title>{html.escape(f"{label}: {value:.1f}s")}</title></rect>'
            )
            if w > 36:
                parts.append(
                    f'<text class="bar-val" x="{x + w / 2:.1f}" y="{y + row_height / 2 + 2:.1f}" text-anchor="middle">{value:.0f}s</text>'
                )
            x += w
    # scale marker
    parts.append(
        f'<text class="axis" x="{pad_l}" y="{height - 6}" text-anchor="start">0s</text>'
        f'<text class="axis" x="{pad_l + inner_w}" y="{height - 6}" text-anchor="end">{total_max:.0f}s</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def _legend_svg(items: list[tuple[str, str]]) -> str:
    """items = list of (label, css_var)."""
    if not items:
        return ""
    chips = []
    for label, var in items:
        chips.append(
            f'<span class="legend-item"><span class="legend-swatch" style="background:var({var});"></span>{html.escape(label)}</span>'
        )
    return f'<div class="legend">{"".join(chips)}</div>'


# ---------------------------------------------------------------------------
# Chart builders per run
# ---------------------------------------------------------------------------


def _chart_cumulative_exits(ts: dict[str, Any]) -> str:
    elapsed = ts.get("elapsed_s") or []
    exits = ts.get("exits") or {}
    if not elapsed:
        return '<div class="chart-empty">No time series — snapshot-only run.</div>'
    x_max = elapsed[-1] if elapsed else 1
    y_max = 1
    series = []
    for ch_key in ("c_channel_2", "c_channel_3", "classification_channel"):
        ys = exits.get(ch_key) or []
        if not ys:
            continue
        y_max = max(y_max, max(ys))
        series.append({
            "xs": elapsed,
            "ys": ys,
            "color_var": CHANNEL_COLOR_VAR[ch_key],
            "label": CHANNEL_SHORT[ch_key],
        })
    legend = _legend_svg([(CHANNEL_SHORT[k], CHANNEL_COLOR_VAR[k]) for k in ("c_channel_2", "c_channel_3", "classification_channel")])
    chart = _svg_line_chart(series, x_max, y_max, title="Cumulative exits per channel", y_label="pieces")
    return f'<div class="chart-wrap">{legend}{chart}</div>'


def _chart_outcomes_stacked(ts: dict[str, Any]) -> str:
    elapsed = ts.get("elapsed_s") or []
    outcomes = ts.get("outcomes_cum") or {}
    if not elapsed:
        return '<div class="chart-empty">No time series — snapshot-only run.</div>'
    # Order: distributed_success > classified_success > unknown > multi_drop_fail > not_found
    order = ("distributed_success", "classified_success", "unknown", "multi_drop_fail", "not_found")
    series = []
    present = []
    for key in order:
        ys = outcomes.get(key) or []
        if not ys or all(v == 0 for v in ys):
            continue
        series.append({
            "ys": ys,
            "color_var": OUTCOME_COLOR_VAR[key],
            "label": OUTCOME_LABELS[key],
        })
        present.append((OUTCOME_LABELS[key], OUTCOME_COLOR_VAR[key]))
    if not series:
        return '<div class="chart-empty">No classification outcomes yet.</div>'
    legend = _legend_svg(present)
    chart = _svg_stacked_area(elapsed, series, title="C4 outcomes (cumulative stacked)", y_label="pieces")
    return f'<div class="chart-wrap">{legend}{chart}</div>'


def _chart_rolling_active_ppm(ts: dict[str, Any]) -> str:
    elapsed = ts.get("elapsed_s") or []
    exits = ts.get("exits") or {}
    active = ts.get("active_s") or []
    if not elapsed:
        return '<div class="chart-empty">No time series — snapshot-only run.</div>'
    series = []
    y_max = 1.0
    for ch_key in ("c_channel_2", "c_channel_3", "classification_channel"):
        cum = exits.get(ch_key) or []
        act = active.get(ch_key) if isinstance(active, dict) else None
        if not cum or not act:
            continue
        ppm = _rolling_active_ppm(cum, act, elapsed, window_s=30.0)
        for v in ppm:
            if isinstance(v, (int, float)):
                y_max = max(y_max, v)
        series.append({
            "xs": elapsed,
            "ys": ppm,
            "color_var": CHANNEL_COLOR_VAR[ch_key],
            "label": CHANNEL_SHORT[ch_key],
        })
    # Faint raw overall-PPM: cumulative_exits * 60 / elapsed
    for ch_key in ("c_channel_2", "c_channel_3", "classification_channel"):
        cum = exits.get(ch_key) or []
        if not cum:
            continue
        ys = []
        for i, t in enumerate(elapsed):
            if t > 5.0:
                ys.append((cum[i] * 60.0) / t)
            else:
                ys.append(None)
        for v in ys:
            if isinstance(v, (int, float)):
                y_max = max(y_max, v)
        series.append({
            "xs": elapsed,
            "ys": ys,
            "color_var": CHANNEL_COLOR_VAR[ch_key],
            "dashed": True,
            "label": f"{CHANNEL_SHORT[ch_key]} overall",
        })
    legend_items = [(CHANNEL_SHORT[k] + " (30s active)", CHANNEL_COLOR_VAR[k]) for k in ("c_channel_2", "c_channel_3", "classification_channel")]
    legend_items.append(("overall (dashed)", "--muted"))
    legend = _legend_svg(legend_items)
    chart = _svg_line_chart(series, elapsed[-1] if elapsed else 1, y_max * 1.1, title="Rolling active-PPM (30s window)", y_label="ppm")
    return f'<div class="chart-wrap">{legend}{chart}</div>'


def _chart_active_waiting(run: dict[str, Any]) -> str:
    ct = _channel_metrics_source(run)
    rows = []
    for ch_key in ("c_channel_2", "c_channel_3", "classification_channel"):
        d = ct.get(ch_key) or {}
        active = float(d.get("active_time_s") or 0)
        waiting = float(d.get("waiting_time_s") or 0)
        if active <= 0 and waiting <= 0:
            continue
        rows.append({
            "label": CHANNEL_SHORT[ch_key],
            "segments": [
                {"label": f"{CHANNEL_SHORT[ch_key]} active", "value": active, "color_var": CHANNEL_COLOR_VAR[ch_key], "opacity": 0.9},
                {"label": f"{CHANNEL_SHORT[ch_key]} waiting", "value": waiting, "color_var": CHANNEL_COLOR_VAR[ch_key], "opacity": 0.35},
            ],
        })
    legend = _legend_svg([("active", "--ink"), ("waiting (faded)", "--muted")])
    chart = _svg_hbar(rows, title="Active vs waiting time")
    return f'<div class="chart-wrap">{legend}{chart}</div>'


# ---------------------------------------------------------------------------
# Cross-run aggregation
# ---------------------------------------------------------------------------


def _leaderboard_entry(run: dict[str, Any]) -> dict[str, Any]:
    ct = _channel_metrics_source(run)
    c4 = ct.get("classification_channel") or {}
    outcomes = c4.get("outcomes") or {}
    distributed = int((outcomes.get("distributed_success") or {}).get("count") or 0)
    classified = int((outcomes.get("classified_success") or {}).get("count") or 0)
    multi = int((outcomes.get("multi_drop_fail") or {}).get("count") or 0)
    not_found = int((outcomes.get("not_found") or {}).get("count") or 0)
    c4_active_ppm = c4.get("active_ppm")
    if not isinstance(c4_active_ppm, (int, float)):
        c4_active_ppm = (outcomes.get("distributed_success") or {}).get("active_ppm")
    if not isinstance(c4_active_ppm, (int, float)):
        c4_active_ppm = 0.0
    summary = run.get("summary") or {}
    wall = summary.get("wall_duration_s")
    captured_at = float(run.get("captured_at") or 0.0)
    return {
        "captured_at": captured_at,
        "id": time.strftime("%m-%d %H:%M", time.localtime(captured_at)),
        "label": str(run.get("label") or ""),
        "note": str(run.get("note") or ""),
        "duration_s": wall,
        "distributed_success": distributed,
        "classified_success": classified,
        "multi_drop_fail": multi,
        "not_found": not_found,
        "c4_active_ppm": float(c4_active_ppm or 0.0),
    }


def _build_leaderboard(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_leaderboard_entry(r) for r in runs]


def _best_run(leaderboard: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not leaderboard:
        return None
    return max(
        leaderboard,
        key=lambda e: (e["distributed_success"], e["c4_active_ppm"]),
    )


def _cross_run_kpi_chart(leaderboard: list[dict[str, Any]]) -> str:
    if not leaderboard:
        return ""
    # Oldest → newest on X (reverse of default display order).
    ordered = sorted(leaderboard, key=lambda e: e["captured_at"])
    labels = [e["id"] for e in ordered]
    groups = [
        {"label": "Distributed", "color_var": OUTCOME_COLOR_VAR["distributed_success"], "values": [e["distributed_success"] for e in ordered]},
        {"label": "C4 Active PPM", "color_var": CHANNEL_COLOR_VAR["classification_channel"], "values": [round(e["c4_active_ppm"], 2) for e in ordered]},
        {"label": "Multi-Drop", "color_var": OUTCOME_COLOR_VAR["multi_drop_fail"], "values": [e["multi_drop_fail"] for e in ordered]},
    ]
    legend = _legend_svg([(g["label"], g["color_var"]) for g in groups])
    chart = _svg_grouped_bar(labels, groups, title="Run-vs-run KPIs (bars normalised per metric)")
    return f'<div class="chart-wrap">{legend}{chart}</div>'


def _cross_run_table(leaderboard: list[dict[str, Any]]) -> str:
    if not leaderboard:
        return ""
    ordered = sorted(leaderboard, key=lambda e: e["captured_at"], reverse=True)
    rows: list[str] = []
    for e in ordered:
        duration = _fmt_num(e["duration_s"]) if isinstance(e["duration_s"], (int, float)) else "-"
        rows.append(
            "<tr>"
            f"<td>{html.escape(e['id'])}</td>"
            f"<td>{html.escape(e['label'] or '-')}</td>"
            f"<td>{duration}</td>"
            f"<td>{e['distributed_success']}</td>"
            f"<td>{_fmt_num(e['c4_active_ppm'], 2)}</td>"
            f"<td>{e['multi_drop_fail']}</td>"
            f"<td>{html.escape(e['note'] or '')}</td>"
            "</tr>"
        )
    return (
        "<table class='compact'>"
        "<thead><tr>"
        "<th>Run</th><th>Label</th><th>Duration (s)</th>"
        "<th>Distributed</th><th>C4 Active PPM</th><th>Multi-Drop</th><th>Note</th>"
        "</tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody></table>"
    )


# ---------------------------------------------------------------------------
# Run card rendering
# ---------------------------------------------------------------------------


def _channel_table(channel_throughput: dict[str, Any]) -> str:
    if not isinstance(channel_throughput, dict):
        return "<p>No channel throughput data available.</p>"
    rows: list[str] = []
    for channel_key in ("c_channel_2", "c_channel_3", "classification_channel"):
        data = channel_throughput.get(channel_key)
        if not isinstance(data, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{html.escape(CHANNEL_LABELS.get(channel_key, channel_key))}</td>"
            f"<td>{_fmt_count(data.get('exit_count'))}</td>"
            f"<td>{_fmt_num(data.get('overall_ppm'))}</td>"
            f"<td>{_fmt_num(data.get('active_ppm'))}</td>"
            f"<td>{_fmt_num(data.get('running_time_s'))}</td>"
            f"<td>{_fmt_num(data.get('active_time_s'))}</td>"
            f"<td>{_fmt_num(data.get('waiting_time_s'))}</td>"
            "</tr>"
        )
    if not rows:
        return "<p>No channel throughput rows available.</p>"
    return (
        "<table>"
        "<thead><tr>"
        "<th>Channel</th><th>Exit Count</th><th>PPM</th><th>PPM Active</th>"
        "<th>Run Time (s)</th><th>Active (s)</th><th>Waiting (s)</th>"
        "</tr></thead>"
        "<tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _classification_outcome_table(channel_throughput: dict[str, Any]) -> str:
    if not isinstance(channel_throughput, dict):
        return "<p>No classification outcome data available.</p>"
    c4 = channel_throughput.get("classification_channel")
    if not isinstance(c4, dict):
        return "<p>No classification outcome data available.</p>"
    outcomes = c4.get("outcomes")
    if not isinstance(outcomes, dict):
        return "<p>No classification outcome data available.</p>"
    rows: list[str] = []
    for outcome_key in (
        "classified_success",
        "distributed_success",
        "unknown",
        "multi_drop_fail",
        "not_found",
    ):
        data = outcomes.get(outcome_key)
        if not isinstance(data, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{html.escape(OUTCOME_LABELS.get(outcome_key, outcome_key))}</td>"
            f"<td>{_fmt_count(data.get('count'))}</td>"
            f"<td>{_fmt_num(data.get('overall_ppm'))}</td>"
            f"<td>{_fmt_num(data.get('active_ppm'))}</td>"
            "</tr>"
        )
    if not rows:
        return "<p>No classification outcome rows available.</p>"
    return (
        "<table>"
        "<thead><tr>"
        "<th>Outcome</th><th>Count</th><th>PPM</th><th>PPM Active</th>"
        "</tr></thead>"
        "<tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _run_summary(run_payload: dict[str, Any]) -> str:
    summary = run_payload.get("summary")
    if not isinstance(summary, dict):
        return ""
    duration_s = summary.get("wall_duration_s")
    samples = summary.get("sample_count")
    counts = summary.get("counts_delta")
    if not isinstance(counts, dict):
        counts = {}
    rows = [
        ("Wall Duration (s)", _fmt_num(duration_s)),
        ("Samples", _fmt_count(samples)),
        ("Pieces Seen", _fmt_count(counts.get("pieces_seen"))),
        ("Distributed", _fmt_count(counts.get("distributed"))),
        ("Classified", _fmt_count(counts.get("classified"))),
        ("Unknown", _fmt_count(counts.get("unknown"))),
        ("Multi-Drop", _fmt_count(counts.get("multi_drop_fail"))),
    ]
    return (
        "<table>"
        "<thead><tr><th>Run Metric</th><th>Value</th></tr></thead>"
        "<tbody>"
        + "".join(
            f"<tr><td>{html.escape(label)}</td><td>{html.escape(value)}</td></tr>"
            for label, value in rows
        )
        + "</tbody></table>"
    )


def _kpi_strip(entry: dict[str, Any]) -> str:
    tiles = [
        ("Distributed", str(entry["distributed_success"]), "--oc-distributed"),
        ("Classified", str(entry["classified_success"]), "--oc-classified"),
        ("C4 Active PPM", _fmt_num(entry["c4_active_ppm"], 2), "--c4"),
        ("Multi-Drop", str(entry["multi_drop_fail"]), "--oc-multi"),
        ("Not Found", str(entry["not_found"]), "--oc-notfound"),
    ]
    return (
        '<div class="kpi-strip">'
        + "".join(
            f'<div class="kpi-tile" style="--kpi:var({var});">'
            f'<span class="kpi-label">{html.escape(lbl)}</span>'
            f'<span class="kpi-value">{html.escape(val)}</span>'
            f"</div>"
            for lbl, val, var in tiles
        )
        + "</div>"
    )


def _run_card(run_payload: dict[str, Any], entry: dict[str, Any], *, is_open: bool) -> str:
    captured_at = float(run_payload.get("captured_at") or 0.0)
    channel_metrics = _channel_metrics_source(run_payload)
    label = str(run_payload.get("label") or "")
    strategy = str(run_payload.get("strategy") or "")
    changes = str(run_payload.get("changes") or "")
    note = str(run_payload.get("note") or "")
    raw_path = str(run_payload.get("_path") or "")
    raw_rel = html.escape(raw_path or "run.json")
    raw_href = html.escape(raw_path or "")

    ts = _extract_timeseries(run_payload)
    has_samples = bool(ts.get("elapsed_s"))

    header_title = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(captured_at))
    meta_chips = []
    if label:
        meta_chips.append(f'<span class="chip">{html.escape(label)}</span>')
    if not has_samples:
        meta_chips.append('<span class="chip chip-muted">snapshot-only</span>')
    meta_html = "".join(meta_chips)

    summary_box = _run_summary(run_payload) or '<p class="muted">Snapshot-only run — no time-series summary.</p>'

    open_attr = " open" if is_open else ""
    return (
        f'<details class="run"{open_attr}>'
        f'<summary><span class="run-date">{html.escape(header_title)}</span>{meta_html}</summary>'
        '<div class="run-body">'
        f'<p class="meta"><strong>Strategy:</strong> {html.escape(strategy or "-")} &nbsp;·&nbsp; <strong>Changes:</strong> {html.escape(changes or "-")} &nbsp;·&nbsp; <strong>Note:</strong> {html.escape(note or "-")}</p>'
        f"{_kpi_strip(entry)}"
        '<div class="charts">'
        f'<div class="chart-panel">{_chart_cumulative_exits(ts)}</div>'
        f'<div class="chart-panel">{_chart_outcomes_stacked(ts)}</div>'
        f'<div class="chart-panel">{_chart_rolling_active_ppm(ts)}</div>'
        f'<div class="chart-panel">{_chart_active_waiting(run_payload)}</div>'
        "</div>"
        '<div class="grid">'
        f"<div><h3>Run Summary</h3>{summary_box}</div>"
        f"<div><h3>Channels</h3>{_channel_table(channel_metrics)}</div>"
        f"<div><h3>C4 Outcomes</h3>{_classification_outcome_table(channel_metrics)}</div>"
        "</div>"
        f'<p class="raw"><a href="{raw_href}">{raw_rel}</a></p>'
        "</div>"
        "</details>"
    )


# ---------------------------------------------------------------------------
# Top-level rendering
# ---------------------------------------------------------------------------


def _best_banner(best: dict[str, Any] | None) -> str:
    if not best:
        return ""
    return (
        '<section class="best">'
        '<span class="best-tag">Best so far</span>'
        f'<span class="best-date">{html.escape(best["id"])}</span>'
        f'<span class="best-label">{html.escape(best["label"] or "no label")}</span>'
        '<div class="best-kpis">'
        f'<span><strong>{best["distributed_success"]}</strong> distributed</span>'
        f'<span><strong>{_fmt_num(best["c4_active_ppm"], 2)}</strong> C4 active PPM</span>'
        f'<span><strong>{best["multi_drop_fail"]}</strong> multi-drop</span>'
        "</div>"
        "</section>"
    )


def _build_index(title: str, runs: list[dict[str, Any]]) -> str:
    leaderboard = _build_leaderboard(runs)
    best = _best_run(leaderboard)
    entry_by_path = {e["captured_at"]: e for e in leaderboard}

    cards: list[str] = []
    for idx, run in enumerate(runs):
        captured_at = float(run.get("captured_at") or 0.0)
        entry = entry_by_path.get(captured_at) or _leaderboard_entry(run)
        cards.append(_run_card(run, entry, is_open=(idx == 0)))

    cross_kpi = _cross_run_kpi_chart(leaderboard)
    cross_table = _cross_run_table(leaderboard)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --bg: #f3efe6;
      --panel: #fffdf8;
      --panel-2: #fbf7ec;
      --ink: #1f1f1a;
      --muted: #8a8576;
      --line: #e2d9c5;
      --line-strong: #c7bda5;
      --accent: #336b56;
      /* channel palette */
      --c2: #d98a2b;
      --c3: #2e7da8;
      --c4: #7a3aa6;
      /* outcome palette */
      --oc-distributed: #2e7d4f;
      --oc-classified:  #4a9d7e;
      --oc-unknown:     #8a8576;
      --oc-multi:       #b84a3a;
      --oc-notfound:    #c98b2a;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font: 14px/1.5 "IBM Plex Sans", "Avenir Next", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(247, 211, 120, 0.22), transparent 28%),
        linear-gradient(180deg, #f5f0e7 0%, var(--bg) 100%);
    }}
    main {{
      max-width: 1000px;
      margin: 0 auto;
      padding: 24px 20px 64px;
    }}
    h1, h2, h3 {{
      margin: 0 0 10px;
      font-family: "IBM Plex Sans Condensed", "Avenir Next Condensed", sans-serif;
      letter-spacing: 0.02em;
    }}
    h1 {{ font-size: 26px; }}
    h2 {{ font-size: 18px; }}
    h3 {{ font-size: 14px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; }}
    .lede {{ color: var(--muted); margin: 4px 0 20px; max-width: 68ch; }}
    .muted {{ color: var(--muted); }}

    .best {{
      display: flex; align-items: center; flex-wrap: wrap; gap: 14px;
      background: linear-gradient(135deg, #fff6d9, #f1dca0);
      border: 1px solid #d9bf6d;
      padding: 14px 18px;
      margin: 0 0 20px;
      box-shadow: 0 6px 16px rgba(120, 90, 20, 0.12);
    }}
    .best-tag {{
      font-weight: 700; text-transform: uppercase; letter-spacing: 0.14em;
      font-size: 11px; color: #7a5a10; background: #fff2c2; padding: 3px 8px;
      border: 1px solid #d9bf6d;
    }}
    .best-date {{ font-weight: 700; }}
    .best-label {{ color: var(--muted); }}
    .best-kpis {{ margin-left: auto; display: flex; gap: 14px; }}
    .best-kpis strong {{ font-size: 18px; color: var(--ink); }}

    .section {{
      background: var(--panel); border: 1px solid var(--line); padding: 16px 18px;
      margin: 0 0 18px;
    }}
    .section h2 {{ margin-bottom: 12px; }}

    details.run {{
      background: var(--panel); border: 1px solid var(--line);
      margin: 0 0 14px; padding: 0;
    }}
    details.run[open] {{ border-color: var(--line-strong); }}
    details.run > summary {{
      list-style: none; cursor: pointer;
      padding: 12px 16px;
      display: flex; align-items: center; gap: 10px;
      background: var(--panel-2); border-bottom: 1px solid transparent;
    }}
    details.run[open] > summary {{ border-bottom-color: var(--line); }}
    details.run > summary::-webkit-details-marker {{ display: none; }}
    details.run > summary::before {{
      content: "›"; display: inline-block; font-size: 18px; color: var(--muted);
      transition: transform 0.15s ease; width: 12px;
    }}
    details.run[open] > summary::before {{ transform: rotate(90deg); }}
    .run-date {{ font-weight: 700; }}
    .chip {{
      font-size: 11px; padding: 2px 8px; background: #efe7d3;
      border: 1px solid var(--line); color: var(--ink);
      text-transform: uppercase; letter-spacing: 0.06em;
    }}
    .chip-muted {{ color: var(--muted); background: transparent; }}
    .run-body {{ padding: 16px 18px 18px; }}
    .meta {{ color: var(--muted); margin: 0 0 12px; font-size: 13px; }}

    .kpi-strip {{
      display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 8px; margin: 0 0 16px;
    }}
    .kpi-tile {{
      padding: 10px 12px; background: var(--panel-2);
      border: 1px solid var(--line); border-left: 3px solid var(--kpi, var(--accent));
      display: flex; flex-direction: column; gap: 2px;
    }}
    .kpi-label {{ font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); }}
    .kpi-value {{ font-size: 20px; font-weight: 700; color: var(--ink); }}

    .charts {{ display: flex; flex-direction: column; gap: 14px; margin-bottom: 18px; }}
    .chart-panel {{
      background: #fffdf6; border: 1px solid var(--line); padding: 14px;
    }}
    .chart-wrap {{ display: flex; flex-direction: column; gap: 6px; }}
    svg.chart {{ width: 100%; height: auto; display: block; }}
    .chart-title {{ font-size: 13px; font-weight: 700; fill: var(--ink); }}
    .axis {{ font-size: 10px; fill: var(--muted); }}
    .axis-label {{ font-size: 11px; fill: var(--muted); }}
    .axis-line {{ stroke: var(--line-strong); stroke-width: 1; }}
    .grid {{ stroke: var(--line); stroke-width: 0.6; }}
    .grid-v {{ stroke-dasharray: 2 3; stroke: var(--line); }}
    .bar-val {{ font-size: 10px; fill: var(--ink); font-weight: 600; }}
    .chart-empty {{ padding: 12px 8px; color: var(--muted); font-style: italic; font-size: 13px; }}

    .legend {{ display: flex; flex-wrap: wrap; gap: 10px 16px; font-size: 12px; color: var(--muted); }}
    .legend-item {{ display: inline-flex; align-items: center; gap: 6px; }}
    .legend-swatch {{ display: inline-block; width: 12px; height: 12px; border: 1px solid var(--line); }}

    .grid {{ /* scoped-via-context; tables grid usage below */ }}
    .run-body .grid {{
      display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 14px; margin-top: 10px;
    }}

    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{
      text-align: left; border-bottom: 1px solid var(--line);
      padding: 6px 8px; vertical-align: top;
    }}
    th {{ color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; }}
    table.compact td, table.compact th {{ padding: 4px 6px; font-size: 12.5px; }}

    .raw {{ margin-top: 14px; font-size: 12px; }}
    a {{ color: var(--accent); }}
  </style>
</head>
<body>
  <main>
    <h1>{html.escape(title)}</h1>
    <p class="lede">Iterative throughput snapshots for C2, C3, and the classification channel. Rolling active-PPM is measured over a 30s sliding window against per-channel busy time; the faint dashed overlay is the raw cumulative overall PPM.</p>
    {_best_banner(best)}
    <section class="section">
      <h2>Runs at a glance</h2>
      {cross_kpi}
      {cross_table}
    </section>
    {''.join(cards) or '<p>No runs recorded yet.</p>'}
  </main>
</body>
</html>
"""


def _write_index(out_root: Path, title: str, runs: list[dict[str, Any]]) -> None:
    for run in runs:
        raw_path = Path(str(run.get("_path")))
        try:
            run["_path"] = str(raw_path.relative_to(out_root))
        except ValueError:
            run["_path"] = str(raw_path)
    (out_root / "index.html").write_text(_build_index(title, runs), encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture and render iterative channel throughput report runs.")
    parser.add_argument("--backend-base", default=BASE)
    parser.add_argument("--out-root", default=str(OUT_ROOT))
    parser.add_argument("--title", default="Sorter Channel Throughput Report")
    parser.add_argument("--label", default="")
    parser.add_argument("--strategy", default="")
    parser.add_argument("--changes", default="")
    parser.add_argument("--note", default="")
    parser.add_argument("--render-only", action="store_true", help="Skip the /runtime-stats fetch; just rebuild index.html from existing runs.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    out_root = Path(args.out_root).expanduser().resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    if not args.render_only:
        try:
            snapshot = _load_runtime_stats(args.backend_base)
            run_payload = _run_payload(args, snapshot)
            _write_run(out_root, run_payload)
        except Exception as exc:
            print(f"WARN: could not fetch runtime-stats ({exc}); rendering existing runs only.")

    runs = _load_runs(out_root)
    _write_index(out_root, args.title, runs)
    print(str(out_root / "index.html"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
