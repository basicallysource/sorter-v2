from __future__ import annotations

from typing import Any

# The LEGO sets a lot looks like it came from, for the lot's summary on the
# dashboard. Hive holds the set inventories, so the answer comes from there.


def candidateSets(lot_id: str) -> list[dict[str, Any]]:
    """The sets whose pieces show up in the lot, likeliest first; empty when
    none stands out (few of a set's own pieces, or a small share of all of
    them), and the dashboard then shows no sets at all. Each one:

        {
            "set_num": "75192-1",
            "name": "Millennium Falcon",
            "year": 2017,
            "image_url": "https://...",  # or None
            "total_pieces": 7541,        # in the set
            "have_pieces": 412,          # of them, found in the lot
            "share": 0.055,              # have_pieces / total_pieces
            "distinctive_have": 9,       # parts few other sets have, found in the lot
            "distinctive_total": 31,     # such parts in the set
        }

    lotSummary calls this on an API thread each time it rebuilds a lot's
    summary (every few seconds while a dashboard shows it), so an answer that
    takes the network must be kept here and never waited on for long."""
    return []
