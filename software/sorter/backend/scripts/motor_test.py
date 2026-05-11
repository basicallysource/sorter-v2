"""motor_test.py — tiny web UI for end-to-end stepper/servo testing.

Initialises hardware via the real mkIRLConfig/mkIRLInterface pathways, then
serves a single-page app on localhost so you can drive every motor manually.

Usage (from software/sorter/backend/):
    uv run python scripts/motor_test.py [--port 8765] [--debug]
"""

from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path
from typing import Any

# ── backend imports ───────────────────────────────────────────────────────────

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import Flask, jsonify, request
from global_config import GlobalConfig, Timeouts
from irl.config import IRLInterface, mkIRLConfig, mkIRLInterface
from logger import Logger
from hardware.sorter_interface import StepperMotor, ServoMotor

# ── global state ──────────────────────────────────────────────────────────────

app = Flask(__name__)
irl: IRLInterface | None = None
_lock = threading.Lock()

STEPPER_ATTR_BASES = [
    "carousel",
    "chute_stepper",
    "c_channel_1_rotor",
    "c_channel_2_rotor",
    "c_channel_3_rotor",
    "fifth_stepper",
    "distribution_aux_1_stepper",
    "distribution_aux_2_stepper",
    "distribution_aux_3_stepper",
]


def _get_steppers() -> dict[str, StepperMotor]:
    assert irl is not None
    result: dict[str, StepperMotor] = {}
    for base in STEPPER_ATTR_BASES:
        motor = getattr(irl, base, None)
        if motor is not None and isinstance(motor, StepperMotor):
            result[base] = motor
    return result


def _get_servos() -> list[ServoMotor]:
    assert irl is not None
    return list(irl.servos) if hasattr(irl, "servos") and irl.servos else []


# ── API routes ────────────────────────────────────────────────────────────────

@app.get("/api/status")
def api_status():
    steppers = {name: {"enabled": m.enabled} for name, m in _get_steppers().items()}
    servos = [{"index": i, "enabled": s.enabled} for i, s in enumerate(_get_servos())]
    return jsonify({"steppers": steppers, "servos": servos})


@app.post("/api/stepper/enable")
def api_stepper_enable():
    name = request.json.get("name")
    steppers = _get_steppers()
    if name not in steppers:
        return jsonify({"error": f"unknown stepper {name!r}"}), 404
    with _lock:
        steppers[name].enabled = True
    return jsonify({"ok": True})


@app.post("/api/stepper/disable")
def api_stepper_disable():
    name = request.json.get("name")
    steppers = _get_steppers()
    if name not in steppers:
        return jsonify({"error": f"unknown stepper {name!r}"}), 404
    with _lock:
        steppers[name].enabled = False
    return jsonify({"ok": True})


@app.post("/api/stepper/speed")
def api_stepper_speed():
    body = request.json
    name = body.get("name")
    max_speed = int(body.get("max_speed", 2000))
    steppers = _get_steppers()
    if name not in steppers:
        return jsonify({"error": f"unknown stepper {name!r}"}), 404
    with _lock:
        steppers[name].set_speed_limits(16, max_speed)
    return jsonify({"ok": True})


@app.post("/api/stepper/move")
def api_stepper_move():
    body: dict[str, Any] = request.json or {}
    name = body.get("name")
    steppers = _get_steppers()
    if name not in steppers:
        return jsonify({"error": f"unknown stepper {name!r}"}), 404

    motor = steppers[name]
    blocking = bool(body.get("blocking", True))

    with _lock:
        if "steps" in body:
            steps = int(body["steps"])
            ok = motor.move_steps_blocking(steps) if blocking else motor.move_steps(steps)
        elif "degrees" in body:
            degrees = float(body["degrees"])
            ok = motor.move_degrees_blocking(degrees) if blocking else motor.move_degrees(degrees)
        else:
            return jsonify({"error": "provide steps or degrees"}), 400

    return jsonify({"ok": ok})


@app.post("/api/stepper/stop")
def api_stepper_stop():
    name = request.json.get("name")
    steppers = _get_steppers()
    if name not in steppers:
        return jsonify({"error": f"unknown stepper {name!r}"}), 404
    with _lock:
        steppers[name].move_at_speed(0)
    return jsonify({"ok": True})


@app.post("/api/servo/move")
def api_servo_move():
    body = request.json
    idx = int(body.get("index", 0))
    angle = int(body.get("angle", 90))
    release = bool(body.get("release", False))
    servos = _get_servos()
    if idx >= len(servos):
        return jsonify({"error": f"servo index {idx} out of range"}), 404
    with _lock:
        ok = servos[idx].move_to_and_release(angle) if release else servos[idx].move_to(angle)
    return jsonify({"ok": ok})


