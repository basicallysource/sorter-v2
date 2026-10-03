---
layout: default
title: Crimping connectors
type: how-to
section: hardware
slug: helper-crimping
kicker: Helpers — Crimping
lede: Every lead on this machine is made with one of two kinds of crimp, and each needs its own pliers. Which is which, how to read the pliers, and the steps for each.
permalink: /hardware/helpers/crimping/
author: barthel
contributors: [effreek, brickcyclealice]
last_verified: 2026-10-02
tools_needed: ["Crimping pliers for open-barrel contacts, for the PH, VH and Dupont contacts", "Insulated-terminal crimping pliers, for the butt connectors, receptacles and fork terminals", "Wire strippers", "Multimeter, to check the finished joint"]
---

The lead pages each say what to crimp onto what. This page is the one place that says **how**, so each of them points here.

## Two kinds of crimp, two pairs of pliers

**Open-barrel contacts** are bare metal, the size of a grain of rice or smaller. One end is two sets of small wings, the other end is the pin or the socket. They are the **PH** contacts (the 2.0 mm JST housings), the **VH** contacts (the 3.96 mm JST housing on the board's 24 V lead) and the **Dupont** contacts. You crimp them with pliers made for open-barrel contacts.

**Insulated terminals** are a metal barrel inside a coloured or clear plastic sleeve: the **butt connectors** (one wire in each end), the **#187 receptacles** on the limit switch, and the **fork terminals** on the PSU pigtails. You crimp them with insulated-terminal pliers.

**The two pairs are not interchangeable.** An insulated terminal in open-barrel pliers is squashed rather than gripped, and an open-barrel contact in insulated-terminal pliers is not closed properly. Each lead page names which pliers each crimp needs.

The words the pages use, once and for all:

<dl class="spec-list">
  <dt>Contact</dt><dd>The metal piece that goes inside a housing: PH, VH or Dupont. Open barrel.</dd>
  <dt>Terminal</dt><dd>Any insulated crimp part. A butt connector is a terminal, so are the receptacle and the fork.</dd>
  <dt>Die</dt><dd>The shaped part of the pliers that closes on the crimp. Some pliers call it the jaw; it is the same thing. Pliers usually have several, each marked with the wire size it is for.</dd>
</dl>

## Choose the die by its marking

**Go by the wire size marked on the die, in AWG or in mm², never by its colour.** Colour codes on pliers and on terminals differ between makers, and some pliers have none. If your die gives only mm², use the one that covers your wire. Each lead page gives the size it needs.

## Open-barrel contacts

Do one contact at a time. Practise on a scrap of the same wire first: a mis-crimped contact cannot be reused, and the first ones in a series you have not done before often come out wrong.

<ol class="numbered-steps">
  <li>Strip the end of the wire: about 2 mm for a PH or Dupont contact, 3 mm for a VH contact. Twist the strands tight.</li>
  <li>Find the two sets of wings on the contact. The inner wings are the short pair next to the pin or socket, the outer wings are the longer pair at the back.</li>
  <li>Place the bare strands in the inner wings and the wire's insulation in the outer wings. No strands may stick out past the inner wings, and the insulation must not be under them.</li>
  <li>Close the die. The inner wings curl onto the strands and the outer wings onto the insulation.</li>
  <li>Pull on the wire. If it comes out, cut the contact off, strip the wire again and use a new contact.</li>
  <li>Push the contact into the back of the housing until it clicks.</li>
</ol>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/ph-contact-crimp-steps-full-985dd5dc580a.png" alt="Three stages: a wire with about 2 mm of bare strands; a contact crimped on, its outer wings on the insulation and its inner wings on the bare strands; the contact pushed into the back of a housing until it clicks.">
  <figcaption>Strip, crimp, push in until it clicks. Shown for a PH contact; Dupont and VH contacts go the same way.</figcaption>
</figure>

What each one takes:

<ul class="bulleted-list">
  <li><b>PH contact</b> (<code>SPH-002T</code>): 24 to 28 AWG (0.08 to 0.20 mm²) wire only. Use the 24 AWG (0.20 mm²) die.</li>
  <li><b>Dupont contact</b>: 22 to 28 AWG (0.08 to 0.33 mm²) wire.</li>
  <li><b>VH contact</b> (<code>SVH-21T</code>): 22 to 16 AWG (0.33 to 1.3 mm²) wire, so a bigger barrel than the other two and a bigger die.</li>
</ul>

## Insulated terminals

<ol class="numbered-steps">
  <li>Strip the wire as long as the metal barrel: about 7 mm for a butt connector, 5 mm for a #187 receptacle, as long as the barrel for a fork terminal. Hold the wire against the terminal to judge it. Twist the strands tight.</li>
  <li>Push the bare strands into the barrel until the wire's insulation meets the end of the barrel. On a clear butt connector you can see the strands reach the stop in the middle.</li>
  <li>Put the metal barrel, not the plastic sleeve, in the die marked for your wire size and squeeze. On ratcheting pliers, squeeze until the ratchet releases.</li>
  <li>On a butt connector, crimp each end separately. Do one joint at a time so two joints never touch, and stagger them by a few millimetres along the lead.</li>
  <li>Pull on every wire.</li>
</ol>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/butt-crimp-steps-full-3537584b7c38.png" alt="Three stages: a wire with 7 mm of bare strands; a wire pushed into each end of a red butt connector; the connector held between the dies of a crimping tool, the die marked 22 to 16.">
  <figcaption>Strip, push in, crimp each end in the marked die.</figcaption>
</figure>

## Check every crimp

A crimp you cannot pull out is a crimp that holds. A crimp that holds can still be a bad joint, so the lead pages end with a continuity check on the finished lead. Do that check before the lead goes near the board or the supply: it is what finds a strand crossing to the next contact.
