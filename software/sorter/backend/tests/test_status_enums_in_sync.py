"""defs.events.ClassificationStatus is a copy of defs.known_object's; the
event converter maps by value, so a status added to one but not the other
crashes the main loop (seen 2026-09-05 with low_confidence)."""
from defs import events, known_object


def test_every_known_object_status_has_an_event_status() -> None:
    for status in known_object.ClassificationStatus:
        assert events.ClassificationStatus(status.value) is not None


def test_every_event_status_exists_on_known_object() -> None:
    for status in events.ClassificationStatus:
        assert known_object.ClassificationStatus(status.value) is not None
