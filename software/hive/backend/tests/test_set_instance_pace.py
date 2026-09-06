"""Pace of a set instance: rate over the last hour, ETA to 90 %, plateau."""
from datetime import datetime, timedelta, timezone

from app.services.set_instances import pace

NOW = datetime(2026, 9, 6, 4, 0, tzinfo=timezone.utc)


def _at(minutes_ago: int) -> datetime:
    return NOW - timedelta(minutes=minutes_ago)


def test_no_pace_without_twenty_minutes_of_history() -> None:
    assert pace([(_at(10), 5)], found=8, needed=100, now=NOW) == {"rate_per_hour": None, "eta_hours": None, "plateau": False}
    assert pace([], found=8, needed=100, now=NOW)["rate_per_hour"] is None


def test_rate_and_eta_from_the_sample_an_hour_ago() -> None:
    samples = [(_at(130), 0), (_at(70), 10), (_at(61), 12), (_at(30), 20), (_at(5), 28)]
    result = pace(samples, found=30, needed=100, now=NOW)
    # anchor = newest sample at least 60 min old: (61 min ago, 12) -> 18 parts in 61 min
    assert result["rate_per_hour"] == 17.7
    assert result["eta_hours"] == round(60 / (18 / (61 / 60)), 1)
    assert result["plateau"] is False


def test_young_history_uses_the_oldest_sample() -> None:
    result = pace([(_at(30), 4), (_at(12), 9)], found=10, needed=100, now=NOW)
    assert result["rate_per_hour"] == 12.0
    assert result["plateau"] is False  # not an hour of history yet


def test_plateau_after_an_hour_below_one_part_per_hour() -> None:
    result = pace([(_at(90), 40), (_at(65), 40), (_at(20), 40)], found=40, needed=100, now=NOW)
    assert result == {"rate_per_hour": 0.0, "eta_hours": None, "plateau": True}


def test_ninety_percent_reached_is_not_a_plateau() -> None:
    result = pace([(_at(90), 88), (_at(65), 90)], found=90, needed=100, now=NOW)
    assert result["eta_hours"] == 0.0 and result["plateau"] is False
