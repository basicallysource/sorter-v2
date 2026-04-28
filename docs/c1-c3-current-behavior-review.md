# C1-C3 Current Behavior Review Notes

Stand: `sorter-v2` Backend, HEAD `6ed5de5`, nach SectorCarousel-Integration.
Scope: nur C1, C2, C3 und deren Orchestrator-/Handoff-Verhalten. C4 wird nur dort
erwaehnt, wo C1-C3 direkt davon gegatet werden.

Quellen im Code:

- `software/sorter/backend/rt/coupling/orchestrator.py`
- `software/sorter/backend/rt/bootstrap.py`
- `software/sorter/backend/rt/runtimes/c1.py`
- `software/sorter/backend/rt/runtimes/c2.py`
- `software/sorter/backend/rt/runtimes/c3.py`
- `software/sorter/backend/rt/coupling/slots.py`
- `software/sorter/backend/rt/services/section_feeder_handler.py`
- `software/sorter/backend/rt/services/sector_shadow_observer.py`
- `software/sorter/backend/rt/tests/test_runtime_c1.py`
- `software/sorter/backend/rt/tests/test_runtime_c2.py`
- `software/sorter/backend/rt/tests/test_runtime_c3.py`

## Kurzantwort

Eine erste software-only Ladder-Simulation fuer C1/C2/C3 existiert jetzt:

```text
software/sorter/backend/rt/services/feeder_ladder/selftest.py
```

Sie ist noch nicht so breit wie der SectorCarousel-Selftest, deckt aber die
wichtigsten Feed-Chain-Gates ab.

Was es gibt:

- isolierte Unit-Tests fuer `RuntimeC1`, `RuntimeC2`, `RuntimeC3`
- Unit-Tests fuer `SectionFeederHandler`
- Unit-Tests fuer `SectorShadowObserver`
- Orchestrator-/Runtime-Tuning-Tests
- C1-Pulse-Observation als Messinstrument
- `run_feeder_ladder_selftest()` fuer C1->C2->C3 mit fake hardware/tracks/leases

Was fehlt:

- ein API-/CLI-Einstieg fuer die Feeder-Ladder analog zu den C4-Diagnosen
- noch breitere Fault-Cases wie C2/C3 pending retry ueber mehrere Ticks,
  Bad-Actor-Risk-Gating und vollstaendige C2->C3 Arrival-Fenster-Metriken

## Aktiver Betriebsmodus

Der Orchestrator tickt mit 20 ms Periodendauer, also 50 Hz. Er tickt
downstream-first, damit upstream-Runtimes die frischeren downstream
`available_slots()`-Werte sehen.

Aktiv ist standardmaessig:

```text
feeder_mode = "lease"
```

In diesem Modus laufen `RuntimeC1`, `RuntimeC2` und `RuntimeC3`.

Es gibt zusaetzlich:

```text
feeder_mode = "section"
```

Dann werden `RuntimeC1/2/3` im Orchestrator-Tick uebersprungen und der
`SectionFeederHandler` entscheidet direkt anhand von Sektor-/Winkelregeln.
Dieser Pfad ist verdrahtet, aber nicht der primaere aktuelle Produktionspfad.

C4 laeuft aktuell in:

```text
c4_mode = "sector_carousel"
```

Dadurch muss C3 vor jedem echten C3->C4 Eject eine Landing-Lease vom
`SectorCarouselHandler` bekommen.

## Gemeinsame Grundlagen

### Perception

C1 ist blind und hat keine Kamera.

C2 und C3 lesen je einen `TrackBatch`:

```text
C2 -> c2_feed
C3 -> c3_feed
```

Die Tracks werden durch die Runtime gefiltert:

- stale tracks werden entfernt (`track_stale_s`, default 0.5 s)
- visible tracks kommen in die Zaehler
- actionable tracks brauchen aktuell `hit_count >= 2` und muessen nach
  `track_policy.action_track()` als brauchbar gelten

### Motion Ownership

Jede Runtime hat einen eigenen `HwWorker`. Der Orchestrator-Tick blockiert
nicht auf Hardware. Er queued nur Commands.

Wenn `hw.busy()` oder Pending-Commands anliegen, setzt die Runtime ihren
State typischerweise auf `pulsing` oder `sample_transport` mit
`blocked_reason="hw_busy"`.

### Capacity-Modell

