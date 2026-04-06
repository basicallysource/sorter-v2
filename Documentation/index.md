---
layout: default
title: Detector Documentation Hub
slug: home
kicker: Sorter V2
lede: This site is the durable documentation layer for detector benchmarking, model artifacts, and target conversion workflows across Mac, Raspberry Pi, Orange Pi, and Hailo.
---

## Why this site exists

The detector work produced a lot of useful results, but also a lot of local experiment output:

- benchmark JSONs
- HTML comparison reports
- compile bundles
- Vast.ai session artifacts

The goal of this site is to keep the lasting knowledge in one checked-in place and treat generated output as local working state unless it is explicitly promoted.

## Documentation map

<div class="callout-grid">
  <div class="callout">
    <strong><a href="runtime-status.html">Runtime Status</a></strong>
    <p>The current conclusions, deployment recommendations, and the canonical local artifacts worth keeping.</p>
  </div>
  <div class="callout">
    <strong><a href="model-artifacts.html">Model Artifacts</a></strong>
    <p>What each export and compiled format is for, where it lives, and which target it serves.</p>
  </div>
  <div class="callout">
    <strong><a href="device-benchmarking.html">Device Benchmarking</a></strong>
    <p>The repeatable cross-device benchmark workflow for Mac, Orange Pi, and Raspberry Pi.</p>
  </div>
  <div class="callout">
    <strong><a href="hailo-hef-workflow.html">Hailo HEF Workflow</a></strong>
    <p>The maintained ONNX to HEF flow for Raspberry Pi 5 AI HAT deployments.</p>
  </div>
</div>

## Current headline conclusions

- The local Mac Mini M4 CPU run is the current quality reference.
- Mac CoreML is the fastest validated local acceleration path, especially for `YOLO11s`.
- Orange Pi CPU and Raspberry Pi 5 CPU match the reference exactly on the shared benchmark bundle.
- Raspberry Pi 5 `Hailo + NanoDet` is the strongest current accelerated deployment path.
- The current Orange Pi `RKNN` artifacts are still experimental because they were not rebuilt from the exact current ONNX exports.

## Artifact policy

The durable rule is simple:

1. Keep decisions and workflows in checked-in Markdown.
2. Keep only the latest canonical benchmark and compile artifacts under `software/client/blob/`.
3. Regenerate reports from benchmark JSONs instead of treating every generated HTML file as permanent.

## GitHub Pages publishing

This site is intended to publish from the root-level `Documentation/` folder via GitHub Actions, so we are not locked to GitHub's built-in `/docs` folder convention.

If the repository's default branch is not `main` or `master`, update the Pages workflow trigger in `.github/workflows/documentation-pages.yml` after merge.
