# Firmware Changes Since Jose's Last Firmware Commit

Date: 2026-04-15

Scope:
- Baseline commit: `a16bdb5` (`Fix PCA and servo issues, add test code`, Jose, 2026-03-02)
- Compared against `origin/sorthive` at `63420e3`
- Latest firmware-touching commit in this branch: `63420e3` (2026-04-15)
- Path reviewed: `software/firmware/sorter_interface_firmware`

Attribution note:
- The `agent` firmware commits in late March were by Marc Neuhaus.
- The follow-up fix commit `63420e3` is recorded in Git as `Marc Neuhaus`.

Net delta:
- 12 firmware files changed
- 11 non-merge commits after Jose's last firmware commit
- 1 of those 11 was comment-only (`afb6003`)
- Diff size: 313 insertions, 60 deletions

## Executive Summary

After Jose's last firmware commit, the firmware changed in four main ways:

1. Board/config reporting was expanded.
   The detect JSON now advertises logical `stepper_names`, and the build system now supports `feeder` vs `distribution` role variants.

2. Hardware mapping and board-specific behavior changed.
   The SKR Pico channel order, UART addresses, and enable pins were remapped. A fan-on-boot behavior was added and later guarded by board config.

3. Servo handling was changed.
   PCA9685 initialization was rewritten, the I2C bus setup was corrected to use the configured port, and a new `MOVE_TO_AND_RELEASE` servo command was added to stop holding torque after reaching target position.

4. Stepper homing and low-level robustness were changed.
   Homing now expects a logical digital-input channel instead of a raw GPIO number, and stepper motion state used by the ISR was made atomic. TMC UART reads now flush stale RX bytes first.

What did not change:
- No changes to `message.cpp`, `message.h`, `cobs.c`, `cobs.h`, `crc.c`, or `crc.h`
- No changes to the overall bus framing/protocol layer
- No new stepper driver bus commands were added; only one new servo command was added

## Commit Timeline

Substantive firmware commits after `a16bdb5`:

| Date | Commit | Author | Net effect |
| --- | --- | --- | --- |
| 2026-02-25 | `8e5ee05` | Alec | Flush stale UART RX data before TMC register reads |
| 2026-02-28 | `e063209` | Alec | Add stepper names to detect JSON and board configs |
| 2026-03-09 | `8f68af9` | Alec | Add role-based firmware variants (`feeder` / `distribution`) |
| 2026-03-12 | `d053f36` | Spencer | Rewrite PCA9685 init and use configured I2C port |
| 2026-03-12 | `afb6003` | Spencer | Comment-only follow-up to PCA change |
| 2026-03-12 | `ba829d1` | Spencer | Add `SERVO.MOVE_TO_AND_RELEASE` |
| 2026-03-12 | `b027f9a` | Spencer | Change homing input from raw GPIO to logical channel lookup |
| 2026-03-26 | `2ac81eb` | Marc Neuhaus | Force FAN0 on at boot |
| 2026-03-26 | `11f9f4e` | Marc Neuhaus | Rename SKR Pico feeder stepper names to `c_channel_1/2/3` |
| 2026-03-27 | `979cee8` | Marc Neuhaus | Make stepper homing state atomic and add TMC CoolStep helpers |
| 2026-04-15 | `63420e3` | Marc Neuhaus | Guard FAN0 boot enable by board config |

Merge commits in the same range:
- `885672d`
- `a0f7099`

Those merges do not introduce additional net firmware behavior beyond the commits listed above.

## Detailed Changes

### 1. Detect JSON and reported board capabilities

Files:
- `sorter_interface_firmware.cpp`
- `hwcfg_basically.h`
- `hwcfg_skr_pico.h`
- `CMakeLists.txt`

Relevant code:
- `sorter_interface_firmware.cpp:204-273`
- `hwcfg_basically.h:15-40`
- `hwcfg_skr_pico.h:11-36`
- `CMakeLists.txt:36-51`

Changes:
- `dump_configuration()` no longer returns the original payload:
  - Old fields removed from the response:
    - `firmware_version`
    - `device_address`
  - New field added:
    - `stepper_names`