Die alte harte `CapacitySlot.available()`-Logik ist nicht mehr die primaere
Flow-Control. Der Orchestrator fragt upstream-seitig:

```text
capacity_downstream = downstream.available_slots()
```

`CapacitySlot.try_claim()` claimt weiter fuer Debug/Bookkeeping, blockiert
aber nicht mehr hart. Claims haben meist 3 s TTL und werden als Breadcrumbs
in Status/Inspect sichtbar.

Das bedeutet:

- Die echte Flow-Grenze ist `available_slots()` der downstream Runtime.
- Slot-Claims dokumentieren "wir haben ein Teil losgeschickt".
- Downstream-Arrival released Claims, aber der Orchestrator verlässt sich
  nicht nur auf den Claim-Zaehler.

## C1 Aktuelle Funktionsweise

### Rolle

C1 ist die blinde Bulk-Quelle. C1 pulst Teile in C2, wenn der Orchestrator
meldet, dass C2 aktuell Headroom hat.

C1 weiss nicht, wie viele Teile wirklich gefallen sind. Deshalb sind die
Sicherheiten um C1 herum besonders wichtig:

- Startup-Hold
- Downstream-Backpressure aus C2/C3/C4
- Jam-Recovery mit Headroom-Gate
- Pulse-Observation zur spaeteren empirischen Kalibrierung

### Default-Parameter

```text
pulse_cooldown_s = 4.0
startup_hold_s = 2.0
jam_timeout_s = 4.0
jam_min_pulses = 3
jam_cooldown_s = 1.5
max_recovery_cycles = 5
unconfirmed_pulse_limit = 2
observation_hold_s = 12.0
```

Diese Werte koennen aus `feeder_config` ueberschrieben werden.

### C1 Tick-Ablauf

Vereinfacht:

```text
if maintenance_pause:
    paused
elif paused_by_jam:
    paused
elif startup_hold_active:
    idle / startup_hold
elif hw_busy or hw_pending or recovery_in_flight:
    pulsing / hw_busy
elif cooldown_active:
    idle / cooldown
elif capacity_downstream <= 0:
    idle / downstream_full
elif jam_timeout reached and min pulses since progress reached:
    launch_recovery()
elif observation_hold_active:
    idle / observing_downstream
else:
    dispatch_pulse()
```

### C1 Pulse

Bei einem normalen Pulse:

```text
1. claim c1_to_c2 slot mit 3 s hold_time
2. enqueue c1_pulse auf C1 HwWorker
3. pulses_since_progress += 1
4. next_pulse_at = now + pulse_cooldown_s
5. pulse observer wird informiert
```

Wenn der Hardware-Pulse fehlschlaegt, wird der Slot-Claim released.

### Progress / Arrival

C1 bekommt Fortschritt indirekt:

```text
C2 sieht neuen actionable Track
-> C2 released c1_to_c2 slot
-> C2 ruft c1.notify_downstream_progress(now)
-> C1 reset jam state
-> C1 startet observation hold
```

Der Observation-Hold verhindert, dass C1 nach einem bestaetigten Fortschritt
sofort weiter blind nachschiebt.

### Jam Recovery

Wenn C1 mehrere Pulse absetzt und C2 keinen Fortschritt meldet, wird nach
Timeout Recovery gestartet.

Recovery ist levelbasiert:

```text
level 0..4
shake backward/forward
then forward push
```

Die Push-Schedule wurde konservativer gemacht:

```text
10°, 20°, 35°, 60°, 90° output degrees
```

Wichtig: Recovery hat ein Orchestrator-Gate:

```text
c1_recovery_admission_decision(level)
```

Das prueft, ob C2 genug Headroom fuer den erwarteten Worst-Case-Push hat.
Wenn nicht:

```text
blocked_reason = recovery_headroom_insufficient
kein Recovery-Versuch wird verbrannt
```

Wenn die maximale Zahl Recovery-Versuche erreicht ist:

```text
paused_reason = jam_recovery_exhausted
```

Dann muss operatorseitig oder per API `clear_c1_pause()` gerufen werden.

### Zusaetzliche C1-Backpressure im Orchestrator

C1 sieht nicht nur C2.available_slots(). Der Orchestrator blockiert C1
zusaetzlich durch drei Controller:

#### 1. C1-C2 Vision Burst Gate

Aus C2-Density:

```text
target_low = 1
target_high = 3
clump_block_threshold = 0.65
exit_queue_limit = 1
```

