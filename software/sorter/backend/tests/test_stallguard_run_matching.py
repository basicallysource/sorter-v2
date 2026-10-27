"""A StallGuard recording counts for tuning only under the driver settings it was
made with: the run current, the microstepping and the chopper mode."""

from server.routers.stallguard import _run_matches_driver

RUN = {"speed": 2000, "irun": 29, "microsteps": 8, "stealthchop": True}


def test_a_run_at_another_current_does_not_count():
    assert not _run_matches_driver(RUN, irun=24, microsteps=8, stealthchop=True)


def test_a_run_with_the_same_settings_counts():
    assert _run_matches_driver(RUN, irun=29, microsteps=8, stealthchop=True)


def test_settings_not_asked_for_are_not_checked():
    assert _run_matches_driver(RUN, irun=None, microsteps=None, stealthchop=None)
    assert _run_matches_driver(RUN, irun=29, microsteps=None, stealthchop=None)


def test_a_run_that_did_not_record_a_setting_does_not_match_it():
    assert not _run_matches_driver({"speed": 2000}, irun=24, microsteps=None, stealthchop=None)
    assert not _run_matches_driver(None, irun=24, microsteps=None, stealthchop=None)
    assert _run_matches_driver(None, irun=None, microsteps=None, stealthchop=None)
