import sys
import time
import csv
import argparse
from datetime import datetime
from pathlib import Path

CLIENT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CLIENT_ROOT))

from dotenv import load_dotenv
load_dotenv(CLIENT_ROOT.parent / ".env")

from global_config import mkGlobalConfig
from irl.config import mkIRLConfig, mkIRLInterface

TMC_REG_TCOOLTHRS = 0x14
TMC_REG_SGTHRS = 0x40
TMC_REG_SG_RESULT = 0x41
TMC_REG_DRV_STATUS = 0x6F
TMC_REG_TSTEP = 0x12

LOGS_DIR = CLIENT_ROOT / "logs"


DUMP_REGS = [
    ("GCONF", 0x00),
    ("IHOLD_IRUN", 0x10),
    ("TPOWERDOWN", 0x11),
    ("TPWMTHRS", 0x13),
    ("TCOOLTHRS", 0x14),
    ("SGTHRS", 0x40),
    ("COOLCONF", 0x42),
    ("CHOPCONF", 0x6C),
    ("DRV_STATUS", 0x6F),
    ("PWMCONF", 0x70),
]


def dumpRegisters(carousel, path):
    lines = []
    for name, addr in DUMP_REGS:
        val = carousel.read_driver_register(addr)
        line = f"{name:15s} (0x{addr:02X}) = 0x{val:08X}"
        lines.append(line)
        print(f"  {line}")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  -> {path}")


def connectCarousel():
    gc = mkGlobalConfig()
    irl_config = mkIRLConfig()
    irl = mkIRLInterface(irl_config, gc)
    irl.enableSteppers()
    return irl, irl.carousel_stepper, gc