Block-Gruende:

```text
vision_target_high
vision_exit_queue
vision_density_clump
vision_target_band
```

Das ist ein bewusst konservativer Bulk-Doser gegen C2-Ueberfuellung.

#### 2. Transitive C3 Backpressure

Wenn C3 keine `available_slots()` mehr meldet, wird C1 gestoppt, auch wenn
C2 lokal noch Platz haette.

Ziel: C1 soll C2 nicht weiter befuellen, wenn C3/C4 downstream schon der
eigentliche Bottleneck ist.

#### 3. C4 Backlog Backpressure

Sticky Hysterese gegen C4-Backlog:

```text
raw_high = 7
dossier_high = 3
raw_resume = 4
dossier_resume = 1
```

Block-Gruende:

```text
backlog_raw
backlog_dossiers
backlog_raw_holding
backlog_dossiers_holding
```

## C2 Aktuelle Funktionsweise

### Rolle

C2 ist der erste getrackte Singulation-Ring. C2 nimmt Material von C1 an,
bewegt Teile Richtung C3 und feuert einen echten C2->C3 Exit-Pulse nur,
wenn C3 seine Landing-Zone frei gibt.

### Default-Parameter

```text
exit_near_arc = 30°
approach_near_arc = 45°
intake_near_arc = 30°
max_piece_count = 5
pulse_cooldown_s = 0.12
track_stale_s = 0.5
advance_interval_s = 1.2
downstream_claim_hold_s = 3.0
exit_handoff_min_interval_s = 0.85
handoff_retry_escalate_after = 2
handoff_retry_max_pulses = 2
stuck_retry_threshold = 5
```

### C2 available_slots()

C2 meldet C1 Headroom so:

```text
if purge_mode:
    0
elif admission_piece_count >= max_piece_count:
    0
else:
    1
```

`admission_piece_count` basiert auf actionable tracks, nicht auf allen raw
oder pending detections.

### C2 Tick-Ablauf

Vereinfacht:

```text
sweep expired downstream claims
fresh_tracks = non-stale c2 tracks
visible_tracks = visible tracks
action_tracks = stable/actionable tracks
update counts + density snapshot
update transport velocity
credit new arrivals from C1
pick exit_track
pick approach_track

if hw_busy:
    pulsing / hw_busy
elif cooldown:
    pulsing / cooldown
elif purge_mode:
    purge pulse
elif exit_track has pending downstream claim:
    wait or retry
elif exit spacing active near exit/approach:
    handoff_spacing / exit_spacing
elif capacity_downstream <= 0:
    idle / downstream_full
elif exit_track:
    dispatch exit pulse
elif approach_track:
    dispatch approach pulse
elif visible_tracks and advance interval elapsed:
    dispatch advance pulse
else:
    idle
```

### C2 Track-Zonen

Ein actionable Track nahe 0°:

```text
abs(angle) <= exit_near_arc
=> exit_track
=> precise pulse
=> C2->C3 handoff
=> downstream slot claim
```

Ein actionable Track in der weiteren Approach-Zone:

```text
exit_near_arc < abs(angle) <= approach_near_arc
=> approach_track
=> precise pulse
=> kein downstream claim
```

Tracks weiter weg:

```text
visible tracks vorhanden, keiner nahe Exit
=> advance pulse
=> NORMAL bei 1 piece
=> PRECISE bei >= 2 pieces
=> kein downstream claim
```

### C2 -> C3 Landing-Lease

Vor jedem echten Exit-Pulse fragt C2 C3:

```text
C2: request_lease(predicted_arrival_in_s=0.5,
                  min_spacing_deg=60,
                  track_global_id=...)
C3: prueft aktuelle sichtbare Winkel um Intake/Drop-Zone
```

Wenn C3 ablehnt:

```text
C2 blocked_reason = lease_denied
kein Pulse
kein downstream claim
```

Wenn C3 akzeptiert:

```text
C2 speichert lease_id fuer track
C2 claimt c2_to_c3 debug slot
C2 feuert precise pulse
```

C3 konsumiert diese upstream lease intern ueber seinen LandingLeasePort, sobald
der Ablauf fuer diesen Handoff abgeschlossen bzw. die Lease ablaeuft. C2 selbst
publiziert kein Event fuer diesen Handoff; die physische Ankunft wird spaeter
ueber C3-Tracking erkannt.

