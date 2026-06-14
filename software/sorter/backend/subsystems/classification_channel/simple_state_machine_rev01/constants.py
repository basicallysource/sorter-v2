LOG_TAG = "[C4-REV01]"

# The carousel travels REVERSE (decreasing relative angle) to take the short path
# from where a piece lands to the precise zone and then the fall-off. Perception
# returns the converge gap as a positive "advance toward target" magnitude in the
# travel direction (see ``perception.arcs._leadingExitApproach`` with
# ``ChannelDef.reverse``); the state machine turns that into a physical move by
# issuing NEGATIVE output degrees. ``startOutputMove`` is sign-preserving all the
# way to firmware, so a negative argument is a valid reverse relative move.
C4_TRAVEL_SIGN = -1.0
