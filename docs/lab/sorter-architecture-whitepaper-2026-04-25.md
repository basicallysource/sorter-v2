# LEGO-Sorter v2 — Architektur-White-Paper für Research-Input

**Stand:** 2026-04-25 abend, nach einer Iterations-Sitzung mit Ziel 10 PPM.
**Zweck:** Dieses Dokument fasst kompakt zusammen, wie der Sorter heute aufgebaut ist, welche Probleme wir noch sehen und an welchen Stellen wir gezielt Outside-Feedback brauchen. Es ist self-contained — der Leser braucht den Codebase nicht.

---

## 1 Mission und harte Randbedingungen

- **Zielmetrik:** 10 PPM (Pieces Per Minute) sustained, mit *Bin-Correctness* als harter Nebenbedingung. Lieber ein Teil im Reject als ein Teil im falschen Bin.
- **Heute:** Saubere Pipeline (kein Zombie-Drift, 1:1 Klassifikationen vs. Distributor-Commits), aber nur **3,3 PPM** über 5 Minuten gemessen. Vorher waren wir kurz auf 4,7 PPM, allerdings chaotisch.
- **Bottleneck heute:** C4 (klassifikationskarussell) hungert, weil C3 Teile nicht schnell genug spaced übergibt. C1-Burst-Verhalten ist auch nicht völlig sauber.
- **Workload:** Heterogene LEGO-Teile, viele *Near-Duplicates* (gleicher Typ, gleiche Farbe), viele *non-rigid Surrogate* (Reifen, Gummischläuche), tendenzielle Klumpen-/Burst-Eingangsmuster aus dem Schüttgut.

## 2 Mechanischer Aufbau

```
C1 (Bulk-Rotor)  →  C2 (Glättungs-Drehteller)  →  C3 (Vorsortier-Drehteller)
                                                   ↓
                                                  C4 (Klassifikations-Karussell)
                                                   ↓
                                                  Distributor (Drehscheibe + Chute → 16 Bins)
```

- **C1** ist eine Schüttgut-Trommel, die portionsweise Teile auf C2 schiebt. Schubartiger Output ist physikalisch typisch.
- **C2** ist ein flacher, reibgetriebener Drehteller. Aufgabe: Klumpen entzerren, Teile in lockere Reihe bringen, an C3 übergeben.
- **C3** ist erneut ein flacher, reibgetriebener Teller mit Drop-Zone-Kamera. Aufgabe: einzelne Teile sicher zur C3→C4-Kante transportieren und einzeln ans Karussell übergeben.
- **C4** ist ein präzise positionierbares Karussell (Stepper, Encoder), das ein Teil unter eine fixe Klassifikationskamera fährt, dann an die Auswurfposition.
- **Distributor** ist eine zweite Drehscheibe, die einen Chute über 16 Bins positioniert; ein einzelner Auswurf fällt durchs Chute in den richtigen Bin.

Wichtig physikalisch: C2 und C3 sind reibgetrieben, ohne Carrier oder Pockets. Ein Teil kann auf dem Teller rutschen, drehen, kollidieren, kurzzeitig verdeckt werden — und nichts hindert es, sich nicht-vorhersehbar zu bewegen. Encoder sagt nur, wie weit sich der Teller gedreht hat, **nicht** wo das Teil ist. C4 ist ähnlich, aber mit deutlich saubererer Bewegung dank Kunststoffrand.

## 3 Software-Topologie

Pro Kanal eine Runtime (`RuntimeC1`, `RuntimeC2`, `RuntimeC3`, `RuntimeC4`, `RuntimeDistributor`). Ein Orchestrator drischt sie reihum durch eine pro-Tick-`step()`-Schleife. Slots zwischen Runtimes sind nur noch Capacity-Buchhaltung mit TTL — die früher harten Slot-Gates wurden entfernt, weil sie genug Throughput killten und gleichzeitig keinen echten Schutz gaben.

Pro Kamera (C2/C3/C4) läuft separat ein **YOLO-OBB-Detektor** (Ultralytics) und ein **Multi-Object-Tracker via BoxMot** (ByteTrack als primary). Tracker-IDs sind „raw_track_ids" und gelten als Evidenz, nicht als Identität.

Live-Tuning: Alle relevanten Parameter sind über `/api/rt/tuning` zur Laufzeit änderbar (Lease-Spacing, Zone-Geometrie, Pulse-Cooldowns, Stepper-Profile, …). Lab-Defaults sind bewusst in den Code-Konstruktor geschrieben, damit sie über Restarts hinweg erhalten bleiben.

## 4 Die zentrale Innovation: PieceTrackBank