### C2 Arrival Handling

Wenn C2 einen neuen actionable global_id sieht:

```text
seen_global_ids.add(global_id)
c1_to_c2 slot release
c1.notify_downstream_progress(now)
arrival diagnostics optional
```

Damit wird C1-Jam-Detection zurueckgesetzt.

### C2 Handoff-Retry

Wenn ein Track nach einem committed exit pulse weiterhin am Exit sichtbar ist:

```text
pending_downstream_claim exists for that global_id
```

Dann:

```text
if exit_handoff_spacing still active:
    handoff_wait / awaiting_downstream_arrival
else:
    retry precise pulse without new claim
```

Ab `handoff_retry_escalate_after` kann der Retry mehrfach pulsen.
Ab `stuck_retry_threshold = 5` wird auf einen aggressiveren NORMAL-Nudge
ohne neuen downstream claim eskaliert.

### C2 Density Snapshot

C2 berechnet zur C1-Steuerung:

```text
piece_count_estimate
visible_track_count
pending_track_count
occupancy_area_px
clump_score
free_arc_fraction
exit_queue_length
min_spacing_deg
largest_gap_deg
max_cluster_count_60deg
max_bbox_area_px
```

Diese Werte gehen in das C1-C2 Vision Burst Gate.

## C3 Aktuelle Funktionsweise

### Rolle

C3 ist der praezise letzte Singulation-Ring vor C4. Er nimmt von C2 an,
transportiert Richtung C4, und darf im aktuellen SectorCarousel-Modus nur
dann ejecten, wenn C4 vorher eine Landing-Lease gibt.

### Default-Parameter

```text
exit_near_arc = 20°
approach_near_arc = 45°
max_piece_count = 8
pulse_cooldown_s = 0.12
track_stale_s = 0.5
holdover_s = 2.0
downstream_claim_hold_s = 3.0
exit_handoff_min_interval_s = 0.85
handoff_retry_escalate_after = 2
handoff_retry_max_pulses = 2
stuck_retry_threshold = 5
downstream_landing_lease_required = True in SectorCarousel mode
```

### C3 available_slots()

C3 meldet C2 Headroom so:

```text
if purge_mode:
    0
elif ignored_transport_bad_actor_count >= 8:
    0
elif admission_piece_count >= max_piece_count:
    0
else:
    1
```

### C3 Tick-Ablauf

Vereinfacht:

```text
sweep expired downstream claims
fresh_tracks = non-stale c3 tracks
visible_tracks = visible tracks
update upstream landing bad-actor suppressor
update transport bad-actor suppressor if observing
active_visible_tracks = visible minus ignored bad actors
action_tracks = stable/actionable active tracks
update counts + latest visible angles
update transport velocity
credit new arrivals from C2
pick exit_track
pick approach_track

if hw_busy:
    pulsing / hw_busy
elif cooldown:
    pulsing / cooldown
elif purge_mode:
    purge pulse
elif exit_track has pending downstream claim:
    wait or retry
elif exit spacing active near exit/approach:
    handoff_spacing / exit_spacing
elif capacity_downstream <= 0 and exit_track:
    idle / downstream_full
elif no active tracks:
    idle
else:
    resolve mode and dispatch pulse
```

### C3 Track-Zonen und Mode

Exit Track:

```text
abs(angle) <= 20°
=> commit_to_downstream = true
=> PRECISE pulse
```

Approach Track:

```text
20° < abs(angle) <= 45°
=> PRECISE pulse
=> no downstream claim
```

Far Track:

```text
outside approach arc
=> NORMAL if one piece and no holdover
=> PRECISE if holdover active or piece_count >= 2
```

Holdover:

```text
after precise exit pulse, for 2 s:
    normal pulses are promoted to precise
```

### C3 -> C4 Landing-Lease

In SectorCarousel mode:

```text
C3 must have landing_lease_port
C3 must have track_global_id
C3 must receive lease_id from C4/SectorCarousel
```

Failure states:

```text
landing_lease_port_missing
landing_lease_track_id_missing
lease_denied
downstream_full
```

Success path:

```text
1. exit_track in commit arc
2. request C4/SectorCarousel landing lease
3. if granted: store lease_id by track id
4. claim c3_to_c4 debug slot, 3 s TTL
5. enqueue C3 precise pulse
6. after pulse command succeeds:
   publish C3_HANDOFF_TRIGGER with piece_uuid, track ids, landing_lease_id,
   c3_eject_started_ts, c3_eject_ts, expected arrival window
7. publish TrackTransit candidate to C4
```