- The detect response now tries multiple progressively smaller JSON payloads to avoid overflowing the bus frame.
- The board config headers now define a logical `STEPPER_NAMES[]` table, which is what gets exposed to the host.
- Builds can now be tagged as `feeder` or `distribution` using `FIRMWARE_ROLE`.
- The default device name now depends on role:
  - `FEEDER MB`
  - `DISTRIBUTION MB`

Impact:
- Host-side device detection changed materially.
- Anything expecting `firmware_version` or `device_address` in the init response will no longer see those fields.
- Host-side actuator binding can now be name-based instead of assuming a fixed channel order.

### 2. Board mapping changes

Files:
- `hwcfg_skr_pico.h`
- `hwcfg_basically.h`

Relevant code:
- `hwcfg_skr_pico.h:1-44`
- `hwcfg_basically.h:1-55`

SKR Pico changes:
- Stepper channel wiring order changed from:
  - step pins `{11, 6, 19, 14}`
  - dir pins `{10, 5, 28, 13}`
  - UART addresses `{0, 2, 1, 3}`
  - enable pins `{12, 7, 2, 15}`
- To:
  - step pins `{14, 11, 6, 19}`
  - dir pins `{13, 10, 5, 28}`
  - UART addresses `{3, 0, 2, 1}`
  - enable pins `{15, 12, 7, 2}`

Current logical SKR Pico feeder names:
- channel 0: `c_channel_1_rotor`
- channel 1: `c_channel_2_rotor`
- channel 2: `c_channel_3_rotor`
- channel 3: `carousel`

Current logical SKR Pico distribution names:
- channel 0: `chute_stepper`
- channel 1: `distribution_aux_1`
- channel 2: `distribution_aux_2`
- channel 3: `distribution_aux_3`

Basically board changes:
- No pin remap was introduced in this range.
- Logical stepper names were added and made role-aware.
- Current feeder naming is:
  - channel 0: `carousel`
  - channel 1: `third_c_channel_rotor`
  - channel 2: `second_c_channel_rotor`
  - channel 3: `first_c_channel_rotor`

Impact:
- On SKR Pico, channel-to-physical-motor mapping changed, not just names.
- This is the biggest hardware-facing change since Jose's last firmware commit.

### 3. I2C and PCA9685 servo controller behavior

Files:
- `sorter_interface_firmware.cpp`
- `PCA9685.cpp`

Relevant code:
- `sorter_interface_firmware.cpp:318-341`
- `PCA9685.cpp:44-73`

Changes:
- I2C init in `initialize_hardware()` now uses `I2C_PORT` instead of hardcoded `i2c0`.
- I2C init speed changed from 100 kHz to 400 kHz.
- PCA9685 init sequence was rewritten:
  - put chip into sleep
  - write prescaler `121` for 50 Hz
  - wake chip
  - enable auto-increment
  - zero all channels
- The PCA zero-out write now starts at `ALL_LED_ON_L`.
- The current code no longer explicitly writes `MODE2_OUTDRV` during initialization.
- The follow-up commit `afb6003` only changed a comment.

Impact:
- This appears intended to make the servo board actually initialize on the configured bus and at a valid servo PWM frequency.
- PCA init behavior is now materially different from Jose's last version.

### 4. New servo command: move, then release

Files:
- `sorter_interface_firmware.cpp`
- `Servo.cpp`
- `Servo.h`

Relevant code:
- `sorter_interface_firmware.cpp:105-128`
- `sorter_interface_firmware.cpp:517-531`
- `Servo.cpp:70-84`
- `Servo.cpp:98-109`
- `Servo.h:39-64`

Changes:
- Added a new command table entry:
  - `SERVO.MOVE_TO_AND_RELEASE`
- Added `Servo::moveToAndRelease(uint16_t position)`.
- Added a `_release_on_idle` flag to the `Servo` class.
- When the target position is reached, the servo now has an optional path that:
  - sets state to `SERVO_DISABLED`
  - zeroes speed and duty state
  - stops outputting PWM

