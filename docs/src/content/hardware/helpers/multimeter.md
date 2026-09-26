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

If you have never picked one up, the video at the foot of this page walks through the whole tool, and the list under it goes straight to the part that matches the section you are on.

## Set the meter up once

<figure class="harness-figure">
  <div class="diagram diagram-wide">
    <svg viewBox="0 0 930 424" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="The front of a digital multimeter, drawn from the front. A display at the top, a rotary dial in the middle and three probe ports along the bottom. The dial carries OFF, DC volts, AC volts and current on one side, and on the other the continuity position, marked with a dot and three arcs, and three resistance ranges bracketed together under an omega. The pointer is parked on continuity. Of the three ports, the one marked V omega mA takes the red probe and the one marked COM takes the black probe, and the third, 10A, is unused. Three numbered notes beside the meter explain the continuity position, the resistance ranges and the two ports.">
      <text x="0" y="20" font-size="17" font-weight="700" fill="var(--ink)">The two settings this build uses, and where the probes go</text>
      <text x="0" y="41" font-size="12" fill="var(--muted)">Every meter is laid out differently. These are the marks to look for on yours.</text>
      <rect x="0" y="70" width="300" height="330" rx="8" fill="var(--surface)" stroke="var(--ink)" stroke-width="1.5"/>
      <rect x="34" y="90" width="232" height="44" rx="3" fill="var(--bg)" stroke="var(--line)" stroke-width="1"/>
      <text x="256" y="122" font-size="22" font-weight="700" text-anchor="end" font-family="var(--font-mono), monospace" fill="var(--muted)">OL</text>
      <circle cx="150" cy="226" r="58" fill="var(--bg)" stroke="var(--ink)" stroke-width="1.5"/>
      <circle cx="150" cy="226" r="27" fill="var(--surface)" stroke="var(--ink)" stroke-width="1.5"/>
      <line x1="150.0" y1="179.0" x2="150.0" y2="169.0" stroke="var(--ink)" stroke-width="1.2" stroke-linecap="round"/>
      <text x="150.0" y="156.0" font-size="12" text-anchor="middle" fill="var(--ink)">OFF</text>
      <line x1="183.2" y1="192.8" x2="190.3" y2="185.7" stroke="var(--ink)" stroke-width="1.2" stroke-linecap="round"/>
      <text x="198.3259018078045" y="177.6740981921955" font-size="12" text-anchor="start" fill="var(--ink)">V</text>
      <line x1="196.3" y1="217.8" x2="206.1" y2="216.1" stroke="var(--ink)" stroke-width="1.2" stroke-linecap="round"/>
      <text x="218.87577372290338" y="217.15003485264717" font-size="12" text-anchor="start" fill="var(--ink)">V~</text>
      <line x1="192.6" y1="245.9" x2="201.7" y2="250.1" stroke="var(--ink)" stroke-width="1.2" stroke-linecap="round"/>
      <text x="213.0667762407121" y="261.27375136881176" font-size="12" text-anchor="start" fill="var(--ink)">A</text>
      <line x1="145.9" y1="272.8" x2="145.0" y2="282.8" stroke="var(--primary)" stroke-width="2.2" stroke-linecap="round"/>
      <line x1="116.8" y1="259.2" x2="109.7" y2="266.3" stroke="var(--primary)" stroke-width="2.2" stroke-linecap="round"/>
      <text x="101.67409819219549" y="282.32590180780454" font-size="12" font-weight="700" text-anchor="end" fill="var(--primary)">200</text>
      <line x1="103.5" y1="232.5" x2="93.6" y2="233.9" stroke="var(--primary)" stroke-width="2.2" stroke-linecap="round"/>
      <text x="80.72016291312379" y="240.29880947104482" font-size="12" font-weight="700" text-anchor="end" fill="var(--primary)">2k</text>
      <line x1="108.9" y1="203.2" x2="100.1" y2="198.4" stroke="var(--primary)" stroke-width="2.2" stroke-linecap="round"/>
      <text x="89.27814167168471" y="194.12408810177106" font-size="12" font-weight="700" text-anchor="end" fill="var(--primary)">20k</text>
      <circle cx="127.0" cy="305.7" r="2.6" fill="var(--primary)"/>
      <path d="M 131.8 301.0 A 6 6 0 0 1 131.8 310.4" fill="none" stroke="var(--primary)" stroke-width="1.6" stroke-linecap="round"/>
      <path d="M 133.3 297.1 A 11 11 0 0 1 133.3 314.3" fill="none" stroke="var(--primary)" stroke-width="1.6" stroke-linecap="round"/>
      <path d="M 134.8 293.2 A 16 16 0 0 1 134.8 318.2" fill="none" stroke="var(--primary)" stroke-width="1.6" stroke-linecap="round"/>
      <text x="40.0510485759104" y="246.03069490368705" font-size="17" font-weight="700" text-anchor="end" fill="var(--primary)">Ω</text>
      <line x1="150" y1="226" x2="147.9" y2="249.9" stroke="var(--primary)" stroke-width="3.4" stroke-linecap="round"/>
      <circle cx="66" cy="348" r="13" fill="var(--bg)" stroke="var(--muted)" stroke-width="1.2"/>
      <circle cx="66" cy="348" r="4" fill="var(--ink)"/>
      <text x="66" y="380" font-size="11" text-anchor="middle" fill="var(--muted)">10A</text>
      <text x="66" y="396" font-size="10" text-anchor="middle" fill="var(--muted)">not used</text>
      <circle cx="150" cy="348" r="13" fill="var(--bg)" stroke="#d01012" stroke-width="2.4"/>
      <circle cx="150" cy="348" r="4" fill="var(--ink)"/>
      <text x="150" y="380" font-size="11" font-weight="700" text-anchor="middle" fill="var(--ink)">VΩmA</text>
      <text x="150" y="396" font-size="10" text-anchor="middle" fill="var(--muted)">red probe</text>
      <circle cx="234" cy="348" r="13" fill="var(--bg)" stroke="#1a1a1a" stroke-width="2.4"/>
      <circle cx="234" cy="348" r="4" fill="var(--ink)"/>
      <text x="234" y="380" font-size="11" font-weight="700" text-anchor="middle" fill="var(--ink)">COM</text>
      <text x="234" y="396" font-size="10" text-anchor="middle" fill="var(--muted)">black probe</text>
      <rect x="344" y="68" width="586" height="104" rx="5" fill="var(--bg)" stroke="var(--line)" stroke-width="1"/>
      <circle cx="374" cy="98" r="12" fill="var(--primary)"/>
      <text x="374" y="102" font-size="12" font-weight="700" text-anchor="middle" fill="#ffffff">1</text>
      <text x="452" y="96" font-size="13" font-weight="700" fill="var(--ink)">Continuity</text>
      <text x="452" y="116" font-size="12" fill="var(--muted)">The meter beeps when the two probe tips are joined. Listen for it rather</text>
      <text x="452" y="132" font-size="12" fill="var(--muted)">than watching the display. On many meters this position is shared with</text>
      <text x="452" y="148" font-size="12" fill="var(--muted)">the diode test.</text>
      <circle cx="394" cy="116" r="3.2" fill="var(--ink)"/>
      <path d="M 400.4 109.8 A 8 8 0 0 1 400.4 122.2" fill="none" stroke="var(--ink)" stroke-width="1.8" stroke-linecap="round"/>
      <path d="M 402.2 105.1 A 14 14 0 0 1 402.2 126.9" fill="none" stroke="var(--ink)" stroke-width="1.8" stroke-linecap="round"/>
      <path d="M 404.0 100.4 A 20 20 0 0 1 404.0 131.6" fill="none" stroke="var(--ink)" stroke-width="1.8" stroke-linecap="round"/>
      <rect x="344" y="184" width="586" height="104" rx="5" fill="var(--bg)" stroke="var(--line)" stroke-width="1"/>
      <circle cx="374" cy="214" r="12" fill="var(--primary)"/>
      <text x="374" y="218" font-size="12" font-weight="700" text-anchor="middle" fill="#ffffff">2</text>
      <text x="452" y="212" font-size="13" font-weight="700" fill="var(--ink)">Resistance</text>
      <text x="452" y="232" font-size="12" fill="var(--muted)">Reads how many ohms sit between the probes. A meter with numbered ranges</text>
      <text x="452" y="248" font-size="12" fill="var(--muted)">instead of one Ω mark starts on the lowest, because every reading on this</text>
      <text x="452" y="264" font-size="12" fill="var(--muted)">page is under an ohm.</text>
      <text x="406" y="240" font-size="30" font-weight="700" text-anchor="middle" fill="var(--ink)">Ω</text>
      <rect x="344" y="300" width="586" height="104" rx="5" fill="var(--bg)" stroke="var(--line)" stroke-width="1"/>
      <circle cx="374" cy="330" r="12" fill="var(--primary)"/>
      <text x="374" y="334" font-size="12" font-weight="700" text-anchor="middle" fill="#ffffff">3</text>
      <text x="452" y="328" font-size="13" font-weight="700" fill="var(--ink)">Where the probes go</text>
      <text x="452" y="348" font-size="12" fill="var(--muted)">Black into COM, red into the port marked V and Ω. Both checks use those</text>
      <text x="452" y="364" font-size="12" fill="var(--muted)">two, so they go in once and stay there. The third port is for measuring</text>
      <text x="452" y="380" font-size="12" fill="var(--muted)">current, which nothing here asks for.</text>
      <circle cx="392" cy="352" r="9" fill="var(--bg)" stroke="#d01012" stroke-width="1.8"/>
      <circle cx="392" cy="352" r="3" fill="var(--ink)"/>
      <circle cx="420" cy="352" r="9" fill="var(--bg)" stroke="#1a1a1a" stroke-width="1.8"/>
      <circle cx="420" cy="352" r="3" fill="var(--ink)"/>
    </svg>
  </div>  <figcaption>Yours will not look like this one. The marks are what carry over. It is drawn parked on continuity with nothing connected, which is the <code>OL</code> on the display.</figcaption>