@app.post("/api/servo/enable")
def api_servo_enable():
    idx = int(request.json.get("index", 0))
    servos = _get_servos()
    if idx >= len(servos):
        return jsonify({"error": f"servo index {idx} out of range"}), 404
    with _lock:
        servos[idx].enabled = True
    return jsonify({"ok": True})


@app.post("/api/servo/disable")
def api_servo_disable():
    idx = int(request.json.get("index", 0))
    servos = _get_servos()
    if idx >= len(servos):
        return jsonify({"error": f"servo index {idx} out of range"}), 404
    with _lock:
        servos[idx].enabled = False
    return jsonify({"ok": True})


# ── HTML ──────────────────────────────────────────────────────────────────────

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>motor test</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg: #0f1117; --surface: #1a1d27; --border: #2a2d3a;
    --text: #e2e4ef; --muted: #6b7280; --accent: #6366f1;
    --green: #22c55e; --red: #ef4444; --yellow: #eab308;
    font-family: ui-monospace, 'Cascadia Code', monospace;
  }
  body { background: var(--bg); color: var(--text); min-height: 100vh; padding: 24px; }
  h1 { font-size: 1.1rem; font-weight: 600; color: var(--muted); margin-bottom: 24px;
       letter-spacing: .08em; text-transform: uppercase; }
  h2 { font-size: .75rem; font-weight: 600; color: var(--muted); letter-spacing: .1em;
       text-transform: uppercase; margin: 32px 0 12px; }
  .cards { display: flex; flex-wrap: wrap; gap: 16px; }
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
          padding: 16px; width: 320px; display: flex; flex-direction: column; gap: 10px; }
  .card-title { font-size: .9rem; font-weight: 600; }
  .row { display: flex; gap: 8px; align-items: center; }
  .row label { font-size: .75rem; color: var(--muted); width: 60px; flex-shrink: 0; }
  input[type=number], input[type=range] { flex: 1; background: var(--bg); border: 1px solid var(--border);
    border-radius: 6px; color: var(--text); padding: 5px 8px; font-family: inherit; font-size: .8rem; }
  input[type=range] { padding: 0; }
  .speed-val { font-size: .75rem; color: var(--muted); width: 40px; text-align: right; }
  button { border: none; border-radius: 6px; cursor: pointer; font-family: inherit;
           font-size: .78rem; font-weight: 500; padding: 6px 12px; transition: opacity .15s; }
  button:hover { opacity: .85; }
  button:active { opacity: .7; }
  .btn-accent { background: var(--accent); color: #fff; }
  .btn-green  { background: var(--green);  color: #000; }
  .btn-red    { background: var(--red);    color: #fff; }
  .btn-muted  { background: var(--border); color: var(--text); }
  .btn-row { display: flex; gap: 6px; flex-wrap: wrap; }
  .status-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0;
                background: var(--red); }
  .status-dot.on { background: var(--green); }
  .feedback { font-size: .72rem; color: var(--muted); min-height: 1.2em; }
  .feedback.ok  { color: var(--green); }
  .feedback.err { color: var(--red); }
</style>
</head>
<body>
<h1>motor test</h1>

<h2>steppers</h2>
<div id="stepper-cards" class="cards"></div>

<h2>servos</h2>
<div id="servo-cards" class="cards"></div>

<script>
const post = (url, body) =>
  fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)})
    .then(r => r.json());

function feedback(el, res) {
  el.textContent = res.ok ? 'ok' : (res.error || 'error');
  el.className = 'feedback ' + (res.ok ? 'ok' : 'err');
  clearTimeout(el._t);
  el._t = setTimeout(() => { el.textContent = ''; el.className = 'feedback'; }, 2500);
}