Wichtig: Seit der SectorCarousel-Haertung darf der C3-Handoff-Trigger ohne
Landing-Lease nicht mehr von C4 akzeptiert werden.

Zusaetzlich bewertet C3 beim Eject den Handoff:

```text
handoff_quality = single_confident | suspect_multi | unknown
handoff_multi_risk = true/false
multi_risk_score
candidate_track_ids
candidate_global_ids
c3_exit_visible_count
c3_exit_actionable_count
c3_nearby_track_count
c3_min_spacing_deg
c3_cluster_score
c3_ignored_near_exit_count
```

Wenn C3 `suspect_multi` publiziert, markiert C4 Slot 1 konservativ als
`SUSPECT_MULTI` und routet den Slot zu `DISCARD`. Das ist absichtlich eine
V1-Policy: nicht retten, sondern stabil entsorgen.

### C3 Upstream Landing-Lease fuer C2

C3 stellt selbst einen `landing_lease_port()` fuer C2 bereit.

C2 fragt vor jedem C2->C3 Exit:

```text
C3: ist die upstream landing arc frei?
```

C3 prueft:

```text
keine aktive sichtbare Track-Winkel nahe intake/drop arc
und keine pending upstream lease
```

Default upstream landing arc:

```text
center = 180°
min spacing = 60°
TTL = 1.5 s
```

### Bad-Actor-Suppression in C3

C3 hat zwei Stationary-Bad-Actor-Suppressors:

1. upstream landing arc
   - stationaere Teile in der C2->C3 Landing-Zone koennen ignoriert werden,
     damit sie nicht dauerhaft neue Leases blockieren.

2. transport non-carrying
   - stationaere Tracks nach Motion-Attempts koennen fuer Transport-
     Entscheidungen ignoriert werden.
   - Wenn zu viele ignorierte Transport-Bad-Actors entstehen, blockiert C3
     upstream capacity:

```text
transport_bad_actor_capacity_block_count = 8
```

### C3 Handoff-Retry

Wie C2:

```text
pending_downstream_claim exists
=> wait during spacing
=> retry precise pulse without new claim
=> after retry threshold, repeat pulses
=> after stuck threshold, aggressive NORMAL nudge
```

### C3 Events

C3 publiziert:

```text
PERCEPTION_ROTATION
RUNTIME_HANDOFF_BURST
C3_HANDOFF_TRIGGER
TrackTransit candidate to C4 registry
```

`C3_HANDOFF_TRIGGER` ist fuer SectorCarousel wichtig:

```text
payload:
  piece_uuid
  track_global_id
  track_id
  landing_lease_id
  c3_eject_started_ts
  c3_eject_ts
  expected_arrival_window_s
```

## Alternative: SectionFeederHandler

Der `SectionFeederHandler` ist eine Main-inspirierte Alternative fuer C1-C3.
Er ist nur aktiv, wenn:

```text
feeder_mode = "section"
```

Dann werden `RuntimeC1/2/3` nicht getickt. Stattdessen entscheidet der Handler
direkt:

```text
if track in exit arc:
    pulse_precise
elif any track:
    pulse_normal
else:
    idle
```

Backpressure:

```text
C1 darf pulsen, wenn C2 intake clear und C2 piece cap nicht voll
C2 darf pulsen, wenn C3 intake clear und C3 piece cap nicht voll
C3 darf pulsen, wenn C4 admission allowed
```

Defaults:

```text
C1 cooldown = 1.5 s
C2 cooldown = 0.5 s
C3 cooldown = 0.3 s
C2 piece cap = 8
C3 piece cap = 8
C2 exit arc = 30°, intake center = 180°, intake arc = 30°
C3 exit arc = 20°, intake center = 180°, intake arc = 30°
```

Dieser Pfad ist deutlich einfacher, aber verzichtet auf die lease-basierte
Handoff-Transaktionslogik, Pending-Claims, C3->C4 Pflicht-Lease,
Handoff-Retry-Semantik und C1-Jam-Recovery.

## SectorShadowObserver

Der `SectorShadowObserver` ist read-only. Er vergleicht alle 0.5 s:

