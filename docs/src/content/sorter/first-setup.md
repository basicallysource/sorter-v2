---
layout: default
title: First setup in the UI
type: how-to
audience: operator
applies_to: Sorter V2 local software
owner: sorter
slug: sorter-first-setup
kicker: SorterOS — Operate
lede: The setup wizard step by step, from opening the machine's UI in a browser to a machine ready for its first sort run.
permalink: /sorter/first-setup/
warning: >-
  **SorterOS changes quickly.** This page describes what each step does, but a
  button's name, or where it is, may have changed since this page was written.
contributors: [brickcyclealice]
last_verified: 2026-10-22
---

The software is installed and the machine has booted. This page takes you from opening its UI in a browser to a machine that is ready to sort. Everything here happens in the browser, so there are no commands to type.

## Before you start

- The machine is the standard Sorter V2, built from the [parts calculator](https://parts-calculator.basically.website/): C-channels 1 to 3 feed the pieces, C-channel 4 is the classification channel, and the chute drops each piece into its bin. This is the only build SorterOS sets up, so there is no build to choose in the UI.
- The machine is assembled, wired and powered on.
- SorterOS is installed and running. See [Installation]({{ '/sorter/installation/' | relative_url }}).
- **The control board is flashed.** Step 3 below only lists boards that already answer on USB serial, so a board with no firmware on it does not appear there at all. [Flashing the control board]({{ '/sorter/' | relative_url }}#flash-the-control-board-before-the-wizard) has the route, including the one for a board that has never been flashed.
- Your phone, tablet or computer is on the same network as the machine.
- The machine is empty: no parts in the C-channels or the chute. The wizard turns the motors.
- Nothing is resting against the chute or the C-channels.

Set aside about an hour. You can stop between steps and come back later.

## Open the UI

Type the machine's address into your browser. Which address depends on how you installed the software:

| Install | Address |
|---|---|
| SorterOS image | `http://sorter.local/` |
| Generic Linux as a service (`install.sh --as-service`) | `http://<machine name>/` |
| Generic Linux with `./dev.sh`, or by hand | `http://<machine name>:5173/` |

If you gave the machine a different hostname during the install, use that name instead of `sorter`. If no `.local` address answers, use the machine's IP address from your router.

**Type the `http://` part.** The machine only answers on `http`. Some browsers change the address to `https://` by themselves, and then the page does not load. Check the address bar for an extra `s`, and remove it.

There is nothing to log into. The machine UI has no account and no password, so anyone on your network who opens the address sees the same screens you do. The only sign-in on this page is Hive, in step 8, and that is optional.

If the page does not appear at all, or it appears and every button fails, see [SorterOS troubleshooting]({{ '/sorter/troubleshooting/' | relative_url }}).

**The first time you open the UI it shows the setup wizard.** Leave it for now: update the software first, then open the wizard again. Open **Settings** from the bar at the top of the page. On a narrow screen it is in the **Pages** menu there.

## Update the software first

The software changes often, so the version on a new machine can be weeks old. Update it before you start the wizard.

<ol class="numbered-steps">
  <li>Open <strong>Settings</strong>, then <strong>Versions</strong>.</li>
  <li>Press <strong>Check for updates</strong>, at the top of the <strong>This machine</strong> panel.</li>
  <li>Read the bottom of that panel. If it says <strong>Up to date.</strong>, there is nothing to do. If it says <strong>A new version is out</strong>, press <strong>Update</strong>.</li>
  <li>Wait. The machine gets the new version, builds it and restarts, which takes a few minutes. If the page goes blank, wait five minutes, then reload it.</li>
</ol>

The same panel says which version you are on: **Channel** is the release the machine follows, and **Commit** and **Made** are the version and its date. Give all three when you ask for help.

**Stable or canary.** The **Release channels** panel lists both. **Stable** is the tested release. **Canary** is newer and less tested. Stay on stable unless a fix you need is only on canary. Switching keeps your settings and data, but once you are on canary you cannot switch back to stable until stable catches up.

## Open the setup wizard

Open **Settings** → **General** → **Open the setup wizard**, or add `/setup` to the machine's address (`http://sorter.local/setup`). This is also how you get back to it after it is finished.

<div class="img-row">
  <figure><img src="https://assets.basically.website/sorter-docs/sorter-first-setup-step1-machine-identity-w1600-08182bfeebd0.jpg" alt="The setup wizard on step 1, with the nine steps along the top and a machine name field below"><figcaption>The wizard on its first step. <cite>UI screenshot. Render: Balloon.</cite></figcaption></figure>
</div>

- The nine steps run along the top. The one you are on is highlighted.
- **Continue** at the bottom takes you to the next step. When it is greyed out, the line beside it says what is still missing.
- A step stays locked until the steps before it are done.
- You can close the browser and come back. The wizard remembers how far you got on this machine.

## Step 1: Machine identity

Type a name for the machine and press **Continue**. The name is how the machine appears in the machine picker at the top of the UI, and in Hive if you connect it later.

**Generate New Name** beside the field invents one for you if you would rather not think of one.

The machine ID above the field is generated by the machine. Leave it as it is.

**Continue** stays greyed out until the name field has something in it.

## Step 2: Your color

Pick a LEGO color. The buttons, highlights and focus rings in the UI switch to it immediately.

<div class="img-row">
  <figure><img src="https://assets.basically.website/sorter-docs/sorter-first-setup-step2-your-color-w1600-849a98b191c9.jpg" alt="Step 2 of the wizard, showing a grid of LEGO colors with one selected"><figcaption>Step 2. The picked color is named under the grid. <cite>UI screenshot. Render: Balloon.</cite></figcaption></figure>
</div>

You can change it later under **Settings** → **Connection & Appearance** → **Theme color**.

## Step 3: Controller discovery

The wizard lists the USB controllers it can see, and uses the ones it recognises. On a machine built from these docs that is one device: the control board, which drives the chute, all four channel rotors and the flap servos. There is no separate servo device to find.

A recognised device has a green **Controller** badge, its board type, and the port it is on.

**Nothing listed, or the control board missing?** In order:

<ol class="numbered-steps">
  <li><strong>The board has no firmware on it.</strong> This is the usual cause on a new machine, and an unflashed board cannot appear here. Flash it, then come back. <a href="{{ '/sorter/' | relative_url }}#flash-the-control-board-before-the-wizard">Flashing the control board</a>.</li>
  <li><strong>The machine is not powered, or the board's USB cable (<code>USB6</code>) is not in.</strong> The cable runs from the Pico's own socket to a port on the USB hub.</li>
  <li>Press <strong>Rescan</strong>.</li>
</ol>

A device badged red **Unrecognised** is one the machine can see but cannot place: it is on the bus, so the cable and the power are fine.

The wizard's own wording, and the screenshot below, still name a feeder and a distribution board, because the software also supports the older machines that had one of each. On this build the single board reports as the distribution one.

**Continue** is blocked with "Waiting for controller boards to be detected" until at least one control board is found.

<div class="img-row">
  <figure><img src="https://assets.basically.website/sorter-docs/sorter-first-setup-step3-no-controllers-w1600-af69c0723983.jpg" alt="Step 3 of the wizard with no controllers found, showing a red panel listing missing steppers and a Rescan button"><figcaption>Step 3 when the machine can see no control boards at all. <cite>UI screenshot. Render: Balloon.</cite></figcaption></figure>
</div>

## Step 4: Motion direction check

This step turns the motors a little to check which way each one runs. The steppers power on when you open the step: wait for "Powering on the steppers…" to clear before you press anything.

One card per axis: C-Channel 1, C-Channel 2, C-Channel 3, C-Channel 4 and the Chute. Each card has a picture of that axis seen from above, with an arrow showing clockwise.

<ol class="numbered-steps">
  <li>Press <strong>Jog</strong> on the first card. The axis moves a small amount.</li>
  <li>Look down on it from above, then press <strong>Clockwise</strong> or <strong>Counterclockwise</strong> to say which way it turned. On a C-channel, watch the rotor, the part the pieces ride on.</li>
  <li>The card reads <strong>Checked</strong>. If it turned counterclockwise, the wizard reverses that motor in software and the card reads <strong>Inverted</strong>. That is expected: the motor is wired the other way round.</li>
  <li>Repeat for every card.</li>
</ol>

**Show the wiring** opens a diagram of the control board and a list of which stepper port each axis uses. Use it if an axis does not move at all.

When every card is checked, press **Directions look correct**.

## Step 5: Chute endstop and geometry

The chute has a sensor at its home position. Here you check that the machine reads it the right way round, then let the chute find home. The wizard checks only the chute here.

<ol class="numbered-steps">
  <li>Trigger the chute's endstop by hand. The <strong>Chute endstop</strong> row should read <strong>Triggered</strong>.</li>
  <li>If it stays <strong>Not triggered</strong>, press <strong>Flip the polarity</strong> and trigger it again.</li>
  <li>Press <strong>Find the chute endstop</strong>. The chute turns until it finds its sensor and stops. Seen from above, it should turn counter-clockwise, so it reaches the sensor from the clockwise side. If it runs the other way, press <strong>Stop the motion</strong>, then <strong>Flip the direction</strong>, and try again.</li>
  <li>Press <strong>Chute endstop and geometry look correct</strong>.</li>
</ol>

<div class="img-row">
  <figure><img src="https://assets.basically.website/sorter-docs/sorter-first-setup-step5-chute-homing-direction-full-b77a67a68ff7.png" alt="Top-down diagram of the machine: the chute in the middle of a ring of bins, its funnel on one side and a hammer-shaped tab on the other. A green arrow takes the funnel counter-clockwise to where it ends at home, a dashed outline at the section left of the control board, while the hammer turns counter-clockwise to the home switch above the PSU. A crossed-out red arrow off the funnel turns clockwise."><figcaption>Which way the chute should turn when it finds the endstop, seen from above. Watch the funnel: the hammer on the far side of the chute is what presses the switch. <cite>Diagram. Render: Balloon.</cite></figcaption></figure>
</div>

**Stop the motion** halts the chute at once. **Show the wiring** shows which header on the control board the endstop plugs into.

Leave **First bin center** and **Pillar width** at the values already in the fields. They are saved when you continue, and you set them properly later, on [Homing and calibrating the chute]({{ '/sorter/chute-calibration/' | relative_url }}).

## Step 6: Servo configuration

Each storage layer has a flap in the chute, driven by a servo. Closed, the flap crosses the chute and pieces slide into that layer's bins. Open, it lies flat in the chute wall and pieces fall past to the layers below.

On the standard control board the servos run from the board itself. The step says **No Waveshare servo bus found, so a PCA9685 on a control board is assumed**, and shows the same flap panel as **Settings → Storage layers**.

<ol class="numbered-steps">
  <li>Press <strong>Add a layer</strong> once for each layer, and set each layer's <strong>Bins</strong> to the bins fitted on it.</li>
  <li>Turn on <strong>Advanced</strong>, beside <strong>Add a layer</strong>. Each layer's <strong>Channel</strong> box only shows while it is on. Pick the servo channel that layer's flap is plugged into.</li>
  <li>Press <strong>Save the layers</strong>. Then restart the backend: the <strong>⋯</strong> menu at the top right, then <strong>Restart the backend</strong>. A layer you added, or whose <strong>Bins</strong> you changed, only takes effect after a restart. Homing alone is not enough, even though the page says to home.</li>
  <li>When the page is back, home the machine from the same menu: <strong>Home</strong> (<strong>Re-home</strong> if it has homed before). A flap cannot move until then.</li>
  <li>For each layer, move the flap with the arrows until it lies flat in the chute wall, then press <strong>Lock open</strong>. Then move it until it crosses the chute and nothing can fall past, and press <strong>Lock closed</strong>. The layer reads <strong>Calibrated</strong> once both are locked.</li>
</ol>

**You need a torch** to see the flaps inside the chute. It is easier with one section opened up: in the section the chute points at, lift out the bins and slide each layer's funnel off its brackets. Neither is screwed in. Then shine the torch in at the flaps. Afterwards, slide each funnel back until it meets the core and push every bin fully back into its bay.

**Never turn a flap by hand.** The servo's gearbox barely turns backwards, so forcing a flap rounds off the teeth inside the horn, or breaks the servo so that it spins freely. Move it only with the arrows.

**The first press swings the flap to one end.** Until a flap has moved since the machine was switched on, the machine does not know where it is, and the first press of either arrow sends it to 0° at full speed. Keep your fingers out of the chute. If it hums or clicks there, press the right arrow (**Move toward a higher angle**) until it stops.

**Watch the flap, not the arrows.** One arrow moves it towards a lower angle and the other towards a higher one, and which of those opens it depends on how its servo sits.

**A clicking noise means you have gone too far.** Step back the other way until it stops, then lock the angle there. Never leave a servo pushing against the chute wall.

A flap that will not reach open or closed, or a servo that spins freely: [troubleshooting]({{ '/sorter/troubleshooting/' | relative_url }}#flaps-a-flap-will-not-reach-open-or-closed-or-its-servo-spins-freely).

**A choice that does not stay after a save was refused.** The reason is at the very bottom of the page, below the speed settings.

**Continue** is blocked with "Configure servos before continuing" until the servos are set up. When every layer is calibrated, press **Servo setup looks correct**.

## Step 7: Cameras

There are three cards, one per camera, and each one needs a camera:

- **C-channel 2**
- **C-channel 3**
- **Classification C-channel (C4)**

Before you pick any cameras:

<ul class="bulleted-list">
  <li><strong>Take the cap off the classification camera's lens.</strong></li>
  <li><strong>Put a LEGO piece on the C-channel 2 rotor and a different-coloured one on the C-channel 3 rotor</strong>, for example a white piece on C2 and a green one on C3. The two channel cameras look alike in the list, and the piece in the picture tells you which one you are looking at.</li>
</ul>

For each card, pick a camera from the dropdown. The card then shows what that camera sees, so you can tell them apart. Both a channel's drop zone and its exit should be visible in the frame. If they are not, you may need to move the camera lamp to a different dovetail on its C-channel. One camera can serve more than one area if its view covers both.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><strong>The dovetail on the arm can break</strong> when a lamp needs to be removed and repositioned. Use caution if repositioning is needed. The lamps go on at <a href="{{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}">arranging C-channels</a>, step 7, which says which dovetail each one starts in.</p>
</div>

Two more buttons on each card: **Review zone** and **Picture tuning**, in that order on the card.

### Review zone

Press **Review** on each camera, then **Find**, then **Save**. The machine does not use a channel until its zones are saved. Fine adjustment can wait. [Zones]({{ '/sorter/zones/' | relative_url }}) has what each zone is for and how to set it, and what the camera should show.

### Picture tuning

Color correction is not a manual setting at the moment, but it is worth visiting [Camera calibration]({{ '/sorter/camera-calibration/' | relative_url }}) to get each camera's focus nice and sharp.

Set the mode on each camera:

| Camera | Mode |
|---|---|
| C-Channel 2 and C-Channel 3 | 1280x720 at 30 fps |
| Classification C-Channel (C4) | 3840x2160 at 30 fps |

On all C-Channels, set **Pixel Format** to MJPG.

**If a camera's mode list has nothing at 1280x720**, only small sizes such as 640x480 at 5 fps, that camera is on a slow USB link. At 5 fps a channel misses small pieces such as Technic pins. See [a camera only offers small modes]({{ '/sorter/troubleshooting/' | relative_url }}#cameras-a-camera-only-offers-small-modes-or-runs-at-5-fps) before you go on.

If the picture's sliders push the live view off the bottom of the screen, zoom the browser out (Ctrl and minus, or Cmd and minus on a Mac) so you can see both while you adjust.

The camera's automatic settings should be enough for everything else, and manual settings are there if you need them. Click **Confirm**.

Press **Save the cameras** when every card has a camera.

## Step 8: Hive

Hive is the community platform. Connecting the machine to it syncs your samples and progress.

- **Continue on Hive** opens Hive in the browser. Sign in there, or create an account, and confirm the machine name. Hive brings you back to the wizard and finishes the link. No password is stored on the machine.
- **Skip for now** moves on without it. You can connect later under **Settings** → **Hive**.

## Step 9: Setup complete

Press **Open Dashboard**. The wizard is done.

## The finished result

The dashboard, with every camera live and its zones drawn, the machine's name at the top, and **Ready** beside it. Nothing has been sorted yet, so **Recent pieces** is empty.

<div class="img-placeholder">Screenshot of the SorterOS dashboard on a machine with stock camera mounts, straight after setup: the three camera tiles live with their zones drawn, the machine name and Ready at the top, and nothing under Recent pieces.</div>

## Settings worth a look

Open **Settings** from the top of the UI.

Everything on this list is on the **General** page, which is the one Settings opens on.

- **Machine name** is the same name you set in step 1.
- **WiFi** joins the machine to a wireless network, and **Tailscale** to a Tailscale one. Useful if the machine is on Ethernet now and you want it elsewhere later.
- **OpenRouter** takes an API key for cloud-assisted detection. It is optional. Identifying a piece does not need it.
- **Sample Capture** and **Local Samples** control what the machine keeps from each run. The defaults are fine to start with.
- **Theme** switches the UI between light and dark, and **Theme color** is the color you picked in step 2.

## Before your first sort run

Five things are left, in this order:

<ol class="numbered-steps">
  <li><strong><a href="{{ '/sorter/camera-calibration/' | relative_url }}">Camera calibration</a></strong>: focus each camera against a printed chart.</li>
  <li><strong><a href="{{ '/sorter/chute-calibration/' | relative_url }}">Homing and calibrating the chute</a></strong>: teach the chute where the bins are.</li>
  <li><strong><a href="{{ '/sorter/before-first-sort-run/' | relative_url }}">Before your first sort run</a></strong>: the last five settings to check, the detection model among them.</li>
  <li><strong><a href="{{ '/sorter/preparing-lego/' | relative_url }}">Preparing LEGO for a sort run</a></strong>: what to take out of a tub of bulk LEGO before it goes in.</li>
  <li><strong><a href="{{ '/sorter/tutorials/first-sort-run/' | relative_url }}">Your first sort run</a></strong>: pick a profile, feed a handful of parts, watch them land.</li>
</ol>
