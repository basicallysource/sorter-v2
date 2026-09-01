import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hardware.bus import MCUBus
from hardware.sorter_interface import SorterInterface
import logging

logging.basicConfig(level=logging.WARNING)

class _FakeGC:
    logger = logging.getLogger("probe")

gc = _FakeGC()

buses = MCUBus.enumerate_buses()
if not buses:
    print("No Pico boards found (VID=0x2E8A PID=0x000A)")
    sys.exit(1)

print(f"Found ports: {buses}")

for port in buses:
    print(f"\n--- {port} ---")
    try:
        bus = MCUBus(port)
        dev = SorterInterface(bus, 0, gc)
        print(f"  device: {dev.name}  hw_id: {dev.hw_id}")
        print(f"  digital_inputs: {len(dev.digital_inputs)}")
        for i, pin in enumerate(dev.digital_inputs):
            try:
                val = pin.value
                print(f"  ch{i}: {val}")
            except Exception as e:
                print(f"  ch{i}: ERROR {e}")
    except Exception as e:
        print(f"  ERROR: {e}")
