import argparse
import html
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from sorter_bus import (
    Servo,
    SorterBus,
    Stepper,
    enumerate_pico_ports,
)


DEFAULT_MIN_DUTY_US = 500
DEFAULT_MAX_DUTY_US = 2500
DEFAULT_MIN_SPEED = 100
DEFAULT_MAX_SPEED = 20000
DEFAULT_ACCEL = 2000

DEFAULT_STEPPER_SPEED = 2000
DEFAULT_STEPPER_STEPS = 200

state: dict = {
    "bus": None,
    "address": None,
    "board_info": None,
    "servos": [],
    "steppers": [],
    "port": None,
}


USB_DEVICE_ADDRESS = 0


def _try_open(port: str) -> tuple[SorterBus, int, dict] | None:
    try:
        bus = SorterBus(port, timeout=0.2)
    except Exception:
        return None
    try:
        info = bus.init(USB_DEVICE_ADDRESS)
    except Exception:
        bus.close()
        return None
    return bus, USB_DEVICE_ADDRESS, info


def scan_boards() -> list[dict]:
    results: list[dict] = []
    for p in enumerate_pico_ports():
        entry: dict = {"port": p, "ok": False, "info": None, "error": None}
        # If the UI is already connected to this port, reuse the cached info
        # instead of re-opening the serial (macOS doesn't love concurrent opens).
        if state.get("port") == p and state.get("bus") is not None:
            entry["ok"] = True
            entry["info"] = state.get("board_info")
            entry["address"] = state.get("address")
            results.append(entry)
            continue
        try:
            bus = SorterBus(p, timeout=0.2)
        except Exception as e:
            entry["error"] = f"open failed: {e}"
            results.append(entry)
            continue
        try:
            entry["info"] = bus.init(USB_DEVICE_ADDRESS)
            entry["address"] = USB_DEVICE_ADDRESS
            entry["ok"] = True
        except Exception as e:
            entry["error"] = str(e)
        finally:
            bus.close()
        results.append(entry)
    return results


def connect(port: str) -> None:
    result = _try_open(port)
    if result is None:
        raise RuntimeError(f"No sorter-interface device responded on {port}.")
    bus, address, board_info = result

    servo_count = int(board_info.get("servo_count", 0))
    servos = [Servo(bus, address, ch) for ch in range(servo_count)]

    stepper_count = int(board_info.get("stepper_count", 0))
    steppers = [Stepper(bus, address, ch) for ch in range(stepper_count)]

    state["bus"] = bus
    state["address"] = address
    state["board_info"] = board_info
    state["servos"] = servos
    state["steppers"] = steppers
    state["port"] = port


def disconnect() -> None:
    bus = state.get("bus")
    if bus is not None:
        bus.close()
    state["bus"] = None
    state["address"] = None
    state["board_info"] = None
    state["servos"] = []
    state["steppers"] = []
    state["port"] = None


def get_servo(channel: int) -> Servo:
    servos = state.get("servos") or []
    if channel < 0 or channel >= len(servos):
        raise HTTPException(404, f"servo channel {channel} not available")
    return servos[channel]


def get_stepper(channel: int) -> Stepper:
    steppers = state.get("steppers") or []
    if channel < 0 or channel >= len(steppers):
        raise HTTPException(404, f"stepper channel {channel} not available")
    return steppers[channel]


def stepper_name(channel: int) -> str:
    info = state.get("board_info") or {}
    names = info.get("stepper_names") or []
    if 0 <= channel < len(names):
        return str(names[channel])
    return f"stepper_{channel}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    disconnect()


app = FastAPI(lifespan=lifespan)