Das Herzstück nach einem mehrstufigen Architektur-Cutover ist die `PieceTrackBank`. **Sie trennt System-Identität (`piece_uuid`) von Tracker-Identität (BoxMot raw_track_id).**

### 4.1 Was die Bank speichert
Pro Stück:
- `piece_uuid` (12-Char Hex, durable über die ganze C4-Lebenszeit)
- `state_mean`, `state_covariance` (4-dim Kalman: Winkel, Radius, Winkelgeschw., Radialgeschw.)
- `raw_track_aliases` (Set von BoxMot-IDs, die jemals diesem Stück zugeordnet wurden)
- `embedding_mean` (gleitender Mittelwert OSNet-ReID-Vektoren, optional)
- `extent_rad` (geglättete angulare Stück-Footprint, AABB-basiert oder OBB falls verfügbar)
- `motion_mode` (carried / sliding / collision_or_clump / edge_transfer / lost_coast)
- `lifecycle_state` (TENTATIVE → CONFIRMED_UNCLASSIFIED → CLASSIFIED_CONFIDENT → LOST_COASTING → FINALIZED_LOST oder EJECTED)
- `class_label`, `confirmed_real_observations`, `eject_committed` etc.

### 4.2 Tray-Frame-Koordinaten
Jede Messung wird vor dem Update **encoder-subtrahiert**: `a_tray = a_camera − encoder_angle`. Damit lebt der Kalman-Zustand in tellerfesten Koordinaten — die Trägerrotation ist absorbiert, der Filter sieht nur noch echtes Slip-Verhalten plus Mess-Rauschen.

### 4.3 Update-Pfad
- **predict_all(t)**: konstantes-Geschwindigkeit-Modell pro Stück, Process-Noise `Q(dt)` je nach `motion_mode` skaliert (`COLLISION_OR_CLUMP` × 4, `LOST_COAST` × 6, `CARRIED` × 0.5). Variance-Cap: `sigma_a ≤ 30°` damit ein lange unsichtbares Tentative nicht „die ganze Scheibe" beansprucht. Lifecycle wird nach jedem Predict reevaluiert.
- **associate_and_update(meas)**: Mahalanobis-Cost-Matrix mit χ²-Gate (default 9.21 ≈ 99 %), softer Penalty wenn raw_track_id schon ein anderes piece_uuid aliased, greedy 1:1-Assignment.
- **update_with_measurement(uuid, meas)**: separater Pfad für C4 (das die Bank manuell mit `_bank_predict` + `_bank_observe` füllt). Bei Mahalanobis² > snap_chi2_threshold (default 50): kein Kalman-Blend, sondern *Snap* — Zustand auf die Messung setzen, Velocity = 0, Cov reset, Mode = `COLLISION_OR_CLUMP`. Hat sich als Brandmauer gegen Drift bei großen Sprüngen bewährt.

### 4.4 Conf-weighted R (heute hinzugefügt)
Mess-Rauschen R ist nicht mehr konstant: `R_eff = R_base * (1 + (1−conf)² · conf_r_scale)`, default `conf_r_scale=8`. Eine 0,95-conf-Detektion zieht mit ~1,02 × R_base, eine 0,4-conf-Detektion mit ~3,9 × R_base, eine 0,2-conf-Detektion mit ~6,1 × R_base. Effekt: *wackelige Detektionen drücken den Filter nicht mehr in falsche Richtungen*; saubere bleiben gleich wirksam. Snap-Pfad bleibt als Letzt-Anker.

### 4.5 Lifecycle-Logik

```
TENTATIVE (≤2 Detections / nicht-confirmed_real)
   ├── confirm_min_real Treffer + confirm_min_detections gesehen
   │     → CONFIRMED_UNCLASSIFIED
   ├── Stille > coast_after_silence_s (0,6 s) → LOST_COASTING
   └── Stille > finalize_lost_after_silence_s (4,0 s) → FINALIZED_LOST
CONFIRMED_UNCLASSIFIED + Klassifikation gebunden
   → CLASSIFIED_CONFIDENT
   → bei eject_committed → EJECTED
```

`is_dispatch_eligible` und `is_chute_blocking` lesen den Lifecycle. Posterior-Singleton-Dispatch (siehe §6) blockt den Auswurf, wenn ≥2 chute-blocking PieceTracks im Auswurf-Fenster liegen.

## 5 Lease-basiertes Escapement (C2→C3, C3→C4)

