---
layout: default
title: Running without the chute and layers
type: how-to
audience: operator
applies_to: Sorter V2 local software
owner: sorter
slug: sorter-run-without-distribution
kicker: "SorterOS: Operate"
lede: Test the feeder and the classification channel before the chute, layers and bins are built, by switching the rest off in software.
permalink: /sorter/run-without-distribution/
warning: >-
  **AI-generated first draft.** Written from SorterOS's own source, not from
  running a machine with the chute left off. The one limit on this page, that
  Home still homes the chute, is read from the code and has not been tried on
  hardware.
---

The machine does not have to be finished to run. The feeder (C1 to C3) and the classification channel (C4) are the part that sees and identifies pieces; the chute, the layers and the bins only receive what it decides. You can switch those off in software and test the front half on its own.

The setup wizard is not a gate. Every step can be opened in any order, and the dashboard is at the machine's own address whether or not the wizard was finished. Nothing has to be calibrated for hardware you have not built, but the wizard's steps for it will stay unfinished, so ignore them.

## What the feeder and C4 still need

- **Cameras** on C2, C3 and the classification channel (C4). C1 has no camera. See [First setup in the UI]({{ '/sorter/first-setup/' | relative_url }}), step 7.
- **Their steppers**, wired and found by the wizard's hardware step.
- **[Camera calibration]({{ '/sorter/camera-calibration/' | relative_url }})** if you want the pictures sharp enough to identify pieces.

Pieces end up at the exit of C4. Put a container under it.

## The switches

Each part is switched off with a name. You can give several, separated by commas:

| Name | What it switches off |
|---|---|
| `chute` | The chute. Moves are worked out and logged as `[DISABLED] would move`, but the stepper does not turn. |
| `servos` | The layer door servos. They are not opened at start, and the machine no longer waits for a door to finish moving before it carries on. |
| `c_channel_1`, `c_channel_2`, `c_channel_3`, `c_channel_4` | That channel's rotor motor. It is never driven. |
| `carousel` | The carousel stepper, which is the same motor as `c_channel_4`. |

For a machine with no distribution section, switch off `chute` and `servos`.

## Setting them

Add one line to the `.env` file in the `software` folder of the machine's install:

```bash
export LEGOSORTER_DISABLE=chute,servos
```

The file is read when the backend starts, so restart it. A soft restart from the UI does not re-read `.env`; use a full one:

```bash
sudo systemctl restart sorter-backend-dev.service
```

If you start the machine by hand with `./dev.sh`, press Ctrl-C and start it again. See [Dev flow]({{ '/sorter/dev-flow/' | relative_url }}) for the difference between the two kinds of restart.

The backend also takes the same names as a command-line option, `--disable chute --disable servos`, when you run it yourself.

To switch a part back on, remove it from the line and restart again.

## Known limit: Home still homes the chute

**Home** on the dashboard starts the hardware and moves every axis to its zero, and the chute is one of them. Switching the chute off stops it moving while sorting; it does not stop it being homed. With no chute built, that step times out, the machine goes to an error state, and you cannot go on to a test run.

Until that changes, the front half can be tested on a machine whose chute is built and homes normally, with only the layers switched off.
