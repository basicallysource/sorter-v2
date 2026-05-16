# Sorter Happy Path / Incident Inventory

## Happy Path

The normal sorter loop should stay boring:

1. C1 feeds only while the C2 dropzone can accept a piece.
2. C2 advances pieces toward C3 and only feeds when C3 can accept one.
3. C3 feeds C4 only when C4 has an open gate or a pending C4-to-C3 intake request.
4. C4 tracks, classifies, and drops a resolved piece into distribution when the chute is ready.
5. Distribution selects a bin, moves chute/door hardware, commits the piece, and reopens the gate after physical exit.

Anything that requires recovery motion, operator judgement, hardware repair, or intentional fallback should be an incident instead of being blended into that flow.

## Explicit Incidents

| Kind | Scope | Trigger | Current resolution |
| --- | --- | --- | --- |
| `exit_stuck` | C2/C3/C4 | A piece is not falling off a channel. | Operator or automatic release wiggle, depending on policy. |
| `channel_dropzone_stuck` | C2/C3 | A detected piece stays in a dropzone during accumulated channel motion. | Operator/auto acknowledges the track is ignored until it leaves the dropzone. |
| `c2_separation_needed` | C2 | C2 would have started slip-stick separation. | Manual review; automatic motion intentionally disabled for now. |
| `bulk_feeder_stalled` | C1 | C1 has pulsed enough times for long enough without new C2 activity. | Operator checks the bulk feeder or clears the incident. |
| `feeder_detection_unavailable` | C2/C3/C4 | Feeder camera detections are unavailable past the grace window. | Operator restores detection or clears the incident. |
| `distribution_chute_jam` | Distribution | Chute/servo motion exceeds the move-time budget. | Operator clears the chute/servo path and clears the incident. |
| `distribution_servo_bus_offline` | Distribution | Every configured distribution layer servo is offline. | Operator restores the bus; incident clears when a servo reports healthy or can be manually cleared. |
| `distribution_no_bin_available` | Distribution | No matching bin/capacity is available for the piece. | Operator assigns capacity, frees a bin, or disables the incident to allow bottom-tray passthrough. |
| `classification_unresolved` | C4 | C4 reaches the drop deadline or Brickognize timeout before the piece is resolved. | Operator reviews the fallback-to-unknown and clears the incident. |
| `classification_multi_drop_collision` | C4 | Multiple pieces reach the C4 drop window together. | Operator inspects the collision/fallback and clears the incident. |
| `classification_intake_request_timeout` | C4 | C4 requested a piece from C3, but no intake track arrived before timeout. | Operator checks the C3→C4 handoff and clears the incident to retry. |
| `classification_track_lost` | C4 | A meaningful C4 track expires from stale-zone cleanup before the expected drop flow completed. | Operator checks C4 tracking/occlusion and clears the incident. Empty ghost tracks remain diagnostics only. |

## Explicit Non-Incident Modes

These paths are intentionally separate from normal sorting, but they are not
operator incidents:

| Mode | Current behavior | Why it is not an incident |
| --- | --- | --- |
| `camera_sample_collection_bypass` | Sample collection bypasses some gates and speed limits. | This is an explicit operating mode, not an incident, but it should stay visibly separate from normal sorting. |
