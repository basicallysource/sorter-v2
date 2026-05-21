---
layout: default
title: machine.toml Reference
section: sorter
slug: machine-toml-reference
kicker: Sorter Configuration
lede: All fields for the machine-specific config file. Set MACHINE_SPECIFIC_PARAMS_PATH to point to your copy.
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

## `[[servo.channels]]`

Per-channel servo configuration. One entry per servo, in layer order. Only used when `backend = "waveshare"`.

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

Chute stepper calibration — home pin wiring and bin layout geometry.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `home_pin_channel` | int | `3` | Digital input channel index on the distribution board where the chute endstop is wired. |
| `first_bin_center` | float (degrees) | `8.25` | Angular position of the first bin center after homing completes. |
| `pillar_width_deg` | float (degrees) | `8.25` | Angular width consumed by each divider pillar between bins. |
| `endstop_active_high` | bool | `true` | Set to true if the chute endstop input reads high when physically triggered. |
| `operating_speed_microsteps_per_second` | int | `3000` | Chute stepper top speed during normal positioning moves. |

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

## `[stepper_direction_inverts]`

Flip the logical direction of a stepper without reflashing firmware. Keys are logical stepper names (`carousel`, `c_channel_1`, `c_channel_2`, `c_channel_3`, `chute`).

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `<logical_stepper_name>` | bool | `false` | Set to true to invert CW/CCW for that stepper. Example: `carousel = true` |

## `[stepper_current_overrides.<stepper_name>]`

Per-stepper TMC driver current settings. Omit to use firmware defaults. Keys are physical or canonical stepper names.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `irun` | int (0–31) | `16` | Run current register value. Higher = more torque, more heat. |
| `ihold` | int (0–31) | `4` | Hold current register value when the stepper is stopped. |
| `ihold_delay` | int (0–15) | `8` | Delay (in clock cycles) before current ramps from irun to ihold after a move ends. |

## `[cameras]`

Camera layout and device index assignments.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `layout` | `"default"` \| `"split_feeder"` | `"default"` | `"default"`: single feeder camera + classification cameras. `"split_feeder"`: separate camera per C-channel + carousel. |
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

## `[[gpio_leds]]`

Digital output pins that are driven HIGH on boot and LOW on shutdown. One entry per pin. Useful for status LEDs wired to the basically or SKR Pico boards.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `board` | `"feeder"` \| `"distribution"` \| `"any"` | — | Which board to target. `"any"` applies the same pin index to all connected boards. |
| `pin` | int (≥ 0) | — | 0-based digital output channel index on the target board. |
