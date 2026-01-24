import threading
from typing import Dict, Any, Literal

VariableType = Literal["int", "float"]

VARIABLE_DEFS: Dict[str, Dict[str, Any]] = {
    "pause_ms": {"type": "float", "min": 0, "max": 2000, "unit": "ms"},
    "v1_pulse_length_ms": {"type": "float", "min": 0, "max": 5000, "unit": "ms"},
    "v1_pulse_speed": {"type": "int", "min": -255, "max": 255, "unit": ""},
    "v2_pulse_length_ms": {"type": "float", "min": 0, "max": 5000, "unit": "ms"},
    "v2_pulse_speed": {"type": "int", "min": -255, "max": 255, "unit": ""},
    "v3_pulse_length_ms": {"type": "float", "min": 0, "max": 5000, "unit": "ms"},
    "v3_pulse_speed": {"type": "int", "min": -255, "max": 255, "unit": ""},
    "slow_v3_pulse_length_ms": {"type": "float", "min": 0, "max": 5000, "unit": "ms"},
    "slow_v3_pulse_speed": {"type": "int", "min": -255, "max": 255, "unit": ""},
}


class RuntimeVariables:
    def __init__(self):
        self._lock = threading.Lock()
        self._values: Dict[str, Any] = {}

    def get(self, key: str) -> Any:
        with self._lock:
            return self._values.get(key)

    def set(self, key: str, value: Any) -> bool:
        if key not in VARIABLE_DEFS:
            return False
        defn = VARIABLE_DEFS[key]
        if defn["type"] == "int":
            value = int(value)
        elif defn["type"] == "float":
            value = float(value)
        value = max(defn["min"], min(defn["max"], value))
        with self._lock:
            self._values[key] = value
        return True

    def getAll(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._values)

    def setAll(self, values: Dict[str, Any]) -> None:
        for key, val in values.items():
            self.set(key, val)


def mkRuntimeVariables(gc) -> RuntimeVariables:
    rv = RuntimeVariables()
    fc = gc.feeder_config
    rv.set("pause_ms", fc.pause_ms)
    rv.set("v1_pulse_length_ms", fc.v1_pulse_length_ms)
    rv.set("v1_pulse_speed", fc.v1_pulse_speed)
    rv.set("v2_pulse_length_ms", fc.v2_pulse_length_ms)
    rv.set("v2_pulse_speed", fc.v2_pulse_speed)
    rv.set("v3_pulse_length_ms", fc.v3_pulse_length_ms)
    rv.set("v3_pulse_speed", fc.v3_pulse_speed)
    rv.set("slow_v3_pulse_length_ms", fc.slow_v3_pulse_length_ms)
    rv.set("slow_v3_pulse_speed", fc.slow_v3_pulse_speed)
    return rv