Intent:
- Avoid continuous holding torque and reduce risk of servo damage.

Impact:
- This adds one new firmware command and new servo state behavior.
- Existing `MOVE_TO` behavior is still present.

### 5. Homing command semantics changed

Files:
- `sorter_interface_firmware.cpp`

Relevant code:
- `sorter_interface_firmware.cpp:425-437`

Old behavior:
- The 5th payload byte for `STEPPER.HOME` was effectively treated as a raw GPIO pin number.

Current behavior:
- The 5th payload byte is treated as a logical digital-input channel index.
- Firmware validates `home_pin_channel < DIGITAL_INPUT_COUNT`.
- Firmware converts that channel to the real GPIO using `digital_input_pins[]`.
- Invalid channels now return an error response.

Impact:
- This is a protocol/host contract change.
- Any caller still passing raw GPIO numbers instead of logical input channels will fail or behave differently.

### 6. Stepper ISR state and homing robustness

Files:
- `Stepper.cpp`
- `Stepper.h`

Relevant code:
- `Stepper.h:65-70`
- `Stepper.cpp:58-116`
- `Stepper.cpp:126-170`
- `Stepper.cpp:178-253`

Changes:
- `_mc_dir`, `_mc_home_pin`, and `_mc_home_pin_polarity` were changed to `std::atomic`.
- Code paths were updated to use `.load()` / `.store()` instead of raw member access.
- Homing input is now checked in `stepgen_tick()` at the 10 kHz step rate, not only in the 1 kHz motion update loop.
- When the home input trips, the stepper now immediately:
  - stops
  - zeroes current speed
  - resets absolute position to 0
  - clears `_mc_home_pin`

Impact:
- This is a real runtime change, not just cleanup.
- The main effect is faster endstop reaction and lower risk of ISR/main-core races around homing state.

### 7. TMC communication and driver helpers

Files:
- `TMC_UART.cpp`
- `TMC2209.cpp`

Relevant code:
- `TMC_UART.cpp:171-197`
- `TMC2209.cpp:92-104`

Changes:
- `TMC_UART_Bus::readRegister()` now clears the RX FIFO before starting a read transaction.
- `TMC2209` gained `enableCoolStep()` and `disableCoolStep()` helpers.

Impact:
- The UART FIFO clear is a direct robustness change for register reads.
- The CoolStep helpers are currently not exposed through the firmware command table and are not called during initialization, so they do not change current runtime behavior by themselves.

### 8. Fan behavior at boot

Files:
- `sorter_interface_firmware.cpp`
- `hwcfg_skr_pico.h`
- `hwcfg_basically.h`

Relevant code:
- `sorter_interface_firmware.cpp:310-318`
- `hwcfg_skr_pico.h:49-51`
- `hwcfg_basically.h:54-56`

Changes:
- On 2026-03-26, the firmware was changed to turn FAN0 on at boot for cooling.
- On 2026-04-15, this was corrected to use a board-specific `FAN0_OUTPUT_CHANNEL` constant instead of directly indexing `digital_output_pins[2]`.

Intent:
- Cooling fan runs immediately on boot.

Impact:
- On SKR Pico, the current code enables the output labeled `FAN0`.
- On the Basically board, the current code explicitly disables this behavior by setting `FAN0_OUTPUT_CHANNEL = -1`.
- The original out-of-bounds risk in the shared startup code has been fixed in `63420e3`.

## Review Findings And Current Status

### Fixed since review: FAN0 boot path

Status:
- Fixed in `63420e3`.

What happened:
- The initial fan-on-boot change wrote `digital_output_pins[2]` unconditionally in shared startup code.
- That was unsafe for the Basically board because it only defines two outputs.

Current behavior:
- The firmware now checks `FAN0_OUTPUT_CHANNEL` before writing any boot-time fan output.
- SKR Pico keeps FAN0 enabled at boot.
- Basically skips it safely.

### Open finding 1: `MOVE_TO_AND_RELEASE` has a stale-state bug

Relevant code:
- `Servo.cpp:44-49`
- `Servo.cpp:78-83`
- `Servo.cpp:99-109`
- `Servo.cpp:190-200`
- `Servo.h:62`