def servo_row(servo: Servo) -> str:
    angle = servo.last_angle if servo.last_angle is not None else 90.0
    enabled_badge = (
        '<span class="badge on">ON</span>' if servo.enabled else '<span class="badge off">off</span>'
    )
    last_text = f"{servo.last_angle:.1f}°" if servo.last_angle is not None else "—"
    ch = servo.channel
    return f"""
<div class="row" id="servo-{ch}">
  <div class="label">ch{ch:02d} {enabled_badge}</div>
  <form hx-post="/servo/{ch}/move" hx-target="#servo-{ch}" hx-swap="outerHTML" class="move">
    <input type="range" name="angle" min="0" max="180" step="1" value="{angle:.0f}"
           oninput="this.nextElementSibling.value=this.value" />
    <output>{angle:.0f}</output>
    <label><input type="checkbox" name="release" /> release</label>
    <button type="submit">move</button>
  </form>
  <div class="info">last: {last_text}</div>
  <div class="actions">
    <button hx-post="/servo/{ch}/enable" hx-target="#servo-{ch}" hx-swap="outerHTML">enable</button>
    <button hx-post="/servo/{ch}/disable" hx-target="#servo-{ch}" hx-swap="outerHTML">disable</button>
    <button hx-post="/servo/{ch}/stop" hx-target="#servo-{ch}" hx-swap="outerHTML">stop</button>
    <button hx-post="/servo/{ch}/position" hx-target="#servo-{ch} .info" hx-swap="innerHTML">read pos</button>
  </div>
</div>
"""


def render_all_rows() -> str:
    servos = state.get("servos") or []
    if not servos:
        return '<div class="empty">no servos (board not connected or servo_count=0)</div>'
    return "\n".join(servo_row(s) for s in servos)


def stepper_row(stepper: Stepper) -> str:
    ch = stepper.channel
    name = html.escape(stepper_name(ch))
    enabled_badge = (
        '<span class="badge on">ON</span>' if stepper.enabled else '<span class="badge off">off</span>'
    )
    return f"""
<div class="row stepper-row" id="stepper-{ch}">
  <div class="label">st{ch:02d} {enabled_badge}<br><span class="sub">{name}</span></div>
  <form hx-target="#stepper-{ch}" hx-swap="outerHTML" class="move" id="stepper-{ch}-form">
    <label>steps <input type="number" name="steps" value="{DEFAULT_STEPPER_STEPS}" style="width:80px" /></label>
    <button type="button" hx-post="/stepper/{ch}/move/pos" hx-include="#stepper-{ch}-form" hx-target="#stepper-{ch}" hx-swap="outerHTML">+</button>
    <button type="button" hx-post="/stepper/{ch}/move/neg" hx-include="#stepper-{ch}-form" hx-target="#stepper-{ch}" hx-swap="outerHTML">-</button>
  </form>
  <div class="info" id="stepper-{ch}-info">pos: —</div>
  <div class="actions">
    <button hx-post="/stepper/{ch}/enable" hx-target="#stepper-{ch}" hx-swap="outerHTML">enable</button>
    <button hx-post="/stepper/{ch}/disable" hx-target="#stepper-{ch}" hx-swap="outerHTML">disable</button>
    <button hx-post="/stepper/{ch}/stop" hx-target="#stepper-{ch}" hx-swap="outerHTML">stop</button>
    <button hx-post="/stepper/{ch}/position" hx-target="#stepper-{ch}-info" hx-swap="innerHTML">read pos</button>
  </div>
</div>
"""


def render_all_steppers() -> str:
    steppers = state.get("steppers") or []
    if not steppers:
        return '<div class="empty">no steppers (board not connected or stepper_count=0)</div>'
    return "\n".join(stepper_row(s) for s in steppers)


def render_header() -> str:
    info = state.get("board_info")
    port = state.get("port")
    if not info:
        return '<div class="header">not connected</div>'
    name = html.escape(str(info.get("device_name", "?")))
    scount = info.get("servo_count", 0)
    stcount = info.get("stepper_count", 0)
    return (
        f'<div class="header">'
        f"<b>{name}</b> &nbsp; port={html.escape(str(port))} &nbsp; addr=0x{state['address']:02x} "
        f"&nbsp; servos={scount} &nbsp; steppers={stcount}"
        f"</div>"
    )


