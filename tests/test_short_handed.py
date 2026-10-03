from __future__ import annotations

import unittest

from plo_premium_proof.__main__ import main  # noqa: F401  (CLI imports cleanly)
from plo_premium_proof.fullsolve import FullSolveConfig, meta_tree_config, tree_config
from plo_premium_proof.fulltree import FullTree


class ShortHandedConfigTest(unittest.TestCase):
    def test_six_max_without_ante_on_top_keeps_the_old_tree(self):
        config = tree_config(40.0, (4, 2, 2, 2), 0.116)
        self.assertEqual(config.stacks, ())
        self.assertEqual(config.cache_name(), "fulltree-40bb-4222-a0.116.npz")

    def test_ante_on_top_adds_the_ante_to_every_seat(self):
        config = FullSolveConfig(seconds=1, stack_bb=20.0, ante_bb=0.116, seats=3, ante_on_top=True).tree_config()
        self.assertEqual(config.seat_stacks, (20.116,) * 3)
        tree = FullTree.build(meta_tree_config({"stack_bb": 3.0, "raise_caps": [2, 0, 0, 0], "ante_bb": 0.116,
                                                "seats": 2, "ante_on_top": True}), cache_dir=None)
        self.assertEqual(tree.seats, 2)
        # after the ante, the small blind has 3 - 0.5 behind and the big blind 3 - 1
        self.assertAlmostEqual(float(tree.behind[0, 0]), 2.5)
        self.assertAlmostEqual(float(tree.behind[0, 1]), 2.0)

    def test_seat_count_is_checked(self):
        with self.assertRaises(ValueError):
            FullSolveConfig(seconds=1, seats=7)


if __name__ == "__main__":
    unittest.main()
