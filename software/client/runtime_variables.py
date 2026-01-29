import threading
from typing import Dict, Any, Literal

VariableType = Literal["int", "float"]

VARIABLE_DEFS: Dict[str, Dict[str, Any]] = {}


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
    return rv
