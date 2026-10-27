# The defaults every sorter starts from

Every setting a person can change on a sorter has a default in the sorter's
code, so a sorter works with no Hive at all. Hive also holds a block of
defaults (`backend/app/services/machine_defaults.py`), so a default can change
across the whole fleet without a sorter release: in Hive's code (a Hive
release), or as an override an admin sets, live. A setting the person saved on
the machine always wins over both.

## The block

`BASE_DEFAULTS` mirrors the sorter's own defaults, namespace by namespace:

| Namespace | What | On the sorter |
|---|---|---|
| `sharing.<stream>` | whether an optional stream is shared | `sharing.py` |
| `steppers.*`, `steppers.<motor>` | each motor's TMC2209 driver settings (`irun`, `ihold`, `ihold_delay`, `microsteps`, `stealthchop`, `coolstep`, `stallguard`, `sgthrs`, `tcoolthrs`) | `hardware_settings/steppers.py` |
| `sample_capture.<setting>` | `enabled`, `interval_s`, `annotate`, `decay_enabled` | `sample_collector.py` |

A sorter layers stepper defaults from the least specific to the most: its code's
for every motor, Hive's `*`, its code's for that motor, Hive's for that motor.
A driver takes its settings at start, so a changed stepper default reaches a
machine at its next start. A value a sorter cannot use (a wrong type, out of
range) is ignored there and the code's default applies.

The block's `version` is a hash of what it holds.

## How a machine gets it

- Every heartbeat reply carries `defaults_version`.
- When the primary Hive's version differs from the one the machine keeps, it
  fetches `GET /api/machine/defaults` (machine token) with the kept version as
  `If-None-Match`; Hive answers 304 when nothing changed.
- The machine keeps the block in its local state (`hive_defaults.py`), so a
  restart with Hive unreachable still uses it. Only the primary Hive's block is
  used.

## Changing a default

- In code: change `BASE_DEFAULTS` (and the sorter's own default, so a machine
  with no Hive agrees), release Hive.
- Live: `PUT /api/admin/machine-defaults` (admin) with `{"path": "steppers.chute.sgthrs", "value": 60}`;
  `"value": null` goes back to Hive's own. An override must name a leaf
  `BASE_DEFAULTS` has and keep its type; one whose leaf Hive's code no longer
  has is ignored. `GET /api/admin/machine-defaults` shows the block served, the
  code's defaults and the overrides (`machine_default_overrides`).

## Adding a namespace

Add it to `BASE_DEFAULTS` with the sorter's current values, and on the sorter
read it through `hive_defaults.value(path, code_default, valid)` where that
setting's default is decided, keeping only what the person chose (as
`sample_collector.py` does), so a machine that never chose follows the default
when it changes.
