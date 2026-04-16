import os
import sqlite3
import tempfile
import unittest
from pathlib import Path


class SecretsCryptoTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_env = {
            key: os.environ.get(key)
            for key in ("LOCAL_STATE_DB_PATH", "MACHINE_SPECIFIC_PARAMS_PATH", "SORTER_SECRET_SEED_PATH")
        }
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp = Path(self._tmpdir.name)
        os.environ["LOCAL_STATE_DB_PATH"] = str(tmp / "local_state.sqlite")
        os.environ.pop("MACHINE_SPECIFIC_PARAMS_PATH", None)
        os.environ.pop("SORTER_SECRET_SEED_PATH", None)
        self.db_path = tmp / "local_state.sqlite"
        self.seed_path = tmp / ".secret_seed"

    def tearDown(self) -> None:
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmpdir.cleanup()

    def _raw_state_value(self, key: str) -> str | None:
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT json_value FROM state_entries WHERE key = ?", (key,)
            ).fetchone()
        finally:
            conn.close()
        return None if row is None else str(row[0])

    def test_api_keys_round_trip_through_ciphertext(self) -> None:
        from local_state import get_api_keys, set_api_keys

        set_api_keys({"openrouter": "secret-key-abc"})

        raw = self._raw_state_value("api_keys")
        assert raw is not None
        # Stored JSON should not contain the plaintext secret.
        self.assertNotIn("secret-key-abc", raw)
        self.assertIn("fernet:v1:", raw)

        # Public API returns the plaintext back after decrypt.
        self.assertEqual({"openrouter": "secret-key-abc"}, get_api_keys())

    def test_legacy_plaintext_api_keys_are_migrated_on_read(self) -> None:
        from local_state import get_api_keys, initialize_local_state, _connection, _set_json

        initialize_local_state()
        # Simulate legacy plaintext entry written by an older build.
        with _connection() as conn:
            _set_json(conn, "api_keys", {"gemini": "legacy-plaintext-token"})
            conn.commit()

        # First read decrypts (no-op for plaintext) and transparently re-encrypts.
        result = get_api_keys()
        self.assertEqual({"gemini": "legacy-plaintext-token"}, result)

        raw = self._raw_state_value("api_keys")
        assert raw is not None
        self.assertNotIn("legacy-plaintext-token", raw)
        self.assertIn("fernet:v1:", raw)

    def test_hive_api_tokens_are_encrypted_at_rest(self) -> None:
        from local_state import get_hive_config, set_hive_config

        set_hive_config({
            "targets": [
                {
                    "id": "primary",
                    "name": "Primary",
                    "url": "https://example.test",
                    "api_token": "hive-token-xyz",
                    "enabled": True,
                }
            ]
        })

        raw = self._raw_state_value("hive")
        assert raw is not None
        self.assertNotIn("hive-token-xyz", raw)
        self.assertIn("fernet:v1:", raw)

        config = get_hive_config()
        assert config is not None
        self.assertEqual("hive-token-xyz", config["targets"][0]["api_token"])

    def test_seed_file_is_created_with_restrictive_mode(self) -> None:
        from local_state import set_api_keys

        set_api_keys({"openrouter": "kick-off"})

        self.assertTrue(self.seed_path.exists())
        mode = self.seed_path.stat().st_mode & 0o777
        # chmod may silently no-op on some filesystems; only assert when it stuck.
        if mode != 0:
            self.assertEqual(0o600, mode)

    def test_missing_ciphertext_decrypts_to_empty_string(self) -> None:
        from secrets_crypto import decrypt_str

        self.assertEqual("", decrypt_str("fernet:v1:this-is-not-a-real-token"))


if __name__ == "__main__":
    unittest.main()
