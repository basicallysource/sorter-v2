from defs.consts import CLASSIFICATION_CHANNEL_CLOCKWISE

LOG_TAG = "[C4-REV01]"

# When a hosted color provider is selected, its request runs in parallel with
# the Brickognize fan-out and we wait at most this long (measured from request
# start) for its answer before falling back to Brickognize's color. Well under
# classify_timeout_s (30 s default) so the color join can never be what times a
# piece out.
HOSTED_COLOR_JOIN_BUDGET_S = 10.0

# Which way the carousel physically turns to advance a piece toward the fall-off.
# Perception returns the converge gap as a positive "advance toward target"
# magnitude in the travel direction (see ``perception.arcs._leadingExitApproach``
# with ``ChannelDef.reverse``); the state machine turns that into a physical move
# by multiplying by this sign. ``startOutputMove`` is sign-preserving all the way
# to firmware. The counter-clockwise build issues NEGATIVE output degrees; the
# clockwise build flips to positive. Driven by the single source of truth in
# defs.consts so it can never disagree with the crop/eject direction. NOTE: the
# +1/-1 ↔ physical-direction mapping is a best guess until verified on hardware;
# if a clockwise flip spins the platter the wrong way, invert this sign.
C4_TRAVEL_SIGN = 1.0 if CLASSIFICATION_CHANNEL_CLOCKWISE else -1.0
