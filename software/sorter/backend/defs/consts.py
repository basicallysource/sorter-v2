# Main-loop pacing. The loop runs controller.step() then sleeps this long.
# With the Rev03 vision refactor the coordinator step is ~15 ms (was ~590 ms),
# so the sleep is now the dominant term in the loop period. 10 ms gives a
# ~40 Hz ceiling (15 ms step + 10 ms sleep) — comfortable headroom above the
# 30 Hz target — while still yielding the GIL to producer/API/encode threads
# every tick. Raise back toward 20 ms if loop CPU becomes a concern.
LOOP_TICK_MS = 10

CHANNEL_SECTION_COUNT = 360
CHANNEL_SECTION_DEG = 360.0 / CHANNEL_SECTION_COUNT

CH3_PRECISE_SECTIONS = range(315, 360)
CH3_DROPZONE_SECTIONS = range(45, 119)
CH2_PRECISE_SECTIONS = range(304, 338)
CH2_DROPZONE_SECTIONS = range(101, 180)
