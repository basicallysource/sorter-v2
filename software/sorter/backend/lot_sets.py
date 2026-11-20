from __future__ import annotations

import threading
import time
from typing import Any

import hive_metadata
import sorting_runs

# The LEGO sets a lot looks like it came from, for the lot's summary on the
# dashboard. Hive holds the set inventories and does the matching; the answer
# is kept here and asked for again in the background as the lot grows.

_FRESH_S = 300.0  # ask Hive again this long after an answer
_RETRY_S = 30.0  # and this long after it could not answer
_LIMIT = 12

_lock = threading.Lock()
_answers: dict[str, list[dict[str, Any]]] = {}
_next_ask: dict[str, float] = {}
_asking: set[str] = set()


def _row(found: dict[str, Any]) -> dict[str, Any]:
    return {
        "set_num": found.get("set_num"),
        "name": found.get("name"),
        "year": found.get("year"),
        "image_url": found.get("image_url"),
        "total_pieces": found.get("required_pieces"),
        "have_pieces": found.get("covered_pieces"),
        "share": found.get("share"),
        "distinctive_have": found.get("distinctive_lines_present"),
        "distinctive_total": found.get("distinctive_lines"),
    }


def _ask(lot_id: str) -> None:
    wait = _RETRY_S
    try:
        client = hive_metadata._client()
        if client is not None:
            inventory = [
                {"part_id": part["part_id"], "color_id": part["color_id"], "quantity": part["in_lot"]}
                for part in sorting_runs.lotParts(lot_id)["parts"]
                if part["in_lot"] > 0
            ]
            found = client.match_sets(inventory, limit=_LIMIT, missing_limit=0) if inventory else {"sets": []}
            with _lock:
                _answers[lot_id] = [_row(s) for s in found.get("sets") or []]
            wait = _FRESH_S
    except Exception:
        # Hive away, still building its index, or without the endpoint: the
        # last answer stands and it is asked again soon.
        pass
    finally:
        with _lock:
            _next_ask[lot_id] = time.time() + wait
            _asking.discard(lot_id)


def candidateSets(lot_id: str) -> list[dict[str, Any]]:
    """The sets whose pieces show up in the lot, likeliest first; empty when
    none stands out (Hive wants several of a set's own rare pieces and a fair
    share of all of them), and the dashboard then shows no sets at all. Each:

        {"set_num", "name", "year", "image_url", "total_pieces", "have_pieces",
         "share", "distinctive_have", "distinctive_total"}

    Never waits on the network: it returns the last answer and, when that is
    old, asks Hive again on a thread of its own."""
    with _lock:
        if lot_id not in _asking and time.time() >= _next_ask.get(lot_id, 0.0):
            _asking.add(lot_id)
            threading.Thread(target=_ask, args=(lot_id,), name="lot-sets", daemon=True).start()
        return list(_answers.get(lot_id, []))
