import sys

from hardware.bus import MCUBus
from hardware.sorter_interface import SorterInterface
from global_config import mkGlobalConfig


IHOLD_IRUN_REGISTER = 0x10


def decodeIholdIrun(value: int) -> dict[str, int]:
    return {
        "ihold": value & 0x1F,
        "irun": (value >> 8) & 0x1F,
        "ihold_delay": (value >> 16) & 0x0F,
    }


def main() -> int:
    gc = mkGlobalConfig()

    buses = MCUBus.enumerate_buses()
    if not buses:
        print("No Pico boards enumerated (VID=0x2E8A, PID=0x000A). Are they flashed and powered?")
        return 1

    print(f"Found {len(buses)} bus(es): {buses}")
    total_steppers = 0

    for port in buses:
        print(f"\n=== Bus: {port} ===")
        try:
            bus = MCUBus(port=port)
        except Exception as e:
            print(f"  failed to open: {e}")
            continue

        addrs = bus.scan_devices()
        if not addrs:
            print("  no devices responded to ping")
            continue
        print(f"  device addresses: {addrs}")

        for addr in addrs:
            try:
                iface = SorterInterface(bus, addr, gc)
            except Exception as e:
                print(f"  addr {addr}: init failed: {e}")
                continue

            print(f"  device '{iface.name}' (addr={addr}, steppers={len(iface.steppers)}):")
            for i, stepper in enumerate(iface.steppers):
                total_steppers += 1
                try:
                    raw = stepper.read_driver_register(IHOLD_IRUN_REGISTER)
                except Exception as e:
                    print(f"    ch{i}: read failed: {e}")
                    continue
                decoded = decodeIholdIrun(raw)
                print(
                    f"    ch{i}: raw=0x{raw:08X}  "
                    f"irun={decoded['irun']:>2}  "
                    f"ihold={decoded['ihold']:>2}  "
                    f"ihold_delay={decoded['ihold_delay']:>2}"
                )

    print(f"\nTotal steppers probed: {total_steppers}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