def modeTune(args):
    irl, carousel, gc = connectCarousel()
    LOGS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = LOGS_DIR / f"stallguard_tune_{timestamp}.csv"

    print(f"StallGuard tuning mode")
    print(f"  speed:      {args.speed} usteps/s")
    print(f"  duration:   {args.duration}s")
    print(f"  sample_hz:  {args.sample_hz}")
    print(f"  tcoolthrs:  0x{args.tcoolthrs:05X}")
    print(f"  output:     {out_path}")
    print()

    carousel.write_driver_register(TMC_REG_TCOOLTHRS, args.tcoolthrs)

    sample_interval = 1.0 / args.sample_hz
    rows = []

    print("Starting motor...")
    carousel.move_at_speed(args.speed)
    time.sleep(0.3)

    print(f"Sampling SG_RESULT for {args.duration}s (Ctrl+C to stop early)...")
    print()
    t_start = time.time()
    try:
        while time.time() - t_start < args.duration:
            t_sample = time.time() - t_start
            sg_result = carousel.read_driver_register(TMC_REG_SG_RESULT)
            drv_status = carousel.read_driver_register(TMC_REG_DRV_STATUS)
            cs_actual = (drv_status >> 16) & 0x1F
            tstep = carousel.read_driver_register(TMC_REG_TSTEP)
            rows.append({
                "t": round(t_sample, 4),
                "sg_result": sg_result,
                "cs_actual": cs_actual,
                "tstep": tstep,
            })
            bar_len = min(sg_result // 4, 60)
            bar = "#" * bar_len
            print(f"\r  t={t_sample:6.2f}  SG={sg_result:4d}  CS={cs_actual:2d}  TSTEP={tstep:6d}  |{bar:<60}|", end="", flush=True)
            elapsed = time.time() - t_start - t_sample
            remaining = sample_interval - elapsed
            if remaining > 0:
                time.sleep(remaining)
    except KeyboardInterrupt:
        print("\nStopped early.")

    print("\nStopping motor...")
    carousel.move_at_speed(0)
    time.sleep(0.5)

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["t", "sg_result", "cs_actual", "tstep"])
        writer.writeheader()
        writer.writerows(rows)

    if rows:
        sg_vals = [r["sg_result"] for r in rows]
        sg_min = min(sg_vals)
        sg_avg = sum(sg_vals) / len(sg_vals)
        suggested = max(1, int(sg_min * 0.4) // 2)
        print(f"\nResults ({len(rows)} samples):")
        print(f"  SG_RESULT  min={sg_min}  max={max(sg_vals)}  avg={sg_avg:.0f}")
        print(f"  Suggested SGTHRS: {suggested}  (triggers when SG_RESULT <= {suggested * 2})")
        print(f"  Your unloaded min is {sg_min}, so stall must drop below {suggested * 2} to trigger")
    print(f"\nSaved to {out_path}")

    cleanup(irl, carousel)


def sgthrsFromLastTune():
    tune_files = sorted(LOGS_DIR.glob("stallguard_tune_*.csv"))
    if not tune_files:
        return None
    last = tune_files[-1]
    with open(last, newline="") as f:
        reader = csv.DictReader(f)
        sg_vals = [int(row["sg_result"]) for row in reader]
    if not sg_vals:
        return None
    sg_min = min(sg_vals)
    suggested = max(1, int(sg_min * 0.4) // 2)
    print(f"Read {last.name}: min SG_RESULT={sg_min}, auto SGTHRS={suggested}")
    return suggested


def modeStall(args):
    if args.sgthrs is None:
        args.sgthrs = sgthrsFromLastTune()
        if args.sgthrs is None:
            print("No --sgthrs provided and no tune CSV found. Run 'tune' first or pass --sgthrs.")
            return

    irl, carousel, gc = connectCarousel()
    LOGS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = LOGS_DIR / f"stallguard_stall_{timestamp}.csv"
    dump_before = LOGS_DIR / f"stallguard_regs_before_{timestamp}.txt"
    dump_after = LOGS_DIR / f"stallguard_regs_after_{timestamp}.txt"

    print(f"StallGuard stall detection mode")
    print(f"  speed:      {args.speed} usteps/s")
    print(f"  sgthrs:     {args.sgthrs}")
    print(f"  tcoolthrs:  0x{args.tcoolthrs:05X}")
    print(f"  output:     {out_path}")
    print()

    print("Registers BEFORE:")
    dumpRegisters(carousel, dump_before)
    print()

    print("Motor will run until stall detected or Ctrl+C.")
    print("Try applying load to the carousel to trigger stall.")
    print()

    rows = []
    try:
        carousel.move_at_speed(args.speed)
        time.sleep(0.5)
        carousel.configureStallGuard(sgthrs=args.sgthrs, tcoolthrs=args.tcoolthrs)

        t_start = time.time()
        while True:
            t_sample = time.time() - t_start
            sg = carousel.read_driver_register(TMC_REG_SG_RESULT)
            stalled = carousel.getStallStatus()
            rows.append({"t": round(t_sample, 4), "sg_result": sg, "stalled": int(stalled)})
            bar_len = min(sg // 4, 60)
            bar = "#" * bar_len
            print(f"\r  SG={sg:4d}  thresh={args.sgthrs * 2:4d}  |{bar:<60}|", end="", flush=True)
            if stalled:
                print(f"\n\nSTALL DETECTED! SG_RESULT was {sg}")
                print(f"Motor stopped by firmware at position {carousel.position_degrees:.2f} deg")
                # Stall recovery procedure
                carousel.enableStallDetection(False)
                carousel.write_driver_register(TMC_REG_TCOOLTHRS, 0)
                carousel.write_driver_register(TMC_REG_SGTHRS, 0)
                # 1. Back off slowly to release tension
                print("Backing off...")
                carousel.move_degrees(10)
                while not carousel.stopped:
                    time.sleep(0.01)
                # 2. Standstill at run current for AT#1 (>130ms)
                time.sleep(0.3)
                # 3. Short move for AT#2 re-tune
                print("Re-tuning StealthChop...")
                carousel.move_degrees(-45)
                while not carousel.stopped:
                    time.sleep(0.01)
                time.sleep(0.2)
                break
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        cleanup(irl, carousel)

    print("\nRegisters AFTER cleanup:")
    dumpRegisters(carousel, dump_after)
    try:
        irl.shutdown()
    except Exception:
        pass

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["t", "sg_result", "stalled"])
        writer.writeheader()
        writer.writerows(rows)

    if rows:
        sg_vals = [r["sg_result"] for r in rows]
        print(f"\nResults ({len(rows)} samples, sgthrs={args.sgthrs}):")
        print(f"  SG_RESULT  min={min(sg_vals)}  max={max(sg_vals)}  avg={sum(sg_vals)/len(sg_vals):.0f}")
    print(f"Saved to {out_path}")


def modeStep(args):
    irl, carousel, gc = connectCarousel()
    LOGS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = LOGS_DIR / f"stallguard_step_{timestamp}.csv"

    print(f"StallGuard step mode (-90 deg rotations)")
    print(f"  pause:      {args.pause}s between moves")
    print(f"  tcoolthrs:  0x{args.tcoolthrs:05X}")
    print(f"  output:     {out_path}")
    print(f"  Ctrl+C to stop")
    print()

    carousel.write_driver_register(TMC_REG_TCOOLTHRS, args.tcoolthrs)

    rows = []
    t_start = time.time()
    move_num = 0
    try:
        while True:
            move_num += 1
            print(f"\n--- Move {move_num}: -90 deg ---")
            carousel.move_degrees(-90)
            while not carousel.stopped:
                t_sample = time.time() - t_start
                sg = carousel.read_driver_register(TMC_REG_SG_RESULT)
                rows.append({"t": round(t_sample, 4), "sg_result": sg, "move": move_num, "moving": 1})
                bar_len = min(sg // 4, 60)
                bar = "#" * bar_len
                print(f"\r  t={t_sample:6.2f}  SG={sg:4d}  |{bar:<60}|", end="", flush=True)
                time.sleep(0.03)
            print(f"\r  Move {move_num} done. Pausing {args.pause}s...")
            time.sleep(args.pause)
    except KeyboardInterrupt:
        print("\nStopped by user.")

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["t", "sg_result", "move", "moving"])
        writer.writeheader()
        writer.writerows(rows)

    if rows:
        sg_vals = [r["sg_result"] for r in rows]
        print(f"\nResults ({len(rows)} samples across {move_num} moves):")
        print(f"  SG_RESULT  min={min(sg_vals)}  max={max(sg_vals)}  avg={sum(sg_vals)/len(sg_vals):.0f}")
    print(f"Saved to {out_path}")

    cleanup(irl, carousel)


def modeRead(args):
    irl, carousel, gc = connectCarousel()

    print(f"Live StallGuard register read (no motor movement)")
    print(f"Reading DRV_STATUS and SG_RESULT. Ctrl+C to stop.")
    print()

    carousel.write_driver_register(TMC_REG_TCOOLTHRS, args.tcoolthrs)

    try:
        while True:
            sg = carousel.read_driver_register(TMC_REG_SG_RESULT)
            drv = carousel.read_driver_register(TMC_REG_DRV_STATUS)
            cs = (drv >> 16) & 0x1F
            stst = (drv >> 31) & 1
            stealth = (drv >> 30) & 1
            ot = drv & 0x03
            print(f"\r  SG={sg:4d}  CS_ACTUAL={cs:2d}  standstill={stst}  stealthchop={stealth}  ot_flags=0x{ot:02X}", end="", flush=True)
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nDone.")

    cleanup(irl, carousel)


def cleanup(irl, carousel):
    try:
        carousel.move_at_speed(0)
    except Exception:
        pass
    try:
        carousel.write_driver_register(TMC_REG_TCOOLTHRS, 0)
        carousel.write_driver_register(TMC_REG_SGTHRS, 0)
        carousel.enableStallDetection(False)
        carousel.write_driver_register(0x01, 0x07)  # Clear GSTAT
        print("  [cleanup] registers cleared, stall detection disabled")
    except Exception as e:
        print(f"  [cleanup] FAILED: {e}")
    try:
        irl.disableSteppers()
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="StallGuard4 test tool for carousel stepper")
    parser.add_argument("mode", choices=["tune", "stall", "step", "read"],
                        help="tune: log SG_RESULT to CSV | stall: run with stall detection | step: -90 deg rotations | read: live register dump")
    parser.add_argument("--speed", type=int, default=-500, help="Motor speed in usteps/s, negative=normal carousel direction (default: -500)")
    parser.add_argument("--duration", type=float, default=10.0, help="Sampling duration in seconds, tune mode (default: 10)")
    parser.add_argument("--sample-hz", type=float, default=20, help="Samples per second, tune mode (default: 20)")
    parser.add_argument("--sgthrs", type=int, default=None, help="SGTHRS threshold, stall mode (auto from last tune CSV if omitted)")
    parser.add_argument("--tcoolthrs", type=lambda x: int(x, 0), default=2000, help="TCOOLTHRS register value, lower velocity threshold for StallGuard (default: 2000)")
    parser.add_argument("--pause", type=float, default=1.0, help="Pause between moves in step mode (default: 1.0s)")
    args, _ = parser.parse_known_args()

    sys.argv = sys.argv[:1]

    if args.mode == "tune":
        modeTune(args)
    elif args.mode == "stall":
        modeStall(args)
    elif args.mode == "step":
        modeStep(args)
    elif args.mode == "read":
        modeRead(args)


if __name__ == "__main__":
    main()
