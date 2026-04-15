---
title: Classification research
type: explanation
audience: contributor working on ML/vision
applies_to: 2026-03 findings
owner: lab
last_verified: 2026-04-14
section: lab
slug: lab-classification-research
kicker: Lab — Research Area
lede: How the sorter identifies which LEGO part it sees — the path from embeddings to classifiers, the training data strategy, and why color detection avoids ML entirely.
permalink: /lab/classification-research/
---

## The question

How does the sorter identify which LEGO part it sees, and what approaches were evaluated before settling on the current strategy?

## Why this matters

Classification accuracy directly determines sort quality. A wrong classification means a piece lands in the wrong bin. The project evaluated multiple ML approaches before converging on the current strategy — understanding that history prevents repeating dead ends.

## Approach evolution

### Embeddings (tried first)

The initial approach used **embedding models** (metric/similarity learning) with DINO V2. Embeddings work well when you have few example images per class — you compare a new image against a database of known embeddings and pick the closest match.

**Problem:** A single ambiguous vector in the database causes cascading misclassifications. For example, a 1×2 brick photo taken at a bad angle (missing the pin) confuses the model between regular and pin-equipped variants. One bad embedding poisons an entire class.

### Classification (current)

Piotr Rybak (Brickognize creator) found that **a regular classifier outperforms embeddings when you have enough high-quality, diverse images per class**. The switch happened after about four weeks of embedding research.

The current model uses DINO V2 small as the backbone with a **soft triple loss** (instead of cross-entropy) for the final classification layer. On a good GPU, single-prediction latency is ~1ms.

## Scope and accuracy

| Metric | Value |
|--------|-------|
| Supported part classes | Top 2,000–5,000 (covers ~85% of user collections) |
| Accuracy on supported classes | 98.5% |
| Achievable with controlled environment | >99% (3+ cameras, consistent lighting) |
| Total LEGO part numbers that exist | 70,000+ |
| Brickognize API response time | 0.56s average (0.40–0.98s range) |
| API throughput | 1.78 requests/second |

The project does not aim to support all 70k+ parts. Without massive training data for rare parts, it is impractical. Focusing on the most common 2,000–5,000 parts covers the vast majority of real-world collections.

## Training data strategy

| Source | Pros | Cons |
|--------|------|------|
| Manual photography | High quality, real-world conditions | Label-heavy, slow to scale |
| Synthetic rendering (LDraw + Blender) | Already labeled, infinite variations | Domain gap if not varied enough |
| Community-contributed images | Scales well | Labeling quality hard to control |
| Phone-home telemetry | Captures rare parts in real sorting conditions | Requires user permission, privacy concern |

Synthetic rendering is viable for augmentation. Varying angles, lighting, and post-processing effects is more important than photorealistic rendering. The images arrive pre-labeled, which eliminates the manual labeling bottleneck.

## Color classification

ML is **unreliable** for color detection due to lighting variation across machines and environments. The recommended approach avoids ML entirely:

1. Place a color calibration card (reference colors) in frame.
2. Apply classic white-balance correction.
3. Use histogram matching against known reference patches.

This is more reliable than any ML-based color detection the team tested.

## Trade-offs

- **Remote API vs local model** — Brickognize API works and is fast (0.56s), but requires internet. A local model is planned for offline operation. Strategy: dual-mode — local for common parts, API for rare/uncertain.
- **Embeddings vs classifier** — Embeddings need fewer examples per class but are fragile to bad vectors. Classifiers need more training data but are more robust. With enough data, classifiers win.
- **Breadth vs depth** — Supporting all 70k parts requires impractical amounts of data. Focusing on top 5k gives 85%+ coverage with achievable effort.
- **ML color vs calibration-based color** — ML color detection sounds elegant but fails across different lighting conditions. Calibration cards are boring but reliable.

## What this is not

- **Not aiming for universal coverage.** Rare and obscure parts (post-2020 limited editions, regional exclusives) are out of scope for the initial classifier.
- **Not doing color via ML.** Color detection uses classical computer vision (calibration cards, white balance), not learned models.
- **Not a self-contained local system yet.** The primary classifier (Brickognize) is a remote API. Local self-hosting is planned but not shipped.

## Where to go next

- [Object detection research]({{ '/lab/object-detection/' | relative_url }}) — the detector that finds pieces in the chamber before classification
- [Sorter architecture]({{ '/sorter/architecture/' | relative_url }}) — how classification fits into the sorting pipeline
- [Camera calibration]({{ '/sorter/camera-calibration/' | relative_url }}) — the color calibration workflow that feeds into classification
