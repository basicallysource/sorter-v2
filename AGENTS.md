# AGENTS.md

## Working Style

This codebase benefits from direct, system-near debugging instead of broad speculative rewrites.

When runtime, perception, or hardware behavior is unclear:

1. Reproduce the problem against the live system first.
2. Use small, targeted probes instead of making large assumptions.
3. Compare before/after states with concrete measurements.
4. Only then change architecture or code paths.

## Preferred Debugging Approach

For sorter/runtime issues, prefer this order:

1. Check live lifecycle state.
   Use endpoints like `/api/system/status` and `/api/rt/status` first.

2. Probe the exact subsystem in isolation.
   Examples:
   - send a direct stepper move
   - call the current detection endpoint
   - compare hardware position before/after
   - inspect runner state, track counts, and blocked reasons

3. Verify the real input to the algorithm.
   If detection/tracking looks wrong, inspect:
   - crop/mask zone
   - camera frame resolution
   - tracker geometry
   - saved polygon / arc params

4. Add temporary or permanent observability when needed.
   Prefer small status/introspection additions over guessing. Good examples:
   - runner detection counts
   - raw/confirmed track counts
   - runtime health / blocked_reason
   - compact runtime debug snapshots

5. Keep fixes central and architectural.
   If multiple channels share the same failure mode, fix the shared bootstrap / pipeline path instead of patching one channel locally.

## Runtime / Hardware Rules

- Do not rely on UI impressions alone when hardware behavior is disputed.
- Use direct API-driven checks to confirm whether motion really happened.
- Separate hardware-path bugs from runtime-logic bugs.
- Separate crop/mask geometry from tracker geometry. Both may be required.
- Keep startup-only behaviors isolated as explicit strategies, not hidden inside normal runtime loops.
- If a speed change is intended only for startup purge or priming, scope it to that mode only.

## Development Bias

- Prefer a small real test over a large theoretical explanation.
- Prefer evidence over recollection.
- Prefer one clean shared path over duplicated special-case fixes.
- Prefer instrumentation that helps the next debugging session too.

## Useful Pattern

For live investigations, a good default loop is:

1. Pause or stabilize the machine.
2. Capture current status.
3. Execute one controlled action.
4. Capture status again.
5. Compare the delta.
6. Repeat until the exact failing boundary is clear.
