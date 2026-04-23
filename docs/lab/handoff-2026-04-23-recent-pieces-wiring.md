# Handoff — Recent Pieces live broadcast + C4 transport tuning

_Date: 2026-04-23 · Branch: `sorthive`_

## TL;DR

Dashboard-Panel "Recent Pieces" hat live gar keine Events bekommen und beim WS-Reconnect alle `registered`/`classified`-Einträge stumm gedroppt. Drei Commits, alles gepusht-ready; End-to-End über WS verifiziert, Unit-Test grün.

## Was committed ist

| Commit    | Bereich                | Inhalt                                                                       |
|-----------|------------------------|------------------------------------------------------------------------------|
| `855658c` | `irl/config.py`, `rt/runtimes/c4.py` | C4-Transport auf ~1 rpm: `transport_speed_scale 6→20`, `cooldown 250→80 ms` |
| `47e4de7` | `rt/projections/piece_dossier.py` + Test | Projection ruft nach `remember_piece_dossier` zusätzlich `remember_recent_known_object` und `shared_state.broadcast_from_thread({tag:"known_object",...})` — live Push + Replay-Ring-Mirror |
| `f8a645c` | `defs/events.py`, `frontend/…/events.ts` | `PieceStage`-Enum um `registered` + `classified` erweitert (vorher droppte Pydantic die rt-Stages beim Replay silent) |

Git status: clean bis auf `software/sorter/local_state.sqlite` (Runtime-DB, nicht ins Repo).

## Ursache & Lösung (Recent Pieces)

**Die kaputte Kette:**
1. rt/ feuert `PIECE_REGISTERED/CLASSIFIED/DISTRIBUTED` auf Event-Bus.
2. `piece_dossier`-Projection upsertete bisher nur in SQLite (`piece_dossiers` Tabelle) — **stoppte dort**.
3. Dashboard `RecentObjects.svelte` liest aus `ctx.machine?.recentObjects`, gefüttert vom WS-Event `known_object`.
4. Den Event hat niemand gefeuert (weder live noch Ring-Mirror), also: Panel leer zwischen Page-Reloads.
5. Selbst der Connect-Replay hätte nix gebracht: Pydantic-Validation bei `server/api.py:749` lehnte `stage="registered"` ab (Enum kannte nur `created/distributing/distributed`) → stiller Skip im `except Exception`.

**Fix:** Projection ruft jetzt drei Side-Effects ab (lazy-imports, damit rt/ layer-sauber bleibt):
- `remember_piece_dossier` (bestand)
- `remember_recent_known_object(merged_row)` — Ring-Population
- `broadcast_from_thread({"tag":"known_object","data":merged_row})` — Live-Fanout

Plus Enum-Erweiterung damit Replay nicht mehr dropt.

## Verifiziert

- **Unit-Test** `rt/tests/test_piece_dossier_flow.py::test_projection_mirrors_into_recent_known_objects` — 4/4 grün, 0.27 s.
- **Live**: `2eda272618f3 stage=registered cls=pending` kam über WS an, nachdem C4 ein Piece registriert hatte.
- **Replay**: nach fresh WS-Reconnect 10 `known_object`-Events mit `stage=registered` durch Validation.

## C4 auf 1 rpm

- Theoretische Burst-RPM bei aktuellen Settings: ~12 rpm Karussell (3200 µsteps/rev · default 1000 µsteps/s · 20× scale, 6°/step, 80 ms cooldown). Das 1-rpm-Ziel ist locker innerhalb des erlaubten Fensters.
- Live-`observed_rpm` (PolarTracker, vision-basiert) war während der Session meist `None` oder niedrig, weil C4 selten confirmed-real Tracks hatte (C1 meist im `jam_recovery_exhausted` hängend). Ohne fließende Pipeline keine belastbare Messung.
- **Verbleibend**: bei laufender Piece-Flow einmal die observed_rpm-Bubble am Dashboard gegen die beobachtete Karussell-Geschwindigkeit abgleichen. Falls zu langsam: `DEFAULT_TRANSPORT_COOLDOWN_MS` weiter runter, nicht scale höher.

## Offene Fäden / Known Issues

- **C1 Jam-Recovery**: `jam_recovery_exhausted` ist sticky, es gibt keinen HTTP-Endpoint zum `clear_pause()`. Aktuell: nur Supervisor-Restart bringt C1 zurück. Wenn der physische Jam zwischen zwei Restarts nicht behoben ist, läuft C1 direkt wieder in Exhausted rein. Kandidat für einen kleinen `/api/rt/c1/clear-jam` Endpunkt.
- **Monotonic-vs-Wallclock-Timestamps im Dossier**: `first_carousel_seen_ts` kommt aus `now_mono` (monotonic, Werte ~216000 s). FE vergleicht mit `Date.now()/1000` (~1.7e9). Der `shouldShowInRecentPieces`-Gate nutzt nur Truthy-Check, also nicht akut kaputt — aber Delivered-Dedup-Fenster (`now_s - ts > 15`) funktioniert für monotonic-Timestamps de facto als "immer alt". Sollte beim nächsten Touch auf `ts_mono`-Ownership umgestellt werden.
- **Task #11 (pending)**: Legacy `angle`-Felder aus `arc_params`-Schema raus — war schon vor der Session offen.
- **`runtime_variables`-Pfad (Plan `fancy-cuddling-squirrel.md`)**: vollständig weg, verifiziert per `rg`. Frontend `rest.ts` trägt die toten OpenAPI-Einträge noch bis zum nächsten Codegen — nicht hand-gepatcht.

## Relevante Dateien (falls jemand reinspringt)

- `software/sorter/backend/rt/projections/piece_dossier.py` — Bridge rt-Events → SQLite + WS
- `software/sorter/backend/server/api.py:728-762` — WS-Connect-Replay
- `software/sorter/backend/server/shared_state.py:157-172` — `broadcast_from_thread` Thread-Safe-Helper
- `software/sorter/backend/local_state.py:1079,2177` — Dossier + Recent-Known-Objects-Ring
- `software/sorter/frontend/src/lib/components/RecentObjects.svelte` — UI-Panel
- `software/sorter/frontend/src/lib/recent-pieces.ts` — FE-Filter-Logik (`hasC4Evidence` etc.)

## Architektur-Notiz

`piece_dossier.py` ist jetzt der **einzige** Bridging-Punkt zwischen rt-Event-Bus und der WS-`known_object`-Welt. Lazy-Imports halten rt/ frei von Server-Boot-Coupling (Principle 2/3). Wer neue Lifecycle-Events dazufügt: Topic + Stage-Mapping dort, und Enum in `defs/events.py` nachziehen.
