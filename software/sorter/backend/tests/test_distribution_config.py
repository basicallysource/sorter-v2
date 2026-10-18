import logging
import unittest
from types import SimpleNamespace

from irl.parse_user_toml import loadMachineConfig


def _gc():
    return SimpleNamespace(logger=logging.getLogger("test"))


class DistributionConfigTests(unittest.TestCase):
    def test_chute_settle_ms_is_read_and_validated(self):
        self.assertEqual(3500, loadMachineConfig(_gc(), {"distribution": {"chute_settle_ms": 3500}}).chute_settle_ms)
        self.assertIsNone(loadMachineConfig(_gc(), {}).chute_settle_ms)
        self.assertIsNone(loadMachineConfig(_gc(), {"distribution": {"chute_settle_ms": 50}}).chute_settle_ms)
        self.assertIsNone(loadMachineConfig(_gc(), {"distribution": {"chute_settle_ms": "slow"}}).chute_settle_ms)


if __name__ == "__main__":
    unittest.main()
