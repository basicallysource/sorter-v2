import unittest

from subsystems.feeder.pulse_perception.config import (
    CHANNEL_MOVE_SPEED_KEYS,
    LEGACY_MOVE_SPEED_KEY,
    PulsePerceptionConfig,
    channelMoveSpeed,
    configFromDict,
    configToDict,
    migrateLegacyKeys,
)


class ChannelMoveSpeedTests(unittest.TestCase):
    def test_resolves_each_channel_independently(self) -> None:
        cfg = configFromDict(
            {
                "ch1_move_speed_usteps_per_s": 1200,
                "ch2_move_speed_usteps_per_s": 2400,
                "ch3_move_speed_usteps_per_s": 3600,
            }
        )
        self.assertEqual(
            [channelMoveSpeed(cfg, ch) for ch in (1, 2, 3)], [1200, 2400, 3600]
        )

    def test_unknown_channel_falls_back_to_a_nonzero_speed(self) -> None:
        # A 0 speed wedges the firmware distance move (see
        # MIN_MOVE_SPEED_USTEPS_PER_S in flow.py), so the fallback must be a real
        # channel's speed rather than a missing-attribute zero.
        cfg = PulsePerceptionConfig()
        cfg.ch2_move_speed_usteps_per_s = 2400
        self.assertEqual(channelMoveSpeed(cfg, 9), 2400)


class LegacyMoveSpeedMigrationTests(unittest.TestCase):
    def test_seeds_all_channels_from_the_retired_shared_key(self) -> None:
        migrated = migrateLegacyKeys(
            {LEGACY_MOVE_SPEED_KEY: 2600, "drop_pulse_pause_ms": 120}
        )
        self.assertNotIn(LEGACY_MOVE_SPEED_KEY, migrated)
        for key in CHANNEL_MOVE_SPEED_KEYS.values():
            self.assertEqual(migrated[key], 2600)
        self.assertEqual(migrated["drop_pulse_pause_ms"], 120)

    def test_existing_per_channel_values_win_over_the_legacy_key(self) -> None:
        migrated = migrateLegacyKeys(
            {LEGACY_MOVE_SPEED_KEY: 2600, "ch2_move_speed_usteps_per_s": 900}
        )
        self.assertEqual(migrated["ch2_move_speed_usteps_per_s"], 900)
        self.assertEqual(migrated["ch1_move_speed_usteps_per_s"], 2600)
        self.assertEqual(migrated["ch3_move_speed_usteps_per_s"], 2600)

    def test_migration_is_a_noop_without_the_legacy_key(self) -> None:
        section = {"ch1_move_speed_usteps_per_s": 1500}
        self.assertEqual(migrateLegacyKeys(section), section)

    def test_does_not_leave_the_legacy_key_in_the_serialized_config(self) -> None:
        serialized = configToDict(PulsePerceptionConfig())
        self.assertNotIn(LEGACY_MOVE_SPEED_KEY, serialized)
        for key in CHANNEL_MOVE_SPEED_KEYS.values():
            self.assertIn(key, serialized)


if __name__ == "__main__":
    unittest.main()
