import sys
import time

from sorter_bus import SorterBus, Stepper, enumerate_pico_ports


def main() -> None:
    ports = enumerate_pico_ports()
    if not ports:
        print("no Pico detected (VID 0x2E8A / PID 0x000A)")
        sys.exit(1)
    port = ports[0]
    print(f"using port: {port}")

    bus = SorterBus(port, timeout=0.5)
    info = bus.init(0)
    print(f"board: {info}")
    stepper_count = int(info.get("stepper_count", 0))
    print(f"stepper_count from firmware: {stepper_count}")
    if stepper_count == 0:
        print("FIRMWARE REPORTS 0 STEPPERS — flash firmware")
        sys.exit(2)

    ch = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    steps = int(sys.argv[2]) if len(sys.argv) > 2 else 400
    print(f"testing ch{ch}, steps={steps}")

    s = Stepper(bus, 0, ch)
    print(f"enabling driver ch{ch}...")
    s.set_enabled(True)
    time.sleep(0.05)
    print(f"moving {steps} steps on ch{ch}...")
    ok = s.move_steps(steps)
    print(f"firmware ack: {ok}")
    time.sleep(2.0)
    try:
        pos = s.get_position()
        print(f"position after: {pos}")
    except Exception as e:
        print(f"get_position failed: {e}")


if __name__ == "__main__":
    main()
