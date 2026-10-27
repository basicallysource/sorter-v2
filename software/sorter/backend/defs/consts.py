# Main-loop pacing. The loop runs controller.step() then sleeps this long.
# With the Rev03 vision refactor the coordinator step is ~15 ms (was ~590 ms),
# so the sleep is now the dominant term in the loop period. 10 ms gives a
# ~40 Hz ceiling (15 ms step + 10 ms sleep) — comfortable headroom above the
# 30 Hz target — while still yielding the GIL to producer/API/encode threads
# every tick. Raise back toward 20 ms if loop CPU becomes a concern.
LOOP_TICK_MS = 10

# A piece is "dead" once it can no longer reach the distributed stage. The
# broadcaster reaps any in-flight piece (created/classified but not distributed,
# and not already aborted) that has emitted no KnownObject update for this long
# while the machine is running: it is flipped to ``dead`` and a final event is
# broadcast so the UI and the per-piece lookup drop it instead of leaving it
# wedged in e.g. "classified" forever. This is the time-based analogue of the
# teardown ``aborted`` flag (machine stop / reset mid-capture). A genuinely-slow
# piece that later progresses re-emits with dead=False and self-recovers.
STUCK_PIECE_TIMEOUT_S = 30.0
# How often the broadcaster scans the known-object lookup for stuck pieces. A
# cheap dict walk; 1 Hz is ample against the 30 s threshold.
STUCK_PIECE_REAP_INTERVAL_S = 1.0

# Classification channel (C4) piece-travel direction. The single source of truth.
# False = counter-clockwise (the historical/default build); True = clockwise
# (matching C2/C3). Two otherwise-independent sites read this so they can never
# disagree (a half-flipped state — perception says one way, motor goes the
# other — is incoherent):
#   - perception eject math:  perception/channel.py          ChannelDef.reverse
#   - motor move sign:        classification SM              C4_TRAVEL_SIGN
# The zones (``zones/``) always run forward, clockwise on screen: flipping this
# to False would need them to run the other way too.
CLASSIFICATION_CHANNEL_CLOCKWISE = True

# The port the backend API serves on. main.py and api_only.py bind it, and the
# Hive heartbeat reports it (machine_network.py) so the machine's Hive page can
# point API users at it.
BACKEND_PORT = 8000
