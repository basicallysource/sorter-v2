"""Allocator counters on the admin server-health payload.

These exist to answer one question during a memory investigation: is the process
holding live objects, or is glibc sitting on memory Python already freed? The
counters are only useful if they move with reality, so that is what is asserted
here rather than mere presence.

glibc-specific numbers are absent off Linux (dev Macs), so those assertions are
conditional. `python_allocated_blocks` works everywhere.
"""

from __future__ import annotations

import sys

from app.services.server_health import _glibc_malloc_stats, get_memory_stats

_ON_GLIBC = sys.platform.startswith("linux")


def test_memory_stats_exposes_allocator_counters():
    stats = get_memory_stats()
    assert isinstance(stats["python_allocated_blocks"], int)
    assert stats["python_allocated_blocks"] > 0
    assert "glibc" in stats
    assert "process_rss_bytes" in stats


def test_python_allocated_blocks_tracks_live_objects():
    before = get_memory_stats()["python_allocated_blocks"]
    held = [object() for _ in range(50_000)]
    during = get_memory_stats()["python_allocated_blocks"]
    assert during > before, "allocating objects must raise the block count"
    del held
    after = get_memory_stats()["python_allocated_blocks"]
    assert after < during, "releasing them must lower it again"


def test_glibc_stats_track_large_allocations():
    if not _ON_GLIBC:
        return  # no libc.so.6 to read; the None path is covered below

    stats = _glibc_malloc_stats()
    assert stats is not None, "malloc_info should be readable on glibc"
    baseline = stats["mmapped_bytes"]

    # Big blocks bypass the arenas and are mmapped individually, which is the
    # path mallinfo2 misses entirely — the reason this uses malloc_info.
    held = [bytearray(1024 * 1024) for _ in range(64)]
    during = _glibc_malloc_stats()
    assert during is not None
    assert during["mmapped_bytes"] > baseline + 32 * 1024 * 1024, (
        "64 MB of live buffers should be visible in the allocator's own accounting"
    )

    del held
    after = _glibc_malloc_stats()
    assert after is not None
    assert after["mmapped_bytes"] < during["mmapped_bytes"], "freed blocks should drop out"


def test_glibc_stats_shape_is_stable():
    stats = _glibc_malloc_stats()
    if stats is None:
        return  # not glibc
    for key in ("arena_bytes", "free_in_arena_bytes", "mmapped_bytes", "heap_count"):
        assert isinstance(stats[key], int), f"{key} must be an int"
        assert stats[key] >= 0