Reason:
- `moveTo()` returns `true` while disabled and only updates `_current_pos`.
- `moveToAndRelease()` then sets `_release_on_idle = true`.
- Nothing clears `_release_on_idle` when the servo is later re-enabled or stopped.

Result:
- A later plain `MOVE_TO` can inherit the stale `_release_on_idle` flag and auto-disable at the end even though release was not requested.

Review status:
- Reproduced locally with a standalone C++ harness linked against current `Servo.cpp`.
- Control case (`MOVE_TO`) kept a non-zero duty.
- Poisoned case (`MOVE_TO_AND_RELEASE` while disabled, then later `MOVE_TO`) ended with duty forced to zero.

### Open finding 2: `_release_on_idle` is also a cross-core race

Relevant code:
- `Servo.h:62`
- `sorter_interface_firmware.cpp:525-529`
- `sorter_interface_firmware.cpp:625-629`

Reason:
- `_release_on_idle` is a plain `bool`.
- It is written from the command path on core 0.
- It is read and cleared from the servo update loop on core 1.

Impact:
- This is not just a style concern; it is the same class of cross-core state issue that the stepper code was explicitly hardened against with atomics.

### Open finding 3: role switching can leave the device name stale in CMake cache

Relevant code:
- `CMakeLists.txt:37-50`

Reason:
- `FIRMWARE_ROLE` changes `DEFAULT_DEVICE_NAME`.
- `INIT_DEVICE_NAME` is stored in the CMake cache.
- Reconfiguring the same build directory from `feeder` to `distribution` does not automatically update the cached `INIT_DEVICE_NAME`.

Impact:
- A reused build directory can produce a `distribution` firmware that still reports `FEEDER MB`.

Review status:
- Reproduced locally by configuring one build directory twice and inspecting `CMakeCache.txt`.

### Open finding 4: two firmware contracts changed without versioning

Relevant code:
- `sorter_interface_firmware.cpp:204-273`
- `sorter_interface_firmware.cpp:425-437`

Changes:
- `INIT` detect JSON no longer returns `firmware_version` or `device_address`.
- `STEPPER.HOME` now expects a logical digital-input channel instead of a raw GPIO number.

Impact:
- Current in-repo Python host code appears updated for these changes.
- Older or external host tooling would break or behave differently without a protocol/version bump.

### Likely Jose questions, but not proven bugs from code review

- The PCA9685 init rewrite in `PCA9685.cpp` is a meaningful behavior change and may deserve bench validation, but I did not find a definite correctness failure from source review alone.
- The stepper atomic/home changes look directionally good: they reduce race risk and improve endstop reaction time.
- The TMC UART FIFO flush before reads also looks like a reasonable robustness fix.

## Short Answer Version

If Jose asks for the headline:

"Since your March 2 firmware commit, we did not rewrite the bus layer or message framing. The main changes were role-based board naming and detect JSON, a corrected PCA/I2C servo init path, a new move-and-release servo command, a change in homing input semantics from raw GPIO to logical channel, a remap of SKR Pico motor channels/UART addresses, a fan-on-boot behavior that has since been guarded by board config, and some stepper atomic/endstop timing hardening. The main remaining review concern is the new servo release state handling."

## Verification

I attempted a local firmware build for:
- default feeder configuration
- `HW_SKR_PICO=ON` with `FIRMWARE_ROLE=distribution`

Configuration succeeded, but the local ARM toolchain failed before linking firmware because `arm-none-eabi-gcc` on this machine cannot find `nosys.specs`.

Additional verification:
- I reproduced the servo stale `_release_on_idle` issue with a small standalone C++ harness linked against current `Servo.cpp`.
- I reproduced the CMake cache/device-name issue locally by reconfiguring the same build directory from `feeder` to `distribution`.
- I could not run the backend Python tests in this environment because `pytest` is not installed.

So:
- I verified the change set directly from Git history and current source.
- I confirmed two of the review findings with local targeted repro steps.
- I did not get a successful full firmware binary build in this environment.
