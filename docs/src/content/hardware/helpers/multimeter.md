---
layout: default
title: Using a multimeter
type: how-to
section: hardware
slug: helper-multimeter
kicker: Helpers — Multimeter
lede: Two settings on the dial cover every check this build asks for, continuity and resistance. What each one tells you, and how to read it.
permalink: /hardware/helpers/multimeter/
author: barthel
contributors: [effreek]
last_verified: 2026-09-26
tools_needed: ["Multimeter, with a continuity buzzer"]
---

Several pages ask you to test something with a multimeter before you commit to it. Which conductor of a barrel plug is the positive one. Which two of a stepper's four leads are one coil. Which of a switch's three tabs are closed while the lever is free.

All three are the same tool on one of two settings, and none of them needs an expensive meter. The one thing yours has to have is a **continuity buzzer**, because half this page listens for the beep. If you are buying one, Adafruit's [Multimeters guide](https://learn.adafruit.com/multimeters) opens with a checklist of what a cheap meter must do.

If you have never picked one up, the video at the foot of this page walks through the whole tool in about ten minutes.

## Set the meter up once

<ol class="numbered-steps">
  <li><b>Black probe into <code>COM</code>, red probe into the port marked <code>V</code> and &Omega;.</b> Both checks on this page use those two ports, so the probes go in once and stay there. The third port, usually <code>10A</code>, is for measuring current, and nothing on this build asks you to.</li>
  <li><b>Find the two positions on the dial.</b> Resistance is the <b>&Omega;</b> mark. Continuity is the symbol that looks like a sound wave, often sharing its position with the diode test. A cheap meter has several numbered &Omega; ranges instead of one. Start on the lowest. If the display shows a lone <code>1</code> or <code>OL</code>, the reading is above that range, so move up to the next one.</li>
  <li><b>Touch the two probe tips together before you trust anything.</b> Continuity should beep, and &Omega; should read close to zero. Test leads have a resistance of their own, usually 0.1 to 0.5 &Omega;, and it is added to every reading you take. That matters here, because every reading on this page is under an ohm. If nothing happens at all, the battery or a lead is the problem, not the thing you were about to measure.</li>
</ol>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Both checks want the power off.</b> Work on a loose cable, or switch the machine off at the inlet and unplug it. Continuity and resistance push the meter's own small current through whatever is between the probes, so a powered circuit gives a meaningless reading and can damage the meter. And nothing on this build ever asks you to put a probe into anything at mains voltage: the only two mains points are inside the <a href="{{ '/hardware/electronics/installation/psu-box/' | relative_url }}">PSU box</a>, and that box is closed before the machine is ever plugged in.</p>
</div>

## Continuity, for tracing a cable

In continuity mode the meter beeps when the two probe tips are joined by anything close to a short. The beep is the point: you can watch what your hands are doing instead of watching the display.

That answers three questions that come up while making the leads.

**Which wire is the positive one.** A barrel plug or a panel-mount jack is centre-positive on this machine, and the lead hanging off it is usually red and black, but it came from somebody else and a few are wired the other way round. Hold one probe against the centre pin down inside the barrel and touch the other to each conductor in turn. The one that beeps is the tip, which is +24 V. You do this on [the PSU output pigtail]({{ '/hardware/helpers/psu-pigtail/' | relative_url }}), [the control board's 24 V lead]({{ '/hardware/helpers/board-24v-lead/' | relative_url }}) and [the Orange Pi's 24 V lead]({{ '/hardware/helpers/pi-24v-lead/' | relative_url }}).

**Which pin of a housing a wire ended up in.** Probe from the bare wire, or from a contact you can still see, through to the pin at the far end. The camera lamps need this: each one plugs on red to `+V`, and the red wire is not always in the pin you would expect. See [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}).

**Whether a finished lead is actually good.** Each end that should be joined to the other beeps, and no two contacts that should be separate do. A stray strand bridging two positions in a housing is invisible and this is what finds it.