Statt „pump-and-pray" haben Up- und Downstream-Channel ein **Reservierungsprotokoll**:
1. Upstream sieht ein Stück nahe der Exit-Kante.
2. Upstream ruft `LandingLeasePort.request_lease(piece_uuid, predicted_arrival_in_s, min_spacing_deg)` am Downstream auf.
3. Downstream prüft: liegt der reservierte Landebogen frei? (Bank kennt alle aktuellen Track-Winkel mit σ.) Falls ja: TTL-bewertete Reservierung wird angelegt, Lease granted.
4. Erst dann darf der Upstream einen Exit-Pulse ausführen.
5. Nach Ankunft / TTL-Ablauf wird die Reservierung consumed.

Parameter (heute live-tunable):
- `lease_min_spacing_deg`: 30° (C3→C4), 60° (C2→C3) — *primärer Throughput-Hebel*
- `lease_transit_estimate_s`: 0,5–0,6
- `lease_ttl_s`: 1,5
- C3 zusätzlich `upstream_lease_arc_center_deg=180°` und `upstream_lease_min_spacing_deg=60°` für die C2-Reservierung an C3

Stuck-Recovery: wenn ein Exit-Pulse `stuck_retry_threshold` mal (default 5) ohne erfolgreiche Übergabe wiederholt wurde, eskaliert von PRECISE auf NORMAL-Mode (mehr Drehmoment / breiterer Pulse). Adressiert „Reifen klebt am Rand"-Fälle.

## 6 Posterior-Singleton-Dispatch + Chute-Geometrie

Der Distributor commit-et nur dann auf einen Auswurf, wenn **genau ein chute-blocking PieceTrack** im Auswurf-Fenster liegt — also keine Geschwister, keine Ghosts, keine LOST_COASTING-Kandidaten in der Nähe. `extent_rad` aus der Bank widening-t das Fenster, sodass ein langer Technic-Achsenstift nicht als Punkt behandelt wird.

Stage 4 schedult die Karussell-Bewegung gegen die Distributor-`next_ready_time(now)`-API: wenn der Chute noch in Bewegung ist, hält C4 den nächsten Step zurück und leitet kein verfrühtes Vorbeitransportieren ein.

## 7 σ-skalierte Zonen (heute hinzugefügt)

Die ZoneManager-Geometrie auf C4 (Intake-Half-Width + Guard) war bisher konstant. Neu: `half_width_eff = base + zone_sigma_k * sigma_a_deg`, gecapt auf `zone_max_half_width_deg`. Bei sicherem Track (σ_a klein, ~0,5°) zählt nur die Basis (7°); bei unsicherem (σ_a groß, bis 30° Cap) widening bis 22° Cap. Dadurch packt das System enger, wenn die Bank confident ist, und reserviert großzügiger, wenn nicht.

## 8 Cross-Channel Re-Identification

OSNet (Torchreid-Architektur) läuft als ReID-Shadow auf jeder Detektion. Embedding-Mean wird in der Bank pro Stück aggregiert. Eine `TransitStitcher`-Komponente macht *nur* den C3→C4-Handoff: ein Track, der C3 verlässt, wird beim erstmaligen Auftauchen auf C4 mit Topologie- und Zeit-Constraints + Embedding-Distanz gegen die letzten C3-Exits gematcht und so dem ursprünglichen `piece_uuid` zugeordnet. **Wichtig:** OSNet ist Off-the-Shelf-Pretrained (Person-ReID), nicht auf LEGO-Crops fein-tunet.

## 9 Step-Debugger und Observability

`/api/rt/debug/*` + `/dashboard/debug` UI: pause / step / step n / inspect orchestrator + einzelne Runtimes. Bank-Tracks, pending Leases, Slot-Capacities sind live einsehbar. Run-Logs landen in `logs/runs/<timestamp>_<label>/` mit JSON-Snapshots, CSV-Exports und Klassifikations-Logs.

---

## 10 Aktuelle offene Probleme

### 10.1 Throughput-Decke ~3,3 PPM
- C4 bekommt nur 1–3 Dossiers parallel; theoretisch passen 9 (max_zones).
- Lease-Spacing 30° an C3→C4 ist konservativ und scheint der primäre Limiter zu sein. **Live-Test bei 20° steht aus** (gerade exposed).
- Hypothese: C4-Admission-Logik (`is_arc_clear` + `dropzone_clear`) ist redundant mit dem Lease-Garant und blockt zusätzlich.

### 10.2 C1-Burst-Charakteristik
- Trotz nachjustierter Recovery-Push-Schedule (10°/20°/35°/60°/90° statt vorher 15°/45°/90°/180°/360°) sehen wir gelegentlich 50+ Teile in einem Schwall auf C2.
- Recovery hat 5 eskalierende Levels, jedes mit Shake (n × ±recovery_deg) + Forward-Push. Korrekt geportet aus pre-cutover Code, aber die Schwellenwerte sind heuristisch.
- Frage: gibt es einen *load-celled* / *vision-based* C1-Output-Estimator-Ansatz, der adaptiv pulsen statt nach Heuristik eskalieren könnte?

