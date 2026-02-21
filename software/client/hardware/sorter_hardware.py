import logging
from .bus import MCUBus
from .sorter_interface import SorterInterface

class SorterHardware:
    """
    Discovers all connected sorter boards and provides access to steppers, digital inputs, and outputs by logical name.
    Accepts a config object (dict) that can be loaded from TOML.

    """
    def __init__(self, config: dict):
        """
        config: dict with keys 'steppers', 'digital_inputs', 'digital_outputs', each mapping logical names to [board_name, index]
        """
        self._stepper_map = config.get("steppers", {})
        self._digital_input_map = config.get("digital_inputs", {})
        self._digital_output_map = config.get("digital_outputs", {})
        self._interfaces = {}  # board_name -> SorterInterface
        self.steppers = {}         # logical_name -> StepperMotor
        self.digital_inputs = {}   # logical_name -> DigitalInputPin
        self.digital_outputs = {}  # logical_name -> DigitalOutputPin
        self._discover_boards_and_populate()

    def _discover_boards_and_populate(self):
        buses = MCUBus.enumerate_buses()
        if not buses:
            raise RuntimeError("No MCU buses found.")
        found_boards = {}
        for bus_path in buses:
            bus = MCUBus(bus_path)
            for addr in bus.scan_devices():
                try:
                    iface = SorterInterface(bus, addr)
                    found_boards[iface.name] = iface
                except Exception as e:
                    logging.warning(f"Failed to initialize board at {bus_path} addr {addr}: {e}")
        # Check all required boards are present
        required_boards = set()
        for mapping in (self._stepper_map, self._digital_input_map, self._digital_output_map):
            required_boards.update(board_name for board_name, _ in mapping.values())
        missing = required_boards - set(found_boards)
        if missing:
            raise RuntimeError(f"Missing required boards: {missing}")
        self._interfaces = found_boards
        # Populate collections for direct access (only new TOML format supported)
        for logical_name, stepper_cfg in self._stepper_map.items():
            board_name = stepper_cfg["board"]
            stepper_idx = stepper_cfg["index"]
            steps_per_rev = stepper_cfg.get("steps_per_revolution", 200)
            microsteps = stepper_cfg.get("microsteps", 16)
            current_run_percent = stepper_cfg.get("current_run_percent", 100)
            current_hold_percent = stepper_cfg.get("current_hold_percent", 50)
            current_hold_delay = stepper_cfg.get("current_hold_delay", 2)
            stepper_obj = self._interfaces[board_name].steppers[stepper_idx]
            # Inject config using public setters (no hasattr checks)
            stepper_obj.steps_per_revolution = steps_per_rev
            stepper_obj.set_microsteps(microsteps)
            # Map percent (0-100) to 0-31 for irun/ihold, and pass hold_delay as is (0-15)
            irun = int(round((current_run_percent / 100.0) * 31))
            ihold = int(round((current_hold_percent / 100.0) * 31))
            ihold_delay = int(current_hold_delay)
            stepper_obj.set_current(irun, ihold, ihold_delay)
            self.steppers[logical_name] = stepper_obj
        for logical_name, (board_name, input_idx) in self._digital_input_map.items():
            self.digital_inputs[logical_name] = self._interfaces[board_name].digital_inputs[input_idx]
        for logical_name, (board_name, output_idx) in self._digital_output_map.items():
            self.digital_outputs[logical_name] = self._interfaces[board_name].digital_outputs[output_idx]


    def shutdown_all(self):
        for iface in self._interfaces.values():
            iface.shutdown()