</figure>

**Then check the meter itself, before you trust it on anything else.** Touch the two probe tips together. Continuity should beep, and &Omega; should read close to zero. Test leads have a resistance of their own, usually 0.1 to 0.5 &Omega;, and it is added to every reading you take. That matters here, because every reading on this page is under an ohm. If nothing happens at all, the battery or a lead is the problem, not the thing you were about to measure.

**If the display shows a lone `1` or `OL` on a numbered &Omega; range**, the reading is above that range, so move up to the next one. An autoranging meter picks the range for you.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Both checks want the power off.</b> Work on a loose cable, or switch the machine off at the inlet and unplug it. Continuity and resistance push the meter's own small current through whatever is between the probes, so a powered circuit gives a meaningless reading and can damage the meter. And nothing on this build asks you to probe a <b>live</b> mains circuit. One test does touch the mains side, finding which of the inlet's three leads is the live one on the <a href="{{ '/hardware/electronics/installation/psu-box/' | relative_url }}">PSU box</a>, and that one is continuity with the module loose, the fuse out of its drawer and nothing plugged into the wall.</p>
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

The same tool, in the same order. It opens on the ports, the dial and the kinds of probe, then works through voltage, resistance, current and continuity, and it finishes on exactly the job the leads here need, probing a cable to find out which conductor reaches the tip of the plug.

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

**Straight to the part you need**, by the section of this page you are on:

- [**Set the meter up once**, from 0:00](https://www.youtube.com/watch?v=SLkPtmnglOI&t=0s). The display, the dial, the three ports and the kinds of probe tip.
- [**Continuity**, from 8:15](https://www.youtube.com/watch?v=SLkPtmnglOI&t=495s). The chapter takes the diode test first and continuity after it, which is why the two so often share one position on the dial.
- [**Resistance**, from 5:00](https://www.youtube.com/watch?v=SLkPtmnglOI&t=300s). Includes what to do when a manual range reads over.
- [**Volts**, from 2:40](https://www.youtube.com/watch?v=SLkPtmnglOI&t=160s).

Its other two chapters, current at 6:33 and the advanced features at 9:53, are not needed for anything on this machine.
