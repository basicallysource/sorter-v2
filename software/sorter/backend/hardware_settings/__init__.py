"""Settings a person changes from the UI or the API that the hardware takes:
the stepper drivers (motors.py, steppers.py), the chute (chute.py) and the
layer servos' speeds (servos.py).

Each setting is declared once, in the module for its device: where
machine.toml keeps it (and the older places that are still read), its range
and default, and how it reaches the hardware. Start-up (irl/config.py) and
every route that changes a setting read, save and apply it through these
modules, so a setting is read back under the name it was saved under, and the
hardware gets it the same way at every start as when it is changed live.
"""
