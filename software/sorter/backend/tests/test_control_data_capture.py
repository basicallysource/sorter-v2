"""A control-data state record carries each piece's tracker colour, and the
detector boxes behind a merged piece, so a replay can see what the tracker and
the merge saw."""

from types import SimpleNamespace

import control_data_store
from perception import transition_capture
from perception.state import ChannelState, PieceObservation


def test_state_record_has_colours_and_merged_boxes(monkeypatch):
    piece = PieceObservation(
        com_forward_to_exit_deg=200.0,
        com_section=10,
        zone_code=1,
        bbox=(10, 10, 90, 220),
        sv_bt_track_id=19,
        color=(0.12345, -0.2, 0.5),
    )
    state = ChannelState(
        ts=100.0,
        in_drop=True,
        in_exit=False,
        n_pieces=1,
        pieces=(piece,),
        merged=(((10, 10, 90, 220), ((10, 10, 90, 150), (12, 140, 88, 220))),),
    )
    service = SimpleNamespace(read_states=lambda: {4: state}, read_pieces_and_frame=lambda ch: None)
    records = []
    monkeypatch.setattr(control_data_store, "record", records.append)
    collector = transition_capture.ControlDataCollector(perception_service=service, gc=None, irl_config=None)
    collector._sampleStates()
    (rec,) = [r for r in records if r["type"] == "state"]
    assert rec["pieces"][0][7] == 19 and rec["pieces"][0][8] == [0.123, -0.2, 0.5]
    assert rec["merged"] == [[[10, 10, 90, 220], [[10, 10, 90, 150], [12, 140, 88, 220]]]]