def render_board_list() -> str:
    boards = scan_boards()
    connected_port = state.get("port")
    if not boards:
        return '<div class="empty">no Picos on USB (VID 0x2E8A / PID 0x000A)</div>'
    parts: list[str] = []
    for b in boards:
        port = b["port"]
        is_connected = connected_port == port and state.get("bus") is not None
        if b["ok"]:
            info = b["info"]
            name = html.escape(str(info.get("device_name", "?")))
            scount = info.get("servo_count", 0)
            stcount = info.get("stepper_count", 0)
            addr = b.get("address", 0)
            meta = (
                f"<b>{name}</b> &nbsp; addr=0x{addr:02x} &nbsp; "
                f"servos={scount} &nbsp; steppers={stcount}"
            )
            if is_connected:
                action = (
                    f'<button hx-post="/disconnect" hx-target="#connection" hx-swap="innerHTML" '
                    f'hx-on::after-request="document.getElementById(\'servos\').innerHTML=\'\';document.getElementById(\'steppers\').innerHTML=\'\'">disconnect</button>'
                )
                status = '<span class="badge on">connected</span>'
            else:
                action = (
                    f'<form hx-post="/connect" hx-target="#connection" hx-swap="innerHTML" '
                    f'hx-on::after-request="document.getElementById(\'servos\').dispatchEvent(new Event(\'refresh\'));document.getElementById(\'steppers\').dispatchEvent(new Event(\'refresh\'))">'
                    f'<input type="hidden" name="port" value="{html.escape(port)}" />'
                    f'<button type="submit">connect</button>'
                    f"</form>"
                )
                status = ""
        else:
            meta = f'<span class="err-inline">error: {html.escape(str(b.get("error", "?")))}</span>'
            action = ""
            status = ""
        parts.append(
            f'<div class="board">'
            f'<div class="board-port">{html.escape(port)} {status}</div>'
            f'<div class="board-meta">{meta}</div>'
            f'<div class="board-action">{action}</div>'
            f"</div>"
        )
    return "\n".join(parts)


def render_connection_block() -> str:
    header = render_header()
    board_list = render_board_list()
    return (
        f'{header}'
        f'<div class="board-list">{board_list}</div>'
        f'<div class="toolbar">'
        f'  <button hx-get="/boards" hx-target="#connection" hx-swap="innerHTML">rescan</button>'
        f"</div>"
    )


