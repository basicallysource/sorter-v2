"""Every upstream picture of the piece on the classification channel.

Follows pieces through C2, C3 and C4 from the control data the machine already
records (every detection of every frame, every motor move), and when a piece is
classified walks back from its C4 track to the C3 and C2 tracklets that were the
same piece, each step with a probability. Order, timing and what the rotors
turned carry the identity; the pictures are only looked up at the end.

    record.py     the live record: detections in ring coordinates, odometers
    tracklets.py  runs of detections that are surely one piece
    nodes.py      the question put to the model, as arrays
    model.py      the model (ONNX)
    journey.py    every tracklet's predecessor, and a piece's walk back
    live.py       the thread that keeps all of it current while sorting
    replay.py     the same over a recorded segment, from the command line
"""