### 10.3 Klumpen / non-rigid Surrogate
- Reifen, Gummischläuche, Schraubenzieher-artige Pieces stoßen sich nicht klassisch ab — sie haken sich. Stuck-Recovery (NORMAL-Mode-Eskalation) hilft, aber „burst quarantine" oder Recirculation gibt es bei uns nicht (kein physischer Recirc-Pfad).
- Frage: Welche pragmatischen Strategien haben Industrie-Singulatoren für non-rigid Items?

### 10.4 ReID-Qualität für visuelle Near-Duplicates
- OSNet läuft mit Person-ReID-Gewichten. Für „zwei identisch gelbe 2×2-Plates" ist das vermutlich kaum besser als geometrisches Matching alleine.
- Wir haben Trainings-Crops über Auto-Sample-Pipeline (Sample-Lifecycle in der Hive-Plattform) und könnten domänen-fein-tunen. Ist nicht passiert.
- Frage: Wieviel Hebel hätte ein domain-fein-tunes OSNet? Lohnt sich Triplet-Loss-Training mit unseren paar tausend gelabelten Crops, oder erst ab ≥10k?

### 10.5 Snap-vs-Kalman-Übergang
- Heute haben wir zwei orthogonale Sicherungen: conf-weighted R (smooth) plus snap-on-residual (hart, nur > Mahalanobis² 50). Die Schwelle 50 ist heuristisch.
- Frage: Gibt es ein principled Verfahren (Schmidt-Kalman, IMM mit explizitem „large-jump"-Mode, etc.), das den Snap durch eine kontinuierliche Mode-Wahrscheinlichkeit ersetzt?

### 10.6 Lokale JPDA / MHT in Konfliktzonen
- Heute machen wir greedy Mahalanobis-Assignment global. Das genügt für die meisten Frames.
- Konfliktzonen (Drop-Zonen, C3→C4-Handoff, C4-Exit-Fenster) sind aber genau die Stellen, wo wir Identitäten verlieren oder Klumpen falsch entscheiden.
- Frage: Lohnt sich ein lokaler JPDA-/MHT-Schalter (nur wenn ≥2 Tracks im Gate eines Measurements liegen), oder sind die zusätzlichen Gewinne klein genug, dass eher Datenqualität-Investments (R-Modell, ReID-Fein-Tuning) Vorrang haben?

### 10.7 Prä-Detection De-Rotation der Frames
- Wir transformieren *post-detection* in Tray-Koordinaten; das Bild geht weiter im Camera-Frame in YOLO.
- Vorschlag aus Vor-Research: das Bild selbst per `cv2.warpAffine` so de-rotieren, dass der Teller pixelfest ist. Vorteil: stationäre Hintergrund-Artefakte (Kratzer, Klebereste) wären für YOLO konsistent → weniger Ghost-Detektionen, optical-flow Plug-in würde sinnvoll werden.
- Bedenken: Detector-Latenz, Tray-Center-Kalibrierung, Anti-Aliasing-Verluste. Wir haben es nicht getestet.
- Frage: Lohnt sich der Aufwand bei unserer Frame-Rate und Detector-Latenz?

### 10.8 ZoneManager-Geometrie vs. Bank-Wahrheit
- Wir haben zwei parallele Repräsentationen für „wo ist welches Stück": die Bank (mit σ und Lifecycle) und der ZoneManager (geometrische Exklusionsbögen).
- Sie sind nur lose synchronisiert: `_sync_owned_tracks` befüllt den ZoneManager aus den Tracks. Mit den σ-skalierten Zonen wird der ZoneManager teilweise redundant zur Bank — er kennt im Wesentlichen die gleiche Information, nur statisch.
- Frage: Sollten wir den ZoneManager auflösen und Admission/Window-Checks direkt gegen die Bank ausführen? Oder lohnt sich die separate Layer als Cache / Performance-Optimierung?

### 10.9 Distributor-Scheduling
- Heute nur ein „is the chute settled in time?" Check. Keine *Lookahead*-Optimierung, die bei mehreren ready-able Pieces am Karussell die Reihenfolge so wählt, dass die kombinierten Bin-Bewegungen minimiert werden.
- Frage: Lohnt sich ein TSP-artiger Optimizer auf den nächsten 5–10 ready Pieces (Travel-Time-Matrix Bin↔Bin), oder bleibt der C3→C4-Lease-Bottleneck so hart, dass der Distributor nie wirklich wartet?

### 10.10 OBB-vs-AABB-Extent
- Aktuell schätzen wir `extent_rad` aus AABB-Diagonale + Radius. Bei langen Achsen (Technic-Lift-Arms) overshoot-et das den realen tellerfesten Footprint.
- Detector ist YOLO-OBB, also Orientierungswinkel ist verfügbar. Wir nutzen ihn aber noch nicht voll für die Extent-Berechnung.
- Frage: Trivialer Code-Change. Vermutlich kleiner Hebel — aber lohnt es sich, oder hat der Mahalanobis-Gating-Fehler andere dominantere Ursachen?

---

## 11 Konkrete Fragen, an denen wir gezielt Outside-Feedback wollen

In Reihenfolge des erwarteten Hebels:

1. **Throughput unter 10 PPM:** Was ist der *next* sinnvolle Schritt nach dem Lease-Spacing-Tuning? C4-Admission relaxieren? Mehrfach-Reservierungen pro Lease-Tick? Anderes Throttling-Modell als das jetzige Single-Lease-pro-Edge?

2. **Confidence-weighted R Schwellen:** Unser `conf_r_scale=8` ist heuristisch. Gibt es Literatur zu konkreten Mappings `score → R`, die in YOLO+MOT-Settings als gut validiert gelten? ConfTrack-Paper nutzt eine ähnliche Idee — sind ihre Schwellen direkt übertragbar?

3. **σ-scaled Zone Cap:** `zone_max_half_width_deg=22` ist eine Hand-Wahl. Mathematisch sauberer wäre vermutlich „95-%-Konfidenz-Intervall" ⇒ k≈2 statt 1,5, oder eine Cap-freie Lösung mit explizitem `is_dispatch_eligible`-Filter, der unsichere Tracks als blocking-but-not-dispatchable markiert.

4. **Klumpen / non-rigid Items:** Konkrete Industrie-Praktiken für Reifen / Gummi auf flachen Drehtellern *ohne* Carrier? Software-Strategien, die uns nicht durch fehlenden Recirculation-Pfad blocken.

5. **OSNet Domain-Fine-Tuning:** Mindestmenge Crops? Triplet-Loss vs. ArcFace? Wir haben eine Sample-Pipeline mit Auto-Crops + manueller Verifikation in einer separaten Web-App.

6. **Snap → IMM-Modus:** Soll der hart-snappende Pfad durch einen Multi-Hypothesen-Modus mit „normal" / „jumped" Track-Komponenten ersetzt werden? Stone-Soup hat fertige IMM-Implementations.

7. **ZoneManager-Auflösung:** Hat jemand schon erfolgreich einen separaten Geometrie-Layer komplett zugunsten eines stochastischen Tracks-mit-Extent-State eliminiert? Welche Performance-/Komplexitäts-Trade-offs sind real?

8. **Image-level Frame De-Rotation:** Validierte Cost-/Benefit-Berichte aus der Industrie für Pixel-Tray-Stabilisierung vor MOT-Tracking?

---

## 12 Was Outside-Feedback *nicht* mehr bringen würde

Diese Punkte halten wir für architektur-stabil und brauchen kein weiteres Bohren:
- **piece_uuid getrennt vom Tracker-ID:** validiert von zwei unabhängigen Researches.
- **Tray-Frame-Koordinaten via Encoder als Prior:** keine Alternativen ernsthaft konkurrenzfähig.
- **Lease/Escapement statt push-and-pray:** unmittelbarer beobachteter Effekt nach Implementierung.
- **BoxMot/ByteTrack als Detector-side-Tracker, nicht als System-Identität:** Validiert von beiden Researches.

---

## 13 Run-Daten

Im Ordner `logs/runs/` liegen ca. 30 Runs der letzten Tage als JSON+CSV-Logs. Wenn ein Reviewer konkrete Beispiele für ein Phänomen sehen möchte, können wir gezielt Runs vor/nach einer Änderung ziehen. Aktuelle Baseline ist `2026-04-25_18-30-05_opus-baseline-60s/`.

---

**Zusammenfassung:** Architektur ist nach mehreren Cutovers an einem stabilen, validierten Punkt (PieceTrackBank + Lease + Posterior-Singleton + Tray-Frame). Throughput-Bottleneck verschiebt sich gerade von „Track-Identität verlieren" zu „Lease-Spacing zu konservativ" — also vom Tracking-Layer zum Flow-Control-Layer. Die in §11 nummerierten Fragen sind die Stellen, an denen wir den größten Hebel von externem Feedback erwarten.