INDEX_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<title>servo tester</title>
<script src="https://unpkg.com/htmx.org@2.0.3"></script>
<style>
  body { font-family: ui-monospace, Menlo, monospace; background:#111; color:#ddd; padding:16px; max-width:900px; margin:0 auto; }
  h1 { font-size:18px; margin:0 0 12px; }
  .header { background:#1a1a1a; padding:8px 12px; border:1px solid #333; margin-bottom:12px; border-radius:4px; }
  .toolbar { display:flex; gap:8px; margin-bottom:12px; flex-wrap:wrap; }
  .toolbar input[type=text] { background:#000; color:#ddd; border:1px solid #444; padding:4px 8px; width:200px; }
  .toolbar input[type=number] { background:#000; color:#ddd; border:1px solid #444; padding:4px 8px; width:80px; }
  button { background:#222; color:#ddd; border:1px solid #444; padding:4px 10px; cursor:pointer; }
  button:hover { background:#333; }
  .row { display:grid; grid-template-columns: 120px 1fr 100px 320px; gap:8px; align-items:center;
         padding:6px 8px; border:1px solid #222; border-radius:4px; margin-bottom:4px; background:#181818; }
  .row .label { font-weight:bold; }
  .row .move { display:flex; gap:8px; align-items:center; }
  .row .move input[type=range] { flex:1; }
  .row .move output { width:32px; text-align:right; }
  .row .info { color:#888; font-size:12px; }
  .row .actions { display:flex; gap:4px; justify-content:flex-end; }
  .row .actions button { padding:2px 6px; font-size:12px; }
  .badge { font-size:10px; padding:1px 4px; border-radius:2px; }
  .badge.on { background:#284; color:#fff; }
  .badge.off { background:#333; color:#888; }
  .empty { padding:16px; color:#888; font-style:italic; }
  fieldset { border:1px solid #333; margin-bottom:12px; padding:8px 12px; border-radius:4px; }
  legend { color:#888; font-size:12px; }
  .msg { padding:6px 10px; border-radius:4px; margin-bottom:8px; font-size:12px; }
  .msg.ok { background:#1a2a1a; color:#afa; }
  .msg.err { background:#2a1a1a; color:#faa; }
  .board-list { display:flex; flex-direction:column; gap:4px; margin-bottom:8px; }
  .board { display:grid; grid-template-columns: 220px 1fr 140px; gap:8px; align-items:center;
           padding:6px 10px; border:1px solid #222; border-radius:4px; background:#181818; }
  .board-port { font-weight:bold; font-size:13px; }
  .board-meta { color:#bbb; font-size:12px; }
  .board-action { text-align:right; }
  .err-inline { color:#faa; }
  .sub { color:#888; font-size:10px; font-weight:normal; }
  .stepper-row { background:#131a13; }
</style>
</head>
<body>
<h1>servo tester</h1>

<div id="msg"></div>

<fieldset>
  <legend>connection</legend>
  <div id="connection">__CONNECTION__</div>
</fieldset>

<fieldset>
  <legend>global (apply to all servos)</legend>
  <form class="toolbar" hx-post="/all/duty" hx-target="#msg" hx-swap="innerHTML">
    <label>duty min µs <input type="number" name="min_us" value="500" /></label>
    <label>duty max µs <input type="number" name="max_us" value="2500" /></label>
    <button type="submit">set duty limits</button>
  </form>
  <form class="toolbar" hx-post="/all/speed" hx-target="#msg" hx-swap="innerHTML">
    <label>speed min (0.1°/s) <input type="number" name="min_speed" value="100" /></label>
    <label>speed max (0.1°/s) <input type="number" name="max_speed" value="20000" /></label>
    <button type="submit">set speed limits</button>
  </form>
  <form class="toolbar" hx-post="/all/accel" hx-target="#msg" hx-swap="innerHTML">
    <label>accel (0.1°/s²) <input type="number" name="accel" value="2000" /></label>
    <button type="submit">set acceleration</button>
  </form>
  <form class="toolbar" hx-post="/all/disable" hx-target="#servos" hx-swap="innerHTML">
    <button type="submit">disable all</button>
  </form>
</fieldset>

<div id="servos" hx-get="/servos" hx-trigger="refresh from:this, load">__SERVOS__</div>

<fieldset>
  <legend>steppers (global)</legend>
  <form class="toolbar" hx-post="/stepper-all/speed" hx-target="#msg" hx-swap="innerHTML">
    <label>min µsteps/s <input type="number" name="min_speed" value="16" /></label>
    <label>max µsteps/s <input type="number" name="max_speed" value="4000" /></label>
    <button type="submit">set speed limits</button>
  </form>
  <form class="toolbar" hx-post="/stepper-all/accel" hx-target="#msg" hx-swap="innerHTML">
    <label>accel (µsteps/s²) <input type="number" name="accel" value="20000" /></label>
    <button type="submit">set acceleration</button>
  </form>
  <form class="toolbar" hx-post="/stepper-all/current" hx-target="#msg" hx-swap="innerHTML">
    <label>irun <input type="number" name="irun" value="16" /></label>
    <label>ihold <input type="number" name="ihold" value="4" /></label>
    <label>ihold_delay <input type="number" name="ihold_delay" value="10" /></label>
    <button type="submit">set current</button>
  </form>
  <form class="toolbar" hx-post="/stepper-all/microsteps" hx-target="#msg" hx-swap="innerHTML">
    <label>microsteps <input type="number" name="microsteps" value="8" /></label>
    <button type="submit">set microsteps</button>
  </form>
  <form class="toolbar" hx-post="/stepper-all/disable" hx-target="#steppers" hx-swap="innerHTML">
    <button type="submit">disable all steppers</button>
  </form>
</fieldset>

<div id="steppers" hx-get="/steppers" hx-trigger="refresh from:this, load">__STEPPERS__</div>

</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    html_page = (
        INDEX_HTML.replace("__CONNECTION__", render_connection_block())
        .replace("__SERVOS__", render_all_rows())
        .replace("__STEPPERS__", render_all_steppers())
    )
    return HTMLResponse(html_page)


@app.get("/servos", response_class=HTMLResponse)
async def list_servos() -> HTMLResponse:
    return HTMLResponse(render_all_rows())


@app.get("/steppers", response_class=HTMLResponse)
async def list_steppers() -> HTMLResponse:
    return HTMLResponse(render_all_steppers())


@app.get("/boards", response_class=HTMLResponse)
async def do_scan_boards() -> HTMLResponse:
    return HTMLResponse(render_connection_block())


@app.post("/connect", response_class=HTMLResponse)
async def do_connect(port: str = Form("")) -> HTMLResponse:
    port = port.strip()
    if not port:
        return HTMLResponse(
            f'<div class="header">connect failed: port required</div>'
            f'<div class="board-list">{render_board_list()}</div>'
            f'<div class="toolbar"><button hx-get="/boards" hx-target="#connection" hx-swap="innerHTML">rescan</button></div>'
        )
    disconnect()
    try:
        connect(port)
    except Exception as e:
        return HTMLResponse(
            f'<div class="header">connect failed on {html.escape(port)}: {html.escape(str(e))}</div>'
            f'<div class="board-list">{render_board_list()}</div>'
            f'<div class="toolbar"><button hx-get="/boards" hx-target="#connection" hx-swap="innerHTML">rescan</button></div>'
        )
    return HTMLResponse(render_connection_block())


@app.post("/disconnect", response_class=HTMLResponse)
async def do_disconnect() -> HTMLResponse:
    disconnect()
    return HTMLResponse(render_connection_block())


@app.post("/servo/{channel}/move", response_class=HTMLResponse)
async def do_move(channel: int, angle: float = Form(...), release: str = Form(default="")) -> HTMLResponse:
    servo = get_servo(channel)
    if release:
        servo.move_to_and_release(angle)
    else:
        servo.move_to(angle)
    return HTMLResponse(servo_row(servo))


@app.post("/servo/{channel}/enable", response_class=HTMLResponse)
async def do_enable(channel: int) -> HTMLResponse:
    servo = get_servo(channel)
    servo.set_enabled(True)
    return HTMLResponse(servo_row(servo))


@app.post("/servo/{channel}/disable", response_class=HTMLResponse)
async def do_disable(channel: int) -> HTMLResponse:
    servo = get_servo(channel)
    servo.set_enabled(False)
    return HTMLResponse(servo_row(servo))


@app.post("/servo/{channel}/stop", response_class=HTMLResponse)
async def do_stop(channel: int) -> HTMLResponse:
    servo = get_servo(channel)
    servo.stop()
    return HTMLResponse(servo_row(servo))


@app.post("/servo/{channel}/position", response_class=HTMLResponse)
async def do_position(channel: int) -> HTMLResponse:
    servo = get_servo(channel)
    pos = servo.get_position_deg()
    return HTMLResponse(f"live: {pos:.1f}° (last cmd: {servo.last_angle if servo.last_angle is not None else '—'})")


@app.post("/all/duty", response_class=HTMLResponse)
async def do_all_duty(min_us: int = Form(...), max_us: int = Form(...)) -> HTMLResponse:
    servos = state.get("servos") or []
    try:
        for s in servos:
            s.set_duty_limits_us(min_us, max_us)
    except Exception as e:
        return HTMLResponse(f'<div class="msg err">{html.escape(str(e))}</div>')
    return HTMLResponse(f'<div class="msg ok">duty limits applied to {len(servos)} servos: {min_us}–{max_us}µs</div>')


@app.post("/all/speed", response_class=HTMLResponse)
async def do_all_speed(min_speed: int = Form(...), max_speed: int = Form(...)) -> HTMLResponse:
    servos = state.get("servos") or []
    try:
        for s in servos:
            s.set_speed_limits(min_speed, max_speed)
    except Exception as e:
        return HTMLResponse(f'<div class="msg err">{html.escape(str(e))}</div>')
    return HTMLResponse(f'<div class="msg ok">speed limits applied to {len(servos)} servos</div>')


@app.post("/all/accel", response_class=HTMLResponse)
async def do_all_accel(accel: int = Form(...)) -> HTMLResponse:
    servos = state.get("servos") or []
    try:
        for s in servos:
            s.set_acceleration(accel)
    except Exception as e:
        return HTMLResponse(f'<div class="msg err">{html.escape(str(e))}</div>')
    return HTMLResponse(f'<div class="msg ok">acceleration {accel} applied to {len(servos)} servos</div>')


@app.post("/all/disable", response_class=HTMLResponse)
async def do_all_disable() -> HTMLResponse:
    for s in state.get("servos") or []:
        try:
            s.set_enabled(False)
        except Exception:
            pass
    return HTMLResponse(render_all_rows())


def _oob_msg(kind: str, text: str) -> str:
    cls = "ok" if kind == "ok" else "err"
    return f'<div id="msg" hx-swap-oob="true"><div class="msg {cls}">{html.escape(text)}</div></div>'


@app.post("/stepper/{channel}/move/{direction}", response_class=HTMLResponse)
async def do_stepper_move(channel: int, direction: str, steps: int = Form(...)) -> HTMLResponse:
    stepper = get_stepper(channel)
    signed = abs(int(steps)) * (-1 if direction == "neg" else 1)
    print(f"[tester] move ch{channel} dir={direction} steps={signed} enabled_cached={stepper.enabled}")
    try:
        if not stepper.enabled:
            stepper.set_enabled(True)
            print(f"[tester] ch{channel} enabled ok")
        ok = stepper.move_steps(signed)
        print(f"[tester] ch{channel} move_steps -> {ok}")
    except Exception as e:
        print(f"[tester] ch{channel} ERROR: {e!r}")
        return HTMLResponse(stepper_row(stepper) + _oob_msg("err", f"ch{channel} move failed: {e}"))
    return HTMLResponse(stepper_row(stepper) + _oob_msg("ok", f"ch{channel} moved {signed} steps (firmware ack={ok})"))


@app.post("/stepper/{channel}/enable", response_class=HTMLResponse)
async def do_stepper_enable(channel: int) -> HTMLResponse:
    stepper = get_stepper(channel)
    try:
        stepper.set_enabled(True)
    except Exception as e:
        print(f"[tester] ch{channel} enable ERROR: {e!r}")
        return HTMLResponse(stepper_row(stepper) + _oob_msg("err", f"ch{channel} enable failed: {e}"))
    return HTMLResponse(stepper_row(stepper) + _oob_msg("ok", f"ch{channel} enabled"))


@app.post("/stepper/{channel}/disable", response_class=HTMLResponse)
async def do_stepper_disable(channel: int) -> HTMLResponse:
    stepper = get_stepper(channel)
    try:
        stepper.set_enabled(False)
    except Exception as e:
        print(f"[tester] ch{channel} disable ERROR: {e!r}")
        return HTMLResponse(stepper_row(stepper) + _oob_msg("err", f"ch{channel} disable failed: {e}"))
    return HTMLResponse(stepper_row(stepper) + _oob_msg("ok", f"ch{channel} disabled"))


@app.post("/stepper/{channel}/stop", response_class=HTMLResponse)
async def do_stepper_stop(channel: int) -> HTMLResponse:
    stepper = get_stepper(channel)
    try:
        stepper.move_at_speed(0)
    except Exception as e:
        print(f"[tester] ch{channel} stop ERROR: {e!r}")
        return HTMLResponse(stepper_row(stepper) + _oob_msg("err", f"ch{channel} stop failed: {e}"))
    return HTMLResponse(stepper_row(stepper) + _oob_msg("ok", f"ch{channel} stopped"))


@app.post("/stepper/{channel}/position", response_class=HTMLResponse)
async def do_stepper_position(channel: int) -> HTMLResponse:
    stepper = get_stepper(channel)
    pos = stepper.get_position()
    return HTMLResponse(f"pos: {pos}")


@app.post("/stepper-all/speed", response_class=HTMLResponse)
async def do_stepper_all_speed(min_speed: int = Form(...), max_speed: int = Form(...)) -> HTMLResponse:
    steppers = state.get("steppers") or []
    try:
        for s in steppers:
            s.set_speed_limits(min_speed, max_speed)
    except Exception as e:
        return HTMLResponse(f'<div class="msg err">{html.escape(str(e))}</div>')
    return HTMLResponse(f'<div class="msg ok">speed limits set on {len(steppers)} steppers</div>')


@app.post("/stepper-all/accel", response_class=HTMLResponse)
async def do_stepper_all_accel(accel: int = Form(...)) -> HTMLResponse:
    steppers = state.get("steppers") or []
    try:
        for s in steppers:
            s.set_acceleration(accel)
    except Exception as e:
        return HTMLResponse(f'<div class="msg err">{html.escape(str(e))}</div>')
    return HTMLResponse(f'<div class="msg ok">accel={accel} set on {len(steppers)} steppers</div>')


@app.post("/stepper-all/current", response_class=HTMLResponse)
async def do_stepper_all_current(
    irun: int = Form(...), ihold: int = Form(...), ihold_delay: int = Form(...)
) -> HTMLResponse:
    steppers = state.get("steppers") or []
    try:
        for s in steppers:
            s.set_current(irun, ihold, ihold_delay)
    except Exception as e:
        return HTMLResponse(f'<div class="msg err">{html.escape(str(e))}</div>')
    return HTMLResponse(
        f'<div class="msg ok">current irun={irun} ihold={ihold} delay={ihold_delay} set on {len(steppers)} steppers</div>'
    )


@app.post("/stepper-all/microsteps", response_class=HTMLResponse)
async def do_stepper_all_microsteps(microsteps: int = Form(...)) -> HTMLResponse:
    steppers = state.get("steppers") or []
    try:
        for s in steppers:
            s.set_microsteps(microsteps)
    except Exception as e:
        return HTMLResponse(f'<div class="msg err">{html.escape(str(e))}</div>')
    return HTMLResponse(f'<div class="msg ok">microsteps={microsteps} set on {len(steppers)} steppers</div>')


@app.post("/stepper-all/disable", response_class=HTMLResponse)
async def do_stepper_all_disable() -> HTMLResponse:
    for s in state.get("steppers") or []:
        try:
            s.set_enabled(False)
        except Exception:
            pass
    return HTMLResponse(render_all_steppers())


@app.get("/ports")
async def list_ports() -> JSONResponse:
    return JSONResponse({"ports": enumerate_pico_ports()})


def main() -> None:
    parser = argparse.ArgumentParser(description="Little htmx UI to control servos on a sorter-interface Pico.")
    parser.add_argument("--port", default=None, help="Serial port to auto-connect to (default: none, pick from UI).")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--http-port", type=int, default=8765)
    args = parser.parse_args()

    if args.port:
        try:
            connect(args.port)
            info = state["board_info"]
            print(f"[servo-tester] connected to {state['port']} addr=0x{state['address']:02x} "
                  f"device={info.get('device_name')} servos={info.get('servo_count')}")
        except Exception as e:
            print(f"[servo-tester] --port connect failed: {e}. Pick one from the UI.")

    import socket
    import uvicorn

    http_port = args.http_port
    for _ in range(20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((args.host, http_port))
                break
            except OSError:
                http_port += 1
    print(f"[servo-tester] serving on http://{args.host}:{http_port}")
    uvicorn.run(app, host=args.host, port=http_port, log_level="info")


if __name__ == "__main__":
    main()