function mkStepperCard(name, info) {
  const card = document.createElement('div');
  card.className = 'card';
  card.dataset.name = name;

  card.innerHTML = `
    <div class="row">
      <div class="status-dot ${info.enabled ? 'on' : ''}"></div>
      <span class="card-title">${name}</span>
    </div>
    <div class="row">
      <label>speed</label>
      <input type="range" class="speed-range" min="50" max="6000" step="50" value="2000">
      <span class="speed-val">2000</span>
      <button class="btn-muted set-speed-btn">set</button>
    </div>
    <div class="row">
      <label>steps</label>
      <input type="number" class="steps-input" value="200" step="1">
      <button class="btn-accent move-steps-btn">move</button>
    </div>
    <div class="row">
      <label>degrees</label>
      <input type="number" class="deg-input" value="90" step="1">
      <button class="btn-accent move-deg-btn">move</button>
    </div>
    <div class="btn-row">
      <button class="btn-green enable-btn">enable</button>
      <button class="btn-red disable-btn">disable</button>
      <button class="btn-muted stop-btn">stop</button>
    </div>
    <div class="feedback"></div>
  `;

  const dot = card.querySelector('.status-dot');
  const fb = card.querySelector('.feedback');
  const speedRange = card.querySelector('.speed-range');
  const speedVal = card.querySelector('.speed-val');

  speedRange.addEventListener('input', () => { speedVal.textContent = speedRange.value; });

  card.querySelector('.set-speed-btn').onclick = () =>
    post('/api/stepper/speed', {name, max_speed: +speedRange.value}).then(r => feedback(fb, r));

  card.querySelector('.move-steps-btn').onclick = () =>
    post('/api/stepper/move', {name, steps: +card.querySelector('.steps-input').value})
      .then(r => feedback(fb, r));

  card.querySelector('.move-deg-btn').onclick = () =>
    post('/api/stepper/move', {name, degrees: +card.querySelector('.deg-input').value})
      .then(r => feedback(fb, r));

  card.querySelector('.enable-btn').onclick = () =>
    post('/api/stepper/enable', {name}).then(r => { if(r.ok) dot.classList.add('on'); feedback(fb, r); });

  card.querySelector('.disable-btn').onclick = () =>
    post('/api/stepper/disable', {name}).then(r => { if(r.ok) dot.classList.remove('on'); feedback(fb, r); });

  card.querySelector('.stop-btn').onclick = () =>
    post('/api/stepper/stop', {name}).then(r => feedback(fb, r));

  return card;
}

function mkServoCard(idx, info) {
  const card = document.createElement('div');
  card.className = 'card';

  card.innerHTML = `
    <div class="row">
      <div class="status-dot ${info.enabled ? 'on' : ''}"></div>
      <span class="card-title">servo ${idx}</span>
    </div>
    <div class="row">
      <label>angle</label>
      <input type="number" class="angle-input" value="90" min="0" max="180" step="1">
    </div>
    <div class="btn-row">
      <button class="btn-accent move-btn">move to</button>
      <button class="btn-muted release-btn">move + release</button>
      <button class="btn-green enable-btn">enable</button>
      <button class="btn-red disable-btn">disable</button>
    </div>
    <div class="feedback"></div>
  `;

  const dot = card.querySelector('.status-dot');
  const fb = card.querySelector('.feedback');
  const angleInput = card.querySelector('.angle-input');

  card.querySelector('.move-btn').onclick = () =>
    post('/api/servo/move', {index: idx, angle: +angleInput.value}).then(r => feedback(fb, r));

  card.querySelector('.release-btn').onclick = () =>
    post('/api/servo/move', {index: idx, angle: +angleInput.value, release: true}).then(r => feedback(fb, r));

  card.querySelector('.enable-btn').onclick = () =>
    post('/api/servo/enable', {index: idx}).then(r => { if(r.ok) dot.classList.add('on'); feedback(fb, r); });

  card.querySelector('.disable-btn').onclick = () =>
    post('/api/servo/disable', {index: idx}).then(r => { if(r.ok) dot.classList.remove('on'); feedback(fb, r); });

  return card;
}

async function init() {
  const {steppers, servos} = await fetch('/api/status').then(r => r.json());

  const sc = document.getElementById('stepper-cards');
  for (const [name, info] of Object.entries(steppers))
    sc.appendChild(mkStepperCard(name, info));
  if (!Object.keys(steppers).length)
    sc.innerHTML = '<p style="color:var(--muted);font-size:.8rem">no steppers detected</p>';

  const vc = document.getElementById('servo-cards');
  for (const [i, info] of servos.entries())
    vc.appendChild(mkServoCard(i, info));
  if (!servos.length)
    vc.innerHTML = '<p style="color:var(--muted);font-size:.8rem">no servos detected</p>';
}

init();
</script>
</body>
</html>"""


@app.get("/")
def index():
    return PAGE


# ── startup ───────────────────────────────────────────────────────────────────

def buildGc(debug: bool) -> GlobalConfig:
    gc = GlobalConfig()
    gc.logger = Logger(debug_level=3 if debug else 1)
    gc.timeouts = Timeouts()
    gc.disable_chute = False
    gc.disable_servos = False
    return gc


def main() -> None:
    global irl

    parser = argparse.ArgumentParser(description="Motor test web UI")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    gc = buildGc(args.debug)
    gc.logger.info("motor_test: loading IRL config")
    irl_config = mkIRLConfig()

    gc.logger.info("motor_test: initialising hardware")
    irl = mkIRLInterface(irl_config, gc)
    irl.enableSteppers()

    steppers = _get_steppers()
    servos = _get_servos()
    print(f"\nDetected {len(steppers)} stepper(s): {', '.join(steppers) or 'none'}")
    print(f"Detected {len(servos)} servo(s)")
    import socket
    hostname = socket.gethostname()
    print(f"\nOpen http://{hostname}:{args.port}  (or http://<pi-ip>:{args.port})\n")

    app.run(host="0.0.0.0", port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
