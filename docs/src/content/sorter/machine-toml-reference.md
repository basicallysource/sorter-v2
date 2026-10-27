---
layout: default
title: machine.toml Reference
section: sorter
slug: machine-toml-reference
kicker: SorterOS Configuration
lede: All fields for the machine-specific config file, software/machine.toml. MACHINE_SPECIFIC_PARAMS_PATH, if set, points SorterOS at a different file.
permalink: /sorter/machine-toml-reference/
---

## `[servo]`

Controls flap servo angles and hardware backend selection.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `open_angle` | int (0–180) | `10` | Angle in degrees for the open (drop) position. |
| `closed_angle` | int (0–180) | `83` | Angle in degrees for the closed (hold) position. |
| `backend` | `"pca9685"` \| `"waveshare"` | `"pca9685"` | Servo driver to use. `"pca9685"` uses the onboard I²C driver; `"waveshare"` uses the SC bus over USB. |
| `port` | string | auto-detected | Serial port for the Waveshare SC bus. Omit to auto-detect. Only used when `backend = "waveshare"`. |
| `open_speed` | int (1–2000, °/s) | firmware default (1500) | PCA9685 layer servos: speed when a door opens. |
| `close_speed` | int (1–2000, °/s) | firmware default (1500) | PCA9685 layer servos: speed when a door closes. |
| `homing_speed` | int (1–2000, °/s) | firmware default (1500) | PCA9685 layer servos: the standard speed, used at start-up, for homing and for jogging. |

## `[[servo.channels]]`

Per-channel servo configuration. One entry per servo, in layer order. Only used when `backend = "waveshare"`.

The double brackets are TOML's syntax for a list of tables. Write the `[[servo.channels]]` header once for each servo, with that servo's `id` and `invert` under it. The other sections on this page are single tables and use one pair of brackets.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `id` | int \| null | — | SC bus servo ID (1–253). Null skips this slot. |
| `invert` | bool | `false` | Flip the direction of open/closed angles for this servo. |

## `[layers]`

Bin layout — one inner array per physical layer of the tower (bottom to top), each containing bin size strings.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `sections` | array of arrays | — | Each element is a layer; each layer is an array of bin-pair arrays like `["medium","medium"]`. Defines the physical bin topology. |
| `servo_open_angles` | table `{layer_index = angle}` | — | Per-layer open angle overrides. Keys are 0-based layer indices. |
| `servo_closed_angles` | table `{layer_index = angle}` | — | Per-layer closed angle overrides. Keys are 0-based layer indices. |

## `[chute]`

Chute stepper calibration: home pin wiring, aiming geometry and speed. The chute settings pages and the chute aiming calibration save these; a change applies at once and again at every start.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `home_pin_channel` | int | the board's (`3` on the SKR Pico) | Digital input channel index on the distribution board where the chute endstop is wired. Read when the hardware starts. |
| `num_sections` | int | `6` | Bin sections around the chute. |
| `section_width_deg` | float (degrees) | `51.75` | Usable arc of one section, between two pillars. |
| `first_section_offset_deg` | float (degrees) | `8.25` | From home to the start of the first section. |
| `first_bin_center` | float (degrees) | `8.25` | Older name for `first_section_offset_deg`, read when that is absent. Saves keep it in step. |
| `pillar_width_deg` | float (degrees) | `8.25` | Older form of the section width (section pitch minus this), read when `section_width_deg` is absent. Saves keep it in step. |
| `endstop_active_high` | bool | the board's | Set to true if the chute endstop input reads high when physically triggered. |
| `operating_speed_microsteps_per_second` | int | `3000` | Chute stepper top speed. Every chute move sets it, so it holds after jogs and tests. |

## `[carousel]`

Carousel stepper calibration — home pin wiring.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `home_pin_channel` | int | `2` | Digital input channel index on the feeder board where the carousel home sensor is wired. |
| `endstop_active_high` | bool | `false` | Set to true if the carousel home sensor reads high when triggered. |

## `[machine_setup]`

Selects the overall machine topology. Changing this requires a full reset and re-home.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `type` | `"standard_carousel"` \| `"classification_channel"` \| `"manual_carousel"` | `"standard_carousel"` | `"standard_carousel"`: full FIDA + carousel + classification path. `"classification_channel"`: dedicated C-channel classifier. `"manual_carousel"`: operator places parts directly into the carousel. |

## `[stepper_bindings]`

Remaps logical stepper names to physical firmware channel names when the physical wiring does not match the firmware defaults.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `carousel` | string (physical stepper name) | — | Override which physical stepper drives the carousel. |
| `c_channel_1` | string (physical stepper name) | — | Override which physical stepper drives C-channel 1. |
| `c_channel_2` | string (physical stepper name) | — | Override which physical stepper drives C-channel 2. |
| `c_channel_3` | string (physical stepper name) | — | Override which physical stepper drives C-channel 3. |
| `chute` | string (physical stepper name) | — | Override which physical stepper drives the distribution chute. |

## Stepper driver settings

The tables below hold each stepper motor's settings. The UI's driver settings, StallGuard and direction controls save them (`POST /api/stepper/{name}/tmc`, `POST /stepper/{name}/stallguard-config`, `POST /api/setup-wizard/stepper-directions/{name}`). A change applies to the running driver at once, and every start writes every setting to every driver, saved or default.

