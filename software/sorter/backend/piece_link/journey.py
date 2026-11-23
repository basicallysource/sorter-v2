"""Every tracklet's predecessor with its probability, and a piece's walk back
from the classification channel.

Asked with nothing kept (a recorded segment, read whole), every tracklet goes
to the model. Asked with a Kept (the running machine), only what a walk can use
and what is new does: a tracklet that has ended keeps its numbers and its
answer, and one still riding C2 or C3 is not asked at all, since no piece
already on the classification channel can have come from it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .model import LinkModel
from .nodes import MIN_NODE, N_CAND, KeptRows, Key, Nodes, Questions, makeNodes, queryOf, questions, timeOrders
from .record import Window

# An answer is final once nothing about its question can still change: its rivals have all started (they start
# within 8 s of it). One given sooner is used until then and asked once more.
FINAL_AFTER_START_S = 10.0
# Links at least this sure make a line: a piece's earlier ride is often several tracklets.
LINE_P = 0.6
LINE_STEPS = 12
# A node this likely to be two pieces boxed as one is walked through, never taken as the piece's look.
MULTI_P = 0.5
MAX_STEPS = 40


@dataclass
class Answer:
    cand: list[Optional[Key]]
    prob: np.ndarray
    multi: float
    final: bool
    # The pick's probability with its line taken in, once the answer is final.
    p: Optional[float] = None


@dataclass
class Kept:
    answers: dict[Key, Answer] = field(default_factory=dict)
    nodes: KeptRows = field(default_factory=KeptRows)

    def keepOnly(self, alive: set[Key]) -> None:
        if len(self.answers) > 2 * len(alive) + 64:
            self.answers = {k: v for k, v in self.answers.items() if k in alive}
        if len(self.nodes.rows) > 2 * len(alive) + 64:
            self.nodes.rows = {k: v for k, v in self.nodes.rows.items() if k in alive}


class Journey:
    def __init__(
        self,
        win: Window,
        model: LinkModel,
        kept: Optional[Kept] = None,
        since: Optional[float] = None,
    ) -> None:
        self.win = win
        self.model = model
        self.nd: Nodes = makeNodes(win, since, kept.nodes if kept is not None else None)
        self.order = timeOrders(self.nd)
        self.asked_fresh = 0
        nd = self.nd
        n = len(nd)
        keys: list[Key] = [(int(c), int(g)) for c, g in zip(nd.ch, nd.gid)]
        index = {k: i for i, k in enumerate(keys)}
        self.node_at: dict[int, np.ndarray] = {}
        for ch, tl in win.tls.items():
            at = np.full(tl.n, -1, dtype=np.int64)
            sel = np.flatnonzero(nd.ch == ch)
            at[nd.tl[sel]] = sel
            self.node_at[ch] = at
        self.cand = np.full((n, N_CAND), -1, dtype=np.int64)
        self.prob = np.zeros((n, 1 + N_CAND), dtype=np.float32)
        self.multi = np.zeros(n, dtype=np.float32)
        self.answered = np.zeros(n, dtype=bool)
        # Answered a moment ago, before the answer was final: good enough for a line, asked again when a walk stands on it.
        self.early = np.zeros(n, dtype=bool)
        ended = nd.t1 < np.array([win.ended_before[int(c)] for c in nd.ch], dtype=float)
        old = win.now - nd.t0 > FINAL_AFTER_START_S
        fixed = np.zeros(n, dtype=bool)
        fixed_p = np.zeros(n, dtype=np.float32)
        fresh: list[int] = []
        for j, key in enumerate(keys):
            if kept is None:
                fresh.append(j)
                continue
            if not ended[j]:
                # Still under way: asked on the classification channel (the piece being followed), not above it.
                if nd.ch[j] == 4:
                    fresh.append(j)
                continue
            answer = kept.answers.get(key)
            if answer is None or (old[j] and not answer.final):
                fresh.append(j)
                continue
            self.cand[j] = [index.get(k, -1) if k is not None else -1 for k in answer.cand]
            self.prob[j] = answer.prob
            self.multi[j] = answer.multi
            self.answered[j] = True
            self.early[j] = not answer.final
            if answer.p is not None:
                fixed[j] = True
                fixed_p[j] = answer.p
        if fresh:
            q = questions(nd, win, np.array(fresh, dtype=np.int64), self.order)
            prob, multi = model.run(q.tokens, q.mask, nd.ctx)
            self.asked_fresh = len(fresh)
            for r, j in enumerate(fresh):
                self.cand[j] = q.cand[r]
                self.prob[j] = prob[r]
                self.multi[j] = multi[r]
                self.answered[j] = True
                if kept is not None and ended[j]:
                    kept.answers[keys[j]] = Answer(
                        [keys[c] if c >= 0 else None for c in q.cand[r]], prob[r].copy(), float(multi[r]), bool(old[j])
                    )
        # Each node's most likely predecessor (-1 for none) and that answer's probability (for none too).
        self.pred = np.full(n, -1, dtype=np.int64)
        self.p = np.zeros(n, dtype=np.float32)
        self._line: dict[int, set[int]] = {}
        if n:
            pick = self.prob.argmax(axis=1)
            self.p[:] = self.prob[np.arange(n), pick]
            names = pick > 0
            self.pred[names] = self.cand[np.flatnonzero(names), pick[names] - 1]
            self.p[fixed] = fixed_p[fixed]
            # A piece's earlier ride is often several tracklets, and each is a right answer, so the
            # probability is spread over them. The pick stays the top candidate; its probability takes in the
            # candidates on one line with it (its own earlier tracklets, and later ones that lead back to it
            # by sure links). Only one line: tracklets that merely share an ancestor may be two pieces that
            # rode boxed as one.
            open_ = np.flatnonzero(~fixed & (self.pred >= 0))
            for _ in range(2):
                before = self.p.copy()
                line: dict[int, set[int]] = {}
                for j in open_:
                    top = int(self.pred[j])
                    self.p[j] = min(max(self._onLine(self.cand[j], self.prob[j, 1:], top, before, line), float(self.p[j])), 1.0)
            if kept is not None:
                for j in np.flatnonzero(~fixed & ended & old):
                    answer = kept.answers.get(keys[j])
                    if answer is not None and answer.final:
                        answer.p = float(self.p[j])
                kept.keepOnly(set(keys))

    def _lineOf(self, node: int, p: np.ndarray, line: dict[int, set[int]]) -> set[int]:
        seen = line.get(node)
        if seen is None:
            seen = set()
            cur = node
            for _ in range(LINE_STEPS):
                if self.pred[cur] < 0 or p[cur] < LINE_P:
                    break
                cur = int(self.pred[cur])
                if cur in seen:
                    break
                seen.add(cur)
            line[node] = seen
        return seen

    def _onLine(self, cand: np.ndarray, prob: np.ndarray, top: int, p: np.ndarray, line: dict[int, set[int]]) -> float:
        total = 0.0
        of_top = self._lineOf(top, p, line)
        for c, q in zip(cand.tolist(), prob.tolist()):
            if c >= 0 and q > 0.0 and (c == top or c in of_top or top in self._lineOf(c, p, line)):
                total += q
        return total

    def _answerNow(self, node: int) -> None:
        # A tracklet not asked because it was still under way, and a walk has reached it after all (a box
        # that stayed on after its piece fell): asked on the spot, for this look only.
        q = questions(self.nd, self.win, np.array([node], dtype=np.int64), self.order)
        prob, multi = self.model.run(q.tokens, q.mask, self.nd.ctx)
        self.cand[node] = q.cand[0]
        self.prob[node] = prob[0]
        self.multi[node] = multi[0]
        self.answered[node] = True
        self.early[node] = False
        self.asked_fresh += 1
        pick = int(prob[0].argmax())
        self.p[node] = prob[0, pick]
        self.pred[node] = int(q.cand[0, pick - 1]) if pick > 0 else -1
        if self.pred[node] >= 0:
            top = int(self.pred[node])
            self.p[node] = min(max(self._onLine(self.cand[node], prob[0, 1:], top, self.p, self._line), float(self.p[node])), 1.0)

    def nodeOf(self, ch: int, det: int) -> int:
        return int(self.node_at[ch][self.win.tls[ch].of[det]])

    def detections(self, node: int) -> tuple[int, np.ndarray]:
        ch = int(self.nd.ch[node])
        return ch, self.win.tls[ch].members[int(self.nd.tl[node])]

    def ask(self, node: int, q_node: int) -> tuple[int, float]:
        """`node`'s predecessor for the piece as it looked in `q_node`, a later tracklet of it."""
        nd = self.nd
        query = queryOf(nd, q_node, below=bool(nd.ch[q_node] != nd.ch[node]))
        q: Questions = questions(nd, self.win, np.array([node], dtype=np.int64), self.order, [query])
        prob = self.model.run(q.tokens, q.mask, nd.ctx)[0][0]
        pick = int(prob.argmax())
        if pick == 0:
            return -1, float(prob[0])
        top = int(q.cand[0, pick - 1])
        return top, min(max(self._onLine(q.cand[0], prob[1:], top, self.p, self._line), float(prob[pick])), 1.0)

    def walk(self, node: int, min_p: float = 0.0) -> list[tuple[int, float]]:
        """The piece's earlier tracklets, latest first, each with the probability
        of the whole chain down to it. Each step is asked about the piece as it
        looked in the last tracklet that showed it alone, so the walk can pass
        through a stretch where it rode boxed with another piece."""
        nd = self.nd
        out: list[tuple[int, float]] = []
        prob = 1.0
        cur = node
        q_node = node if self.multi[node] < MULTI_P else -1
        for _ in range(MAX_STEPS):
            if not self.answered[cur] or self.early[cur]:
                self._answerNow(cur)
            if q_node >= 0 and q_node != cur and nd.ch[q_node] - nd.ch[cur] in (0, 1):
                nxt, p = self.ask(cur, q_node)
            else:
                nxt, p = int(self.pred[cur]), float(self.p[cur])
            if nxt < 0:
                break
            prob *= p
            if prob < min_p:
                break
            cur = nxt
            out.append((cur, prob))
            if self.multi[cur] < MULTI_P:
                q_node = cur
        return out

    def pieceWalk(self, c4_tracks: list[int], min_p: float = 0.0) -> list[tuple[int, float]]:
        """A classified piece's journey from its track ids on the classification
        channel: [(node, chain probability), ...] starting with a C4 tracklet of
        the piece (1.0). A landing is often a few short tracklets and a turn of
        the channel cuts the track again, so the walk starts from the earliest
        tracklet of the track that is tied to C3; failing that, from the track's
        main tracklet."""
        c = self.win.ch[4]
        counts: dict[int, int] = {}
        for d in np.flatnonzero(np.isin(c.tid, c4_tracks)):
            node = self.nodeOf(4, int(d))
            if node >= 0:
                counts[node] = counts.get(node, 0) + 1
        if not counts:
            return []
        nd = self.nd
        for node in sorted(counts, key=lambda k: nd.t0[k])[:5]:
            if self.early[node]:
                self._answerNow(node)
            if self.pred[node] >= 0 and nd.ch[self.pred[node]] == 3 and self.p[node] >= 0.5:
                return [(node, 1.0)] + self.walk(node, min_p)
        main = max(counts, key=lambda k: counts[k])
        return [(main, 1.0)] + self.walk(main, min_p)


__all__ = ["Answer", "Journey", "Kept", "MIN_NODE", "MULTI_P"]