```text
Was wuerde Mains sektorbasierte Logik tun?
Was blockiert sorter-v2 gerade tatsaechlich?
```

Er schreibt optional JSONL nach:

```text
logs/sector_shadow.jsonl
```

Er beeinflusst keine Bewegung.

## Bestehende Tests

Vorhanden:

- `test_runtime_c1.py`
  - startup hold
  - downstream full
  - jam recovery
  - recovery admission
  - observation hold
  - maintenance pause
  - hw worker rollback / queue handling

- `test_runtime_c2.py`
  - exit pulse
  - approach pulse
  - advance pulse
  - downstream full
  - lease denied
  - arrivals release upstream
  - density snapshot
  - stale tracks
  - handoff retry/escalation
  - purge port

- `test_runtime_c3.py`
  - precise exit
  - landing lease required / denied / missing
  - C3_HANDOFF_TRIGGER with landing lease id
  - upstream landing bad-actor suppression
  - transport bad-actor suppression
  - TrackTransit candidate
  - holdover
  - downstream full
  - handoff retry/escalation
  - purge port

- `test_section_feeder_handler.py`
  - section decisions and cooldowns

- `test_sector_shadow_observer.py`
  - Main-style sector inference and divergence logging

- `test_feeder_ladder_selftest.py`
  - C1 pulse -> C2 arrival/progress -> C2 exit -> C3 arrival -> C3 C4 event
  - C2 landing lease denied
  - C3 C4 landing lease denied
  - C3 suspect_multi payload
  - stale C2 tracks
  - C1 recovery admission denied without burning attempt

Noch nicht vorhanden:

- ein Ladder-CLI/API wie `sector_carousel_ladder_selftest`
- eine lange "N Teile durch C1-C3 mit fake tracks/fake leases" Simulation

## Wichtigste Review-Fragen

1. Ist der aktuelle aktive `lease`-Pfad zu komplex fuer C1-C3, verglichen mit
   dem Main-artigen Section-Modell?

2. Sollte C1 als blinde Bulk-Quelle weiterhin ueber C2-Density, C3-Transitive
   und C4-Backlog gegatet werden, oder sollten wir auf eine einfachere
   feste Dosis-/Cooldown-Logik mit staerkerer C2/C3-Singulation wechseln?

3. Sind `target_low=1`, `target_high=3` fuer C1-C2 Vision Backpressure zu
   konservativ, wenn 6-10 Teile/min erreicht werden sollen?

4. Sollte C2->C3 ebenfalls zwingend ein vollwertiges Lease/Trigger-Protokoll
   bekommen, analog C3->C4, oder reicht das aktuelle C3-LandingLeasePort?

5. Sollte Double-Drop-/Multi-Object-Logik auch fuer C2/C3 als normale
   Reject-/Recovery-Klasse modelliert werden, oder ist das nur auf C4 relevant?

6. Welche zusaetzlichen Szenarien soll der neue `FeederLadderSelftest` noch
   abdecken?
   - pending handoff retry ueber mehrere Ticks
   - bad actor suppression zaehlt weiter fuer Multi-Risk
   - C2->C3 Arrival-Window und erwartete Ankunftszeit
   - mehrere Teile in kontrollierter Pipeline-Sequenz

7. Soll der Main-artige `SectionFeederHandler` als primärer C1-C3-Pfad
   reaktiviert und die `lease`-Runtimes reduziert werden, oder bleibt er nur
   ein Debug-/Fallback-Modus?

## Empfohlener naechster Schritt

Die vorhandene C1-C3 Phase-0-Simulation verbreitern und per API/CLI ausfuehrbar
machen:

```text
scripts/feeder_ladder_selftest.py
POST /api/rt/feeder/selftest
```

Szenarien:

```text
1. C1 single pulse creates C2 arrival/progress
2. C1 blocked by C2 density target
3. C2 exit pulse requires C3 landing lease
4. C2 lease denied blocks without motion
5. C2 handoff arrival releases C1 upstream claim
6. C3 exit pulse requires C4 landing lease
7. C3 missing lease blocks in sector mode
8. C3 accepted lease publishes C3_HANDOFF_TRIGGER
9. pending handoff waits then retries
10. stale tracks are ignored
11. bad actor suppression does not permanently deadlock
12. C1 jam recovery admission denies unsafe push
```

Ziel: Gleiches Vertrauen wie beim SectorCarousel, aber fuer den Feed-Pfad.