<div class="callout">
  <p><b>Probe the metal, not the plastic.</b> A blunt probe tip resting on the mouth of a crimped contact reads open circuit on a joint that is perfectly good. Use a needle probe, or push a short offcut of solid wire into the contact and hold the probe against that.</p>
</div>

## Continuity, for a switch

A switch is a pair of contacts that move, so continuity reads it directly: probe the two terminals and work the lever, and the beep tells you which way round it is wired.

The [chute limit switch]({{ '/hardware/helpers/limit-switch-lead/' | relative_url }}) is the one on this machine. It has three tabs, printed `COM`, `NC` and `NO` on its body. `COM` is the common one, and the other two take turns: one of them is closed while the lever is free, the other while it is pressed.

Probe two tabs at a time and work the lever:

- **Lever free**, `COM` to `NC` beeps and `COM` to `NO` does not.
- **Lever pressed**, that swaps over.

That tells you the printing on the switch is honest, which is worth knowing before you crimp anything onto it. It does not tell you which pair the machine expects. The lead is built onto `COM` and `NC`, and that choice has not been confirmed on a running machine yet, which the [lead page]({{ '/hardware/helpers/limit-switch-lead/' | relative_url }}) says on itself.

The same check on the finished lead, at the housing rather than at the switch, is the last step of that page.

## Resistance, for finding a stepper's coils

A stepper motor's four leads are two coils, two leads to each, and the wire colours do not reliably say which pair is which. The lead you build has to put one coil in positions 1 and 2 of its housing and the other in 3 and 4, so this gets measured rather than assumed. Set the dial to **&Omega;** and probe two leads at a time:

- **Two leads from the same coil read well under an ohm.** 0.65 &Omega; on the chute's NEMA 23 and 2.3 &Omega; on the channel NEMA 17s, plus whatever your test leads add.
- **Two leads from different coils read open circuit**, shown as `OL` or a lone `1`.

Work through the combinations until you have both pairs, and write down which colour went with which before you start crimping. It is [the chute stepper lead]({{ '/hardware/helpers/chute-stepper-lead/' | relative_url }}) that is built from bare motor leads, and [the channel stepper leads]({{ '/hardware/helpers/channel-stepper-lead/' | relative_url }}) where the pairs decide which contacts move.

<div class="callout">
  <p><b>Continuity mode finds the pairs too</b>, since a coil is close enough to a short to beep. The reason to read the number instead is that it also tells you the coil is healthy: a pair you are confident about that reads tens of ohms, or nothing at all, is a broken winding or a bad joint rather than a pairing you got wrong.</p>
</div>

## Volts, when the machine is on

This is the only setting you use with the power on, and no build step asks for it, so treat it as optional. Set the dial to **DC volts** (the straight line over a dashed line, `V` with a dash, or `DCV`), pick a range above 24 V if your meter is not autoranging, then hold the red probe on the tip inside a spare [PSU output]({{ '/hardware/helpers/psu-pigtail/' | relative_url }}) jack and the black probe against its sleeve. A healthy supply reads about 24 V. If the probes are the wrong way round the meter just shows a negative number, which harms nothing.

The two things worth knowing: put the probes back in the `COM` and `V`/&Omega; ports if you ever move them for a current measurement, and never take a meter to the mains side of the PSU box.

## Watch somebody do it

Ten minutes on the same tool, in the order this page uses it. The ports and the dial first, then resistance, then continuity, and it finishes on exactly the job the leads here need, probing a cable to find out which conductor reaches the tip of the plug.

<figure class="video-figure">
  <div class="video-embed video-embed-wide">
    <iframe
      src="https://www.youtube.com/embed/SLkPtmnglOI"
      title="How to use a multimeter"
      allow="encrypted-media; picture-in-picture; web-share"
      allowfullscreen
      loading="lazy"></iframe>
  </div>
  <figcaption>Covers the probe ports, the dial, voltage, resistance, current and continuity. <cite>Video: SparkFun Electronics, not a Basically video.</cite></figcaption>
</figure>