The per-motor tables key a motor by its stepper name: `chute_stepper`, `carousel`, `c_channel_1_rotor`, `c_channel_2_rotor`, `c_channel_3_rotor`. The older names `first_c_channel_rotor`, `second_c_channel_rotor` and `third_c_channel_rotor` are still read, and the next save moves them under the new name. A motor moved to another socket by `[stepper_bindings]` keeps its settings.

## `[stepper_direction_inverts]`

Flip the logical direction of a stepper without reflashing firmware. Keys are logical stepper names (`carousel`, `c_channel_1`, `c_channel_2`, `c_channel_3`, `chute`). The API's `c_channel_4` is the carousel motor.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `<logical_stepper_name>` | bool | `false` | Set to true to invert CW/CCW for that stepper. Example: `carousel = true` |

## `[stepper_current_overrides.<stepper_name>]`

Per-stepper TMC driver currents. With no entry, the C-channel rotors run at `irun = 4`, `ihold = 1`, the carousel at `irun = 8`, `ihold = 1`, and the chute at `irun = 16`, `ihold = 4`. A key an entry leaves out takes the default below.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `irun` | int (0–31) | `16` | Run current register value. Higher = more torque, more heat. |
| `ihold` | int (0–31) | `4` | Hold current register value when the stepper is stopped. |
| `ihold_delay` | int (0–15) | `8` | Delay (in clock cycles) before current ramps from irun to ihold after a move ends. |

## `[stepper_driver.<stepper_name>]`

Per-stepper TMC driver mode. The control program writes these to each driver at start-up and never changes them by itself while sorting. Saving a change in the stepper settings writes it to the running driver straight away and keeps it in `machine.toml` for the next start.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `microsteps` | int (1, 2, 4 … 256) | `8` | Microsteps per full step. Every speed in µsteps/s scales with it. |
| `stealthchop` | bool | `true` | StealthChop; `false` runs SpreadCycle. |
| `coolstep` | bool | `false` | CoolStep load-adaptive current. Above StallGuard's speed floor when StallGuard is on, at every speed otherwise. |

## `[stepper_stallguard.<stepper_name>]`

Per-stepper stall detection. With no entry, the chute (`sgthrs = 55`) and the carousel (`sgthrs = 148`) have it on with `tcoolthrs = 150`; the other motors have it off.

The chute can tune its own (`auto`, off until it's turned on on the chute's StallGuard tab). While it moves at its operating speed it reads its driver's load figure, and it keeps the speed floor a quarter above the TSTEP of that speed and the threshold far under what normal running reads and far over a stall. When the speed, the current, the microstepping or the chopper mode changes, it learns again. Its StallGuard tab shows what it learned, and says when the chute works harder than it did. A threshold or speed floor saved by hand turns it off.

To tune by hand, use the StallGuard tab of the chute's settings page or the classification channel's. The tab takes it in five steps: check the speed (the chute starts at its operating speed), record the motor running freely, record a stall by holding it back by hand, review and save the threshold and speed floor, and optionally check them.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `enabled` | bool | `true` in an entry | Halt the machine when this motor stalls. |
| `auto` | bool | `false` | Keep `sgthrs` and `tcoolthrs` set from the operating speed and normal running. Only the chute has it. |
| `sgthrs` | int (0–255) | the motor's, else `50` | Stall threshold: a stall is SG_RESULT at or below twice this. |
| `tcoolthrs` | int (0–1048575) | `1048575` in an entry | Speed floor, as TSTEP: stall detection acts only above this speed. |

## `[cameras]`

Camera layout and device index assignments.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `layout` | `"split_feeder"` \| `"default"` | `"split_feeder"` | `"split_feeder"`: separate camera per C-channel + carousel. `"default"`: single feeder camera + classification cameras. |
| `feeder` | int | — | OpenCV device index for the feeder camera. Used in `"default"` layout. |
| `carousel` | int \| string (URL) | — | Device index or MJPEG URL for the carousel/classification camera. |
| `classification_top` | int \| string (URL) | — | Device index or URL for the top classification camera. |
| `classification_bottom` | int \| string (URL) | — | Device index or URL for the bottom classification camera. |
| `c_channel_2` | int | — | Device index for the C-channel 2 camera. Only used in `"split_feeder"` layout. |
| `c_channel_3` | int | — | Device index for the C-channel 3 camera. Only used in `"split_feeder"` layout. |

## `[camera_capture_modes.<role>]`

Per-camera capture settings. Role matches camera keys from `[cameras]` (e.g. `feeder`, `carousel`). Strongly recommended on Linux to force MJPG and avoid USB bandwidth exhaustion.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `fourcc` | string | — | Four-character code for the capture format. `"MJPG"` is strongly recommended on Linux multi-cam setups. |
| `width` | int | — | Capture width in pixels. |
| `height` | int | — | Capture height in pixels. |
| `fps` | int | — | Target capture frame rate. |

## `[camera_picture_settings.<role>]`

Per-camera image transform settings applied after capture.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `rotation` | int (0, 90, 180, 270) | `0` | Clockwise rotation in degrees applied to every captured frame. |
| `flip_horizontal` | bool | `false` | Mirror the image left-to-right. |
| `flip_vertical` | bool | `false` | Flip the image top-to-bottom. |
