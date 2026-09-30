import unittest

from plo_chipev.config import Config, ConfigError


class ConfigTest(unittest.TestCase):
    def test_default_config_serializes_explicit_fixed_tournament_semantics(self):
        config = Config()

        self.assertEqual(config.to_dict(), {
            "variant": "PLO4-high",
            "format": "tournament",
            "players": 6,
            "stack_bb": 100.0,
            "small_blind_bb": 0.5,
            "big_blind_bb": 1.0,
            "ante_bb": 0.0,
            "rake": 0.0,
            "utility": "chip_ev",
            "payouts_or_icm": False,
            "postflop": "check_down",
            "max_voluntary_raises": 2,
            "hand_abstraction": "features",
            "seed": 1,
            "iterations": 1_000,
            "time_limit_seconds": None,
            "max_nodes": 1_000_000,
            "max_infosets": 250_000,
            "averaging_epsilon": 0.05,
        })
        self.assertEqual(Config.from_dict(config.to_dict()), config)


    def test_config_rejects_changes_to_fixed_game_or_invalid_abstraction(self):
        cases = [
            ({"players": 5}, "players must be 6"),
            ({"rake": 0.01}, "rake must be 0"),
            ({"postflop": "betting"}, "postflop must be check_down"),
            ({"hand_abstraction": "tiers"}, "hand_abstraction"),
            ({"stack_bb": True}, "stack_bb must be numeric"),
            ({"stack_bb": 99}, "stack_bb must be 100"),
        ]
        for change, message in cases:
            with self.subTest(change=change):
                data = Config().to_dict() | change
                with self.assertRaisesRegex(ConfigError, message):
                    Config.from_dict(data)

    def test_config_rejects_unknown_keys(self):
        with self.assertRaisesRegex(ConfigError, "unknown configuration: surprise"):
            Config.from_dict(Config().to_dict() | {"surprise": 1})
