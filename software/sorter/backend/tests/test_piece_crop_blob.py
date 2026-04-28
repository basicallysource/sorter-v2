"""Tests for Phase 3 piece-crop disk persistence helpers.

Covers the ``blob_manager.piece_crops_dir`` / ``write_piece_crop`` contract:
roundtrip of JPEG bytes, uuid-scoped subfolder layout, and graceful
degradation when the filesystem refuses to cooperate (disk full /
permission denied).
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

import blob_manager


class PieceCropBlobTests(unittest.TestCase):
    def setUp(self) -> None:
        # Route every disk write at a fresh tmpdir so we don't spray JPEGs
        # into the real ``blob/`` tree. ``_tmpdir`` keeps the context
        # alive through the test.
        self._tmpdir_ctx = _TempDirCtx()
        self._tmpdir = self._tmpdir_ctx.__enter__()
        self._blob_dir_patch = mock.patch.object(
            blob_manager, "BLOB_DIR", Path(self._tmpdir)
        )
        self._blob_dir_patch.start()

    def tearDown(self) -> None:
        self._blob_dir_patch.stop()
        self._tmpdir_ctx.__exit__(None, None, None)

    def test_write_piece_crop_roundtrip(self) -> None:
        jpeg_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\xff\xd9"
        rel = blob_manager.write_piece_crop(
            "test-uuid", 7, "wedge", 3, jpeg_bytes
        )
        self.assertIsNotNone(rel)
        self.assertEqual(
            str(rel),
            str(Path("piece_crops") / "test-uuid" / "seg7" / "wedge_003.jpg"),
        )
        abs_path = Path(self._tmpdir) / rel
        self.assertTrue(abs_path.is_file())
        self.assertEqual(abs_path.read_bytes(), jpeg_bytes)

    def test_piece_crops_dir_uses_piece_uuid_subfolder(self) -> None:
        target = blob_manager.piece_crops_dir("abc-123")
        self.assertTrue(target.exists() and target.is_dir())
        self.assertEqual(target.name, "abc-123")
        self.assertEqual(target.parent.name, "piece_crops")
        self.assertEqual(str(target.parent.parent), self._tmpdir)

    def test_write_piece_crop_handles_disk_error_gracefully(self) -> None:
        original_write_bytes = Path.write_bytes

        def _boom(self, data):  # noqa: ANN001
            raise OSError("disk full")

        with mock.patch.object(Path, "write_bytes", _boom):
            result = blob_manager.write_piece_crop(
                "uuid-disk", 1, "piece", 0, b"\xff\xd8\xff"
            )
        self.assertIsNone(result)

        # Sanity — after restoring, the next write should succeed.
        self.assertTrue(Path.write_bytes is original_write_bytes)
        rel = blob_manager.write_piece_crop(
            "uuid-disk", 1, "piece", 0, b"\xff\xd8\xff"
        )
        self.assertIsNotNone(rel)

    def test_write_piece_crop_rejects_unknown_kind(self) -> None:
        result = blob_manager.write_piece_crop(
            "uuid-x", 0, "garbage", 0, b"\xff\xd8\xff"
        )
        self.assertIsNone(result)

    def test_write_piece_crop_returns_relative_path_under_blob_dir(self) -> None:
        rel = blob_manager.write_piece_crop(
            "uuid-rel", 0, "snapshot", 0, b"\xff\xd8\xff"
        )
        self.assertIsNotNone(rel)
        # Relative paths do not start with the tmpdir's absolute prefix.
        self.assertFalse(Path(str(rel)).is_absolute())
        # Joining with BLOB_DIR recovers the concrete file.
        joined = Path(self._tmpdir) / rel
        self.assertTrue(joined.is_file())

    def test_write_matrix_shot_crop_uses_matrix_kind(self) -> None:
        rel = blob_manager.write_piece_crop(
            "uuid-matrix", 0, "matrix", 2, b"\xff\xd8\xff"
        )
        self.assertIsNotNone(rel)
        self.assertEqual(
            str(rel),
            str(Path("piece_crops") / "uuid-matrix" / "seg0" / "matrix_002.jpg"),
        )


class _TempDirCtx:
    """Tiny context manager wrapper so setUp/tearDown can hold the state."""

    def __enter__(self) -> str:
        import tempfile

        self._td = tempfile.TemporaryDirectory()
        return self._td.name

    def __exit__(self, exc_type, exc, tb) -> None:
        self._td.cleanup()


if __name__ == "__main__":
    unittest.main()
