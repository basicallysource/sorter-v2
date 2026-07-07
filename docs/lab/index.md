---
layout: default
title: Lab
type: landing
section: lab
slug: lab
kicker: Research & Contributor References
lede: The lab is where we keep durable findings from hands-on research and the shared contributor references the rest of the project builds on. Right now it holds two areas — the object detection model research, and the shared styleguide used by the Sorter UI, Hive, and these docs.
permalink: /lab/
---

## Research areas

<div class="callout-grid">
  <div class="callout">
    <strong><a href="{{ '/lab/object-detection/' | relative_url }}">Object detection research</a></strong>
    <p>Which detector runtimes we validated, where the canonical artifacts live, the cross-device benchmark workflow, and the Raspberry Pi 5 Hailo HEF compile path.</p>
  </div>
  <div class="callout">
    <strong><a href="{{ '/lab/c-channel-singulation/' | relative_url }}">C-channel singulation</a></strong>
    <p>How the sorter separates tangled LEGO into single pieces using rotating C-shaped channels — a novel approach with no known published precedent.</p>
  </div>
  <div class="callout">
    <strong><a href="{{ '/lab/classification-research/' | relative_url }}">Classification research</a></strong>
    <p>Embeddings vs classifiers, the Brickognize API, training data strategy, and why color detection avoids ML entirely.</p>
  </div>
  <div class="callout">
    <strong><a href="{{ '/lab/feeder-experiments/' | relative_url }}">Feeder experiments</a></strong>
    <p>Turntable, vibration, and chute experiments that preceded the C-channel design — what was tested, what failed, and what the data showed.</p>
  </div>
  <div class="callout">
    <strong><a href="{{ '/lab/software-architecture-decisions/' | relative_url }}">Software architecture decisions</a></strong>
    <p>Why the project uses a dumb-firmware / smart-host split, what alternatives were evaluated, and the design principles behind the stack.</p>
  </div>
  <div class="callout">
    <strong><a href="{{ '/lab/sorter-architecture-principles/' | relative_url }}">Sorter Architecture Principles</a></strong>
    <p>A durable set of architectural principles and audit questions for iteratively improving the runtime and backend without losing direction.</p>
  </div>
  <div class="callout">
    <strong><a href="{{ '/lab/styleguide/' | relative_url }}">Styleguide</a></strong>
    <p>The shared visual language used by the Sorter UI, Hive, and this documentation site. Contributor reference only — not useful for end users.</p>
  </div>
</div>

## What counts as lab content

The lab sits one level below the end-user-facing sections. Content lands here when:

- it's a **contributor reference** the rest of the project builds on but that an operator would never need to read (the styleguide);
- it's an **active research thread** where we're still validating conclusions, and the findings aren't ready to be promoted into a stable hardware or Sorter docs page (the object detection work).

Once a finding stabilizes enough to be promoted — for example, when we settle on a single accelerated deployment path and it belongs in the Sorter setup docs — it graduates out of the lab into the appropriate top-level section.

## Artifact policy

The durable rule across all lab work:

1. Keep decisions and workflows in checked-in Markdown on these pages.
2. Keep only the latest canonical benchmark and compile artifacts under `software/sorter/backend/blob/`.
3. Regenerate reports from benchmark JSONs instead of treating every HTML file as permanent.
4. Promote a finding out of the lab only after it has both a quality comparison against a reference and a sustained-throughput measurement.
