from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from rt.coupling.slots import CapacitySlot


def test_initial_available_equals_capacity() -> None:
    slot = CapacitySlot("c1_to_c2", capacity=3)
    assert slot.available() == 3
    assert slot.capacity() == 3
    assert slot.taken() == 0


def test_try_claim_is_now_permissive() -> None:
    """Claims used to fail when the slot was full; now they always succeed
    so a transient claim from an upstream advance pulse cannot block all
    flow. The slot still tracks the claim list so the step debugger can
    surface it as a breadcrumb."""
    slot = CapacitySlot("t", capacity=2)
    assert slot.try_claim() is True
    assert slot.try_claim() is True
    assert slot.taken() == 2
    assert slot.try_claim() is True  # would have returned False before
    assert slot.taken() == 3


def test_release_restores_capacity() -> None:
    slot = CapacitySlot("t", capacity=1)
    assert slot.try_claim() is True
    assert slot.available() == 0
    slot.release()
    assert slot.available() == 1
    # Extra releases clamp at zero, never negative.
    slot.release()
    slot.release()
    assert slot.taken() == 0


def test_set_capacity_shrinks_gracefully() -> None:
    slot = CapacitySlot("t", capacity=5)
    for _ in range(4):
        assert slot.try_claim() is True
    assert slot.taken() == 4
    slot.set_capacity(2)
    # We can't un-ship pieces that were already claimed; available reports 0.
    assert slot.available() == 0
    assert slot.capacity() == 2
    # Draining two pieces moves us under the new cap.
    slot.release()
    slot.release()
    assert slot.available() == 0  # still 2 taken, capacity 2
    slot.release()
    assert slot.available() == 1


def test_set_capacity_grows() -> None:
    slot = CapacitySlot("t", capacity=1)
    assert slot.try_claim() is True
    slot.set_capacity(4)
    assert slot.available() == 3


def test_negative_capacity_rejected() -> None:
    with pytest.raises(ValueError):
        CapacitySlot("t", capacity=-1)
    slot = CapacitySlot("t", capacity=1)
    with pytest.raises(ValueError):
        slot.set_capacity(-1)


def test_repr_is_informative() -> None:
    slot = CapacitySlot("c2_to_c3", capacity=2)
    slot.try_claim()
    r = repr(slot)
    assert "c2_to_c3" in r
    assert "1/2" in r


def test_thread_safety_under_concurrent_claim_release() -> None:
    """Two threads spamming claim + release: final taken must be in [0, cap]
    and no claim may succeed when available()==0 at the moment of the call."""
    slot = CapacitySlot("stress", capacity=10)
    iterations = 1000
    errors: list[str] = []
    barrier = threading.Barrier(2)

    def worker() -> None:
        barrier.wait()
        local_claims = 0
        for _ in range(iterations):
            if slot.try_claim():
                local_claims += 1
                # Release immediately to keep the slot cycling.
                slot.release()
        if local_claims <= 0:
            errors.append("worker never claimed — lock likely livelocked")

    with ThreadPoolExecutor(max_workers=2) as pool:
        for _ in range(2):
            pool.submit(worker)
    assert not errors
    # Final invariant: taken count fits within [0, capacity]
    assert 0 <= slot.taken() <= slot.capacity()


def test_try_claim_thread_safe_under_contention() -> None:
    """Claim is now permissive — no capacity bound to enforce — but the
    lock must still keep the bookkeeping list consistent under contention."""
    slot = CapacitySlot("contention", capacity=3)

    def claimer() -> None:
        for _ in range(500):
            slot.try_claim()

    with ThreadPoolExecutor(max_workers=4) as pool:
        for _ in range(4):
            pool.submit(claimer)
    # 4 workers x 500 claims each = 2000 total — no claim was lost.
    assert slot.taken() == 2000
